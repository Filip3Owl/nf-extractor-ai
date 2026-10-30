from collections.abc import Callable

import pytest

from nf_extractor.validators.br_identifiers import (
    AccessKey,
    is_valid_access_key,
    is_valid_cnpj,
    is_valid_cpf,
    normalize_identifier,
)


def test_normalize_identifier_removes_punctuation_and_upper_cases() -> None:
    assert normalize_identifier(" 12.abc.345/01de-35 ") == "12ABC34501DE35"


@pytest.mark.parametrize("value", ["52998224725", "529.982.247-25"])
def test_valid_cpf(value: str) -> None:
    assert is_valid_cpf(value)


@pytest.mark.parametrize(
    "value", ["52998224724", "11111111111", "5299822472", "529982247250", "5299822472A", ""]
)
def test_invalid_cpf(value: str) -> None:
    assert not is_valid_cpf(value)


@pytest.mark.parametrize(
    "value",
    [
        "11222333000181",
        "11.222.333/0001-81",
        # Example published by the Brazilian Federal Revenue for the alphanumeric format.
        "12.ABC.345/01DE-35",
        "12abc34501de35",
    ],
)
def test_valid_cnpj(value: str) -> None:
    assert is_valid_cnpj(value)


@pytest.mark.parametrize(
    "value",
    ["11222333000182", "12ABC34501DE36", "00000000000000", "1122233300018", "12ABC34501DE3A", ""],
)
def test_invalid_cnpj(value: str) -> None:
    assert not is_valid_cnpj(value)


def test_valid_numeric_access_key(access_key_factory: Callable[..., str]) -> None:
    assert is_valid_access_key(access_key_factory())


def test_valid_alphanumeric_access_key(access_key_factory: Callable[..., str]) -> None:
    assert is_valid_access_key(access_key_factory(issuer_id="12ABC34501DE35"))


def test_access_key_ignores_spaces(access_key_factory: Callable[..., str]) -> None:
    key = access_key_factory()
    grouped = " ".join(key[index : index + 4] for index in range(0, 44, 4))
    assert is_valid_access_key(grouped)


def test_access_key_with_wrong_check_digit(access_key_factory: Callable[..., str]) -> None:
    key = access_key_factory()
    wrong_digit = str((int(key[-1]) + 1) % 10)
    assert not is_valid_access_key(key[:-1] + wrong_digit)


def test_access_key_with_transposed_digits_is_detected(
    access_key_factory: Callable[..., str],
) -> None:
    key = access_key_factory()
    assert not is_valid_access_key(key[:30] + key[31] + key[30] + key[32:])


@pytest.mark.parametrize(
    "value",
    [
        "",
        "123",
        # Letters are only allowed in the first 12 characters of the issuer field.
        "A" * 44,
        "35261011222333000181550010000001231123456" + "A00",
    ],
)
def test_access_key_with_invalid_format(value: str) -> None:
    assert not is_valid_access_key(value)


def test_parse_access_key_fields(access_key_factory: Callable[..., str]) -> None:
    key = AccessKey.parse(access_key_factory())
    assert key.state_code == "35"
    assert key.year_month == "2610"
    assert key.issuer_id == "11222333000181"
    assert key.model == "55"
    assert key.series == "001"
    assert key.number == "000000123"
    assert key.emission_type == "1"
    assert key.random_code == "12345678"


def test_parse_rejects_invalid_key() -> None:
    with pytest.raises(ValueError, match="Invalid"):
        AccessKey.parse("123")
