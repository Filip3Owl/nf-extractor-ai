from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest

from nf_extractor.core.result import Severity, ValidationIssue
from nf_extractor.document_types import default_registry
from nf_extractor.document_types.nfe import NFE, NotaFiscal
from nf_extractor.document_types.nfe.schema import Item


def _codes(issues: list[ValidationIssue]) -> list[str]:
    return [issue.code for issue in issues]


def test_nfe_is_registered_by_default() -> None:
    assert default_registry().get("nfe") is NFE


def test_valid_invoice_has_no_issues(nota: NotaFiscal) -> None:
    assert NFE.validate(nota) == []


def test_missing_fields_are_warnings_not_errors() -> None:
    empty = NotaFiscal(
        chave_acesso=None,
        modelo=None,
        numero=None,
        serie=None,
        data_emissao=None,
        natureza_operacao=None,
        emitente=None,
        destinatario=None,
        itens=[],
        totais=None,
    )
    issues = NFE.validate(empty)
    assert {issue.field for issue in issues} == {
        "chave_acesso",
        "numero",
        "serie",
        "data_emissao",
        "emitente",
        "totais",
        "itens",
    }
    assert all(issue.severity is Severity.WARNING for issue in issues)


def test_invalid_access_key_is_an_error(nota: NotaFiscal) -> None:
    assert nota.chave_acesso is not None
    nota.chave_acesso = "0" * 43 + "1"
    assert _codes(NFE.validate(nota)) == ["chave_acesso.invalid"]


def test_invalid_issuer_cnpj_is_an_error(nota: NotaFiscal) -> None:
    assert nota.emitente is not None
    nota.emitente.documento = "11.222.333/0001-82"
    issues = NFE.validate(nota)
    assert "emitente.documento.invalid" in _codes(issues)
    assert "The CNPJ" in next(i.message for i in issues if i.code == "emitente.documento.invalid")


def test_invalid_recipient_cpf_is_an_error(nota: NotaFiscal) -> None:
    assert nota.destinatario is not None
    nota.destinatario.documento = "529.982.247-24"
    issues = NFE.validate(nota)
    assert _codes(issues) == ["destinatario.documento.invalid"]
    assert "The CPF" in issues[0].message


def test_invoice_without_recipient_is_valid(nota: NotaFiscal) -> None:
    nota.destinatario = None
    assert NFE.validate(nota) == []


def test_alphanumeric_issuer_is_accepted(
    nota: NotaFiscal, access_key_factory: Callable[..., str]
) -> None:
    assert nota.emitente is not None
    nota.emitente.documento = "12.ABC.345/01DE-35"
    nota.chave_acesso = access_key_factory(issuer_id="12ABC34501DE35")
    assert NFE.validate(nota) == []


def test_issuer_with_cpf_is_compared_with_padding(
    nota: NotaFiscal, access_key_factory: Callable[..., str]
) -> None:
    assert nota.emitente is not None
    nota.emitente.documento = "529.982.247-25"
    nota.chave_acesso = access_key_factory(issuer_id="00052998224725")
    assert NFE.validate(nota) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("numero", "124"),
        ("serie", "2"),
        ("modelo", "65"),
        ("data_emissao", date(2026, 9, 15)),
    ],
)
def test_field_that_differs_from_access_key_is_an_error(
    nota: NotaFiscal, field: str, value: object
) -> None:
    setattr(nota, field, value)
    issues = NFE.validate(nota)
    assert _codes(issues) == ["chave_acesso.mismatch"]
    assert issues[0].field == field
    assert issues[0].severity is Severity.ERROR


def test_issuer_that_differs_from_access_key_is_an_error(nota: NotaFiscal) -> None:
    assert nota.emitente is not None
    nota.emitente.documento = "12.ABC.345/01DE-35"
    issues = NFE.validate(nota)
    assert _codes(issues) == ["chave_acesso.mismatch"]
    assert issues[0].field == "emitente.documento"


def test_punctuated_number_matches_access_key(nota: NotaFiscal) -> None:
    nota.numero = "000.000.123"
    assert NFE.validate(nota) == []


def test_item_amount_mismatch_is_a_warning(nota: NotaFiscal) -> None:
    nota.itens[0].quantidade = Decimal("3")
    issues = NFE.validate(nota)
    assert _codes(issues) == ["item.amount_mismatch"]
    assert issues[0].field == "itens[0].valor_total"
    assert issues[0].severity is Severity.WARNING


def test_rounding_within_tolerance_is_accepted(nota: NotaFiscal) -> None:
    nota.itens[1].quantidade = Decimal("0.333")
    nota.itens[1].valor_unitario = Decimal("76.59")
    assert NFE.validate(nota) == []


def test_missing_item_is_detected_by_products_total(nota: NotaFiscal) -> None:
    nota.itens.pop()
    issues = NFE.validate(nota)
    assert _codes(issues) == ["totais.products_mismatch"]
    assert issues[0].severity is Severity.WARNING


def test_products_total_is_skipped_when_an_item_is_unreadable(nota: NotaFiscal) -> None:
    nota.itens[0].valor_total = None
    assert NFE.validate(nota) == []


def test_invoice_total_mismatch_is_a_warning(nota: NotaFiscal) -> None:
    assert nota.totais is not None
    nota.totais.valor_total_nota = Decimal("999.00")
    issues = NFE.validate(nota)
    assert _codes(issues) == ["totais.invoice_mismatch"]
    assert issues[0].severity is Severity.WARNING


def test_invoice_total_treats_unreadable_components_as_zero(nota: NotaFiscal) -> None:
    assert nota.totais is not None
    nota.totais.valor_seguro = None
    assert NFE.validate(nota) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1.234,56", "1234.56"), ("1234.56", "1234.56"), ("0,5", "0.5"), ("10", "10")],
)
def test_item_accepts_brazilian_number_format(raw: str, expected: str) -> None:
    item = Item.model_validate(
        {
            "codigo": None,
            "descricao": None,
            "ncm": None,
            "cfop": None,
            "unidade": None,
            "quantidade": raw,
            "valor_unitario": None,
            "valor_total": None,
        }
    )
    assert item.quantidade == Decimal(expected)
