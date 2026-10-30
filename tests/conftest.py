from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest

from nf_extractor.document_types.nfe.schema import Item, NotaFiscal, Parte, Totais

# Synthetic data only: these identifiers are test values and belong to no real party.
ISSUER_CNPJ = "11222333000181"
RECIPIENT_CPF = "52998224725"


def build_access_key(
    issuer_id: str = ISSUER_CNPJ,
    year_month: str = "2610",
    model: str = "55",
    series: str = "001",
    number: str = "000000123",
) -> str:
    """Build a key with a correct check digit, independently of the code under test."""
    body = f"35{year_month}{issuer_id}{model}{series}{number}112345678"
    total = sum(
        (ord(character) - 48) * (index % 8 + 2) for index, character in enumerate(reversed(body))
    )
    remainder = total % 11
    return body + str(0 if remainder < 2 else 11 - remainder)


def _nota() -> NotaFiscal:
    """Build an invoice that passes every validation rule."""
    return NotaFiscal(
        chave_acesso=build_access_key(),
        modelo="55",
        numero="123",
        serie="1",
        data_emissao=date(2026, 10, 15),
        natureza_operacao="Venda de mercadoria",
        emitente=Parte(
            nome="Empresa Exemplo LTDA",
            documento="11.222.333/0001-81",
            inscricao_estadual=None,
            municipio="São Paulo",
            uf="SP",
        ),
        destinatario=Parte(
            nome="Pessoa Exemplo",
            documento="529.982.247-25",
            inscricao_estadual=None,
            municipio="Campinas",
            uf="SP",
        ),
        itens=[
            Item(
                codigo="A1",
                descricao="Produto A",
                ncm="12345678",
                cfop="5102",
                unidade="UN",
                quantidade=Decimal("2"),
                valor_unitario=Decimal("50.00"),
                valor_total=Decimal("100.00"),
            ),
            Item(
                codigo="B2",
                descricao="Produto B",
                ncm="12345678",
                cfop="5102",
                unidade="UN",
                quantidade=Decimal("1"),
                valor_unitario=Decimal("25.50"),
                valor_total=Decimal("25.50"),
            ),
        ],
        totais=Totais(
            base_calculo_icms=Decimal("125.50"),
            valor_icms=Decimal("22.59"),
            valor_icms_st=Decimal("0"),
            valor_ipi=Decimal("0"),
            valor_produtos=Decimal("125.50"),
            valor_frete=Decimal("10.00"),
            valor_seguro=Decimal("0"),
            valor_desconto=Decimal("5.50"),
            outras_despesas=Decimal("0"),
            valor_total_nota=Decimal("130.00"),
        ),
    )


@pytest.fixture
def nota() -> NotaFiscal:
    return _nota()


@pytest.fixture
def access_key_factory() -> Callable[..., str]:
    return build_access_key
