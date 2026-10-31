"""Check digits of Brazilian identifiers: CPF, CNPJ and NF-e access keys.

CNPJs and access keys may contain letters, following the alphanumeric CNPJ introduced by
IN RFB 2.229/2024 and applied to fiscal documents by Nota Técnica Conjunta 2025.001. Each
character counts as its ASCII code minus 48, so numeric identifiers keep their usual check
digits and the same routine handles both formats.
"""

import re
from dataclasses import dataclass

_CPF_PATTERN = re.compile(r"[0-9]{11}")
_CNPJ_PATTERN = re.compile(r"[A-Z0-9]{12}[0-9]{2}")
_ACCESS_KEY_PATTERN = re.compile(r"[0-9]{6}[A-Z0-9]{12}[0-9]{26}")


def normalize_identifier(value: str) -> str:
    """Remove punctuation and whitespace, and convert letters to upper case."""
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


def _check_digit(characters: str, max_weight: int) -> int:
    """Compute a modulo 11 check digit, with weights rising from 2 at the rightmost position."""
    total = 0
    weight = 2
    for character in reversed(characters):
        total += (ord(character) - 48) * weight
        weight = 2 if weight == max_weight else weight + 1
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


def _has_valid_check_digits(identifier: str, count: int, max_weight: int) -> bool:
    """Verify the last ``count`` digits, each computed over everything before it."""
    for position in range(len(identifier) - count, len(identifier)):
        if _check_digit(identifier[:position], max_weight) != int(identifier[position]):
            return False
    return True


def with_cpf_check_digits(base: str) -> str:
    """Append the two check digits to the first 9 digits of a CPF."""
    first = _check_digit(base, max_weight=11)
    return f"{base}{first}{_check_digit(f'{base}{first}', max_weight=11)}"


def with_cnpj_check_digits(base: str) -> str:
    """Append the two check digits to the first 12 characters of a CNPJ."""
    first = _check_digit(base, max_weight=9)
    return f"{base}{first}{_check_digit(f'{base}{first}', max_weight=9)}"


def with_access_key_check_digit(base: str) -> str:
    """Append the check digit to the first 43 characters of an NF-e access key."""
    return f"{base}{_check_digit(base, max_weight=9)}"


def is_valid_cpf(value: str) -> bool:
    """Check a CPF's format and check digits. Punctuation is ignored."""
    cpf = normalize_identifier(value)
    if not _CPF_PATTERN.fullmatch(cpf) or len(set(cpf)) == 1:
        return False
    return _has_valid_check_digits(cpf, count=2, max_weight=11)


def is_valid_cnpj(value: str) -> bool:
    """Check a numeric or alphanumeric CNPJ's format and check digits. Punctuation is ignored."""
    cnpj = normalize_identifier(value)
    if not _CNPJ_PATTERN.fullmatch(cnpj) or len(set(cnpj)) == 1:
        return False
    return _has_valid_check_digits(cnpj, count=2, max_weight=9)


def is_valid_access_key(value: str) -> bool:
    """Check an NF-e access key's format and check digit. Whitespace is ignored."""
    key = normalize_identifier(value)
    if not _ACCESS_KEY_PATTERN.fullmatch(key):
        return False
    return _has_valid_check_digits(key, count=1, max_weight=9)


@dataclass(frozen=True)
class AccessKey:
    """The fields encoded in the 44 characters of an NF-e access key."""

    state_code: str
    year_month: str
    issuer_id: str
    model: str
    series: str
    number: str
    emission_type: str
    random_code: str
    check_digit: str

    @classmethod
    def parse(cls, value: str) -> "AccessKey":
        """Split a key into its fields.

        Raises:
            ValueError: If the key has an invalid format or check digit.
        """
        if not is_valid_access_key(value):
            raise ValueError("Invalid NF-e access key.")
        key = normalize_identifier(value)
        return cls(
            state_code=key[:2],
            year_month=key[2:6],
            issuer_id=key[6:20],
            model=key[20:22],
            series=key[22:25],
            number=key[25:34],
            emission_type=key[34],
            random_code=key[35:43],
            check_digit=key[43],
        )
