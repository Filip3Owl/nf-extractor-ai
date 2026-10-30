"""Output schema for Brazilian invoices.

Field names stay in Portuguese because they mirror the terms printed on the DANFE. Every
field is nullable so the model can report an unreadable value instead of inventing one,
and identifiers are plain strings so that bad values reach the validators, which report
them as issues without discarding the rest of the extraction.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, WithJsonSchema


def _parse_decimal(value: Any) -> Any:
    """Accept Brazilian number formatting, in case the model copies it as printed."""
    if isinstance(value, str) and "," in value:
        return value.replace(".", "").replace(",", ".")
    return value


# Sent to the model as a string because binary floats cannot represent money exactly.
BrDecimal = Annotated[
    Decimal,
    BeforeValidator(_parse_decimal),
    WithJsonSchema({"type": "string", "description": "Decimal number, for example 1234.56"}),
]


class _Schema(BaseModel):
    """Base model that rejects fields not defined in the schema."""

    model_config = ConfigDict(extra="forbid")


class Parte(_Schema):
    """The issuer or the recipient of the invoice."""

    nome: str | None
    documento: str | None = Field(description="CNPJ or CPF, as printed")
    inscricao_estadual: str | None
    municipio: str | None
    uf: str | None = Field(description="Two-letter state code")


class Item(_Schema):
    """One line of the products and services table."""

    codigo: str | None
    descricao: str | None
    ncm: str | None
    cfop: str | None
    unidade: str | None
    quantidade: BrDecimal | None
    valor_unitario: BrDecimal | None
    valor_total: BrDecimal | None


class Totais(_Schema):
    """The invoice totals, as printed in the tax calculation section."""

    base_calculo_icms: BrDecimal | None
    valor_icms: BrDecimal | None
    valor_icms_st: BrDecimal | None
    valor_ipi: BrDecimal | None
    valor_produtos: BrDecimal | None
    valor_frete: BrDecimal | None
    valor_seguro: BrDecimal | None
    valor_desconto: BrDecimal | None
    outras_despesas: BrDecimal | None
    valor_total_nota: BrDecimal | None


class NotaFiscal(_Schema):
    """A Brazilian electronic invoice. Use null for any value that is absent or unreadable."""

    chave_acesso: str | None
    modelo: str | None
    numero: str | None
    serie: str | None
    data_emissao: date | None
    natureza_operacao: str | None
    emitente: Parte | None
    destinatario: Parte | None
    itens: list[Item]
    totais: Totais | None
