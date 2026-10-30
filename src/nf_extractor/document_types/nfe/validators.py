"""Business rules that catch misread values and inconsistent invoices.

These checks are independent of the model, which is what makes its output trustworthy: an
access key whose check digit matches is very unlikely to have been misread. Rules that
genuine invoices always satisfy produce errors. Rules with legitimate exceptions produce
warnings: an item may stay out of the invoice total, for example, and some taxes have no
field of their own in :class:`~nf_extractor.document_types.nfe.schema.Totais`.
"""

from collections.abc import Callable, Iterable, Iterator, Sequence
from decimal import Decimal

from nf_extractor.core.result import Severity, ValidationIssue
from nf_extractor.document_types.nfe.schema import NotaFiscal, Parte
from nf_extractor.validators.br_identifiers import (
    AccessKey,
    is_valid_access_key,
    is_valid_cnpj,
    is_valid_cpf,
    normalize_identifier,
)

# Printed values are rounded to two decimals, so small differences are expected.
MONEY_TOLERANCE = Decimal("0.02")

_CPF_LENGTH = 11


def _issue(
    code: str, message: str, severity: Severity = Severity.ERROR, field: str | None = None
) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, severity=severity, field=field)


def check_required_fields(nota: NotaFiscal) -> Iterator[ValidationIssue]:
    """Warn about missing values that every invoice should have."""
    values = {
        "chave_acesso": nota.chave_acesso,
        "numero": nota.numero,
        "serie": nota.serie,
        "data_emissao": nota.data_emissao,
        "emitente": nota.emitente,
        "totais": nota.totais,
    }
    for name, value in values.items():
        if value is None:
            yield _issue("field.missing", f"Could not read {name}.", Severity.WARNING, field=name)
    if not nota.itens:
        yield _issue("field.missing", "No items were found.", Severity.WARNING, field="itens")


def check_access_key(nota: NotaFiscal) -> Iterator[ValidationIssue]:
    """Verify the format and check digit of the access key."""
    if nota.chave_acesso is not None and not is_valid_access_key(nota.chave_acesso):
        yield _issue(
            "chave_acesso.invalid",
            "The access key has an invalid format or check digit.",
            field="chave_acesso",
        )


def _check_party(party: Parte | None, field: str) -> Iterator[ValidationIssue]:
    if party is None or party.documento is None:
        return
    document = normalize_identifier(party.documento)
    if len(document) == _CPF_LENGTH:
        valid, label = is_valid_cpf(document), "CPF"
    else:
        valid, label = is_valid_cnpj(document), "CNPJ"
    if not valid:
        yield _issue(
            f"{field}.documento.invalid",
            f"The {label} has an invalid format or check digits.",
            field=f"{field}.documento",
        )


def check_parties(nota: NotaFiscal) -> Iterator[ValidationIssue]:
    """Verify the CNPJ or CPF of the issuer and the recipient."""
    yield from _check_party(nota.emitente, "emitente")
    yield from _check_party(nota.destinatario, "destinatario")


def _same_number(printed: str, encoded: str) -> bool:
    """Compare numbers while ignoring punctuation and leading zeros."""
    return normalize_identifier(printed).lstrip("0") == encoded.lstrip("0")


def check_access_key_consistency(nota: NotaFiscal) -> Iterator[ValidationIssue]:
    """Compare the printed fields with the same fields encoded in the access key."""
    if nota.chave_acesso is None or not is_valid_access_key(nota.chave_acesso):
        return
    key = AccessKey.parse(nota.chave_acesso)

    mismatches: list[str] = []
    if nota.emitente is not None and nota.emitente.documento is not None:
        # An issuer identified by CPF appears in the key padded with zeros.
        issuer = normalize_identifier(nota.emitente.documento).zfill(len(key.issuer_id))
        if issuer != key.issuer_id:
            mismatches.append("emitente.documento")
    if nota.modelo is not None and nota.modelo.strip() != key.model:
        mismatches.append("modelo")
    if nota.serie is not None and not _same_number(nota.serie, key.series):
        mismatches.append("serie")
    if nota.numero is not None and not _same_number(nota.numero, key.number):
        mismatches.append("numero")
    if nota.data_emissao is not None and nota.data_emissao.strftime("%y%m") != key.year_month:
        mismatches.append("data_emissao")

    for field in mismatches:
        yield _issue(
            "chave_acesso.mismatch",
            f"The value of {field} differs from the one encoded in the access key.",
            field=field,
        )


def check_item_amounts(nota: NotaFiscal) -> Iterator[ValidationIssue]:
    """Warn when an item's total differs from its quantity times its unit price."""
    for index, item in enumerate(nota.itens):
        if item.quantidade is None or item.valor_unitario is None or item.valor_total is None:
            continue
        expected = item.quantidade * item.valor_unitario
        if abs(expected - item.valor_total) > MONEY_TOLERANCE:
            yield _issue(
                "item.amount_mismatch",
                f"Item total is {item.valor_total}, but quantity times unit price is {expected}.",
                Severity.WARNING,
                field=f"itens[{index}].valor_total",
            )


def check_products_total(nota: NotaFiscal) -> Iterator[ValidationIssue]:
    """Warn when the items do not add up to the products total."""
    if nota.totais is None or nota.totais.valor_produtos is None or not nota.itens:
        return
    totals = [item.valor_total for item in nota.itens]
    if any(value is None for value in totals):
        return
    computed = sum((value for value in totals if value is not None), Decimal(0))
    if abs(computed - nota.totais.valor_produtos) > MONEY_TOLERANCE:
        yield _issue(
            "totais.products_mismatch",
            f"Items add up to {computed}, but the products total is "
            f"{nota.totais.valor_produtos}. Check for missing or misread items.",
            Severity.WARNING,
            field="totais.valor_produtos",
        )


def check_invoice_total(nota: NotaFiscal) -> Iterator[ValidationIssue]:
    """Warn when the invoice total does not follow from its components."""
    totals = nota.totais
    if totals is None or totals.valor_produtos is None or totals.valor_total_nota is None:
        return
    additions = (
        totals.valor_frete,
        totals.valor_seguro,
        totals.outras_despesas,
        totals.valor_ipi,
        totals.valor_icms_st,
    )
    computed = (
        totals.valor_produtos
        + sum((value or Decimal(0) for value in additions), Decimal(0))
        - (totals.valor_desconto or Decimal(0))
    )
    if abs(computed - totals.valor_total_nota) > MONEY_TOLERANCE:
        yield _issue(
            "totais.invoice_mismatch",
            f"The components add up to {computed}, but the invoice total is "
            f"{totals.valor_total_nota}.",
            Severity.WARNING,
            field="totais.valor_total_nota",
        )


VALIDATORS: Sequence[Callable[[NotaFiscal], Iterable[ValidationIssue]]] = (
    check_required_fields,
    check_access_key,
    check_parties,
    check_access_key_consistency,
    check_item_amounts,
    check_products_total,
    check_invoice_total,
)
