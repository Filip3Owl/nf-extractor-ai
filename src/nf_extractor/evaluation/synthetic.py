"""Generate fictional invoices with known values, to serve as ground truth.

No real person or company is involved: names are fictional, identifiers are random, and
all the documents rendered from this data are marked as having no fiscal value.
"""

import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from nf_extractor.document_types.nfe.schema import Item, NotaFiscal, Parte, Totais
from nf_extractor.validators.br_identifiers import (
    with_access_key_check_digit,
    with_cnpj_check_digits,
    with_cpf_check_digits,
)

_CENT = Decimal("0.01")
_COMPANY_WORDS = ("Fictícia", "Exemplo", "Demonstração", "Simulada", "Modelo", "Ensaio")
_COMPANY_TYPES = ("Comércio", "Indústria", "Serviços", "Distribuidora", "Atacado")
_PERSON_NAMES = ("Ana Fictícia", "João Exemplo", "Maria Simulada", "José Modelo", "Lia Ensaio")
_STATES = {
    "SP": ("35", "São Paulo"),
    "RJ": ("33", "Rio de Janeiro"),
    "MG": ("31", "Belo Horizonte"),
    "PR": ("41", "Curitiba"),
    "BA": ("29", "Salvador"),
    "RS": ("43", "Porto Alegre"),
}
_PRODUCTS = (
    "Parafuso sextavado aço",
    "Cabo elétrico flexível",
    "Papel sulfite A4",
    "Café torrado moído",
    "Óleo lubrificante",
    "Caixa de papelão",
    "Tinta acrílica branca",
    "Luva de proteção",
    "Lâmpada LED",
    "Fita adesiva",
)
_UNITS = ("UN", "CX", "KG", "PC", "LT")
_ALPHANUMERIC = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _digits(rng: random.Random, count: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(count))


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def format_cnpj(cnpj: str) -> str:
    """Add the usual punctuation to a CNPJ."""
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"


def format_cpf(cpf: str) -> str:
    """Add the usual punctuation to a CPF."""
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"


def _cnpj(rng: random.Random) -> str:
    # One in five uses the alphanumeric format, which is harder to read.
    if rng.random() < 0.2:
        base = "".join(rng.choice(_ALPHANUMERIC) for _ in range(8)) + "0001"
    else:
        base = _digits(rng, 8) + "0001"
    return with_cnpj_check_digits(base)


def _item(rng: random.Random) -> Item:
    quantity = Decimal(rng.randint(1, 500)).quantize(Decimal("0.0001"))
    unit_price = _money(Decimal(rng.randint(50, 250_000)) / 100)
    return Item(
        codigo=f"P{_digits(rng, 5)}",
        descricao=rng.choice(_PRODUCTS),
        ncm=_digits(rng, 8),
        cfop=rng.choice(("5102", "6102", "5405", "6108")),
        unidade=rng.choice(_UNITS),
        quantidade=quantity,
        valor_unitario=unit_price,
        valor_total=_money(quantity * unit_price),
    )


def _totals(rng: random.Random, products: Decimal) -> Totais:
    freight = _money(products * Decimal(rng.randint(0, 5)) / 100)
    insurance = _money(products * Decimal(rng.randint(0, 1)) / 100)
    discount = _money(products * Decimal(rng.randint(0, 3)) / 100)
    other = _money(Decimal(rng.randint(0, 2000)) / 100)
    ipi = _money(products * Decimal(rng.choice((0, 0, 5))) / 100)
    return Totais(
        base_calculo_icms=products,
        valor_icms=_money(products * Decimal("0.18")),
        valor_icms_st=Decimal("0.00"),
        valor_ipi=ipi,
        valor_produtos=products,
        valor_frete=freight,
        valor_seguro=insurance,
        valor_desconto=discount,
        outras_despesas=other,
        valor_total_nota=products + freight + insurance + other + ipi - discount,
    )


def generate_nota(rng: random.Random) -> NotaFiscal:
    """Generate a fictional invoice that satisfies every validation rule.

    Args:
        rng: The source of randomness. The same seed always gives the same invoice.

    Returns:
        The invoice.
    """
    issued = date(2026, 1, 1) + timedelta(days=rng.randint(0, 300))
    uf, (state_code, city) = rng.choice(list(_STATES.items()))
    recipient_uf, (_, recipient_city) = rng.choice(list(_STATES.items()))
    issuer = _cnpj(rng)
    number = str(rng.randint(1, 999_999_999))
    series = str(rng.randint(1, 9))

    if rng.random() < 0.7:
        recipient_name = f"{rng.choice(_COMPANY_TYPES)} {rng.choice(_COMPANY_WORDS)} S.A."
        recipient_document = format_cnpj(_cnpj(rng))
        recipient_ie: str | None = _digits(rng, 12)
    else:
        recipient_name = rng.choice(_PERSON_NAMES)
        recipient_document = format_cpf(with_cpf_check_digits(_digits(rng, 9)))
        recipient_ie = None

    items = [_item(rng) for _ in range(rng.randint(1, 12))]
    products = sum((item.valor_total for item in items if item.valor_total), Decimal(0))

    key_base = (
        f"{state_code}{issued:%y%m}{issuer}55{series.zfill(3)}{number.zfill(9)}1{_digits(rng, 8)}"
    )
    return NotaFiscal(
        chave_acesso=with_access_key_check_digit(key_base),
        modelo="55",
        numero=number,
        serie=series,
        data_emissao=issued,
        natureza_operacao=rng.choice(("Venda de mercadoria", "Remessa para conserto", "Devolução")),
        emitente=Parte(
            nome=f"{rng.choice(_COMPANY_TYPES)} {rng.choice(_COMPANY_WORDS)} LTDA",
            documento=format_cnpj(issuer),
            inscricao_estadual=_digits(rng, 12),
            municipio=city,
            uf=uf,
        ),
        destinatario=Parte(
            nome=recipient_name,
            documento=recipient_document,
            inscricao_estadual=recipient_ie,
            municipio=recipient_city,
            uf=recipient_uf,
        ),
        itens=items,
        totais=_totals(rng, products),
    )
