"""Render fictional invoices as DANFE-like PDFs.

The layout follows the general structure of a DANFE but is not the official model. Every
page states that the document is synthetic and has no fiscal value.
"""

import io
import random
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from nf_extractor.document_types.nfe.schema import NotaFiscal

DISCLAIMER = "DOCUMENTO SINTÉTICO - SEM VALOR FISCAL"

_FONTS = (
    ("Helvetica", "Helvetica-Bold"),
    ("Times-Roman", "Times-Bold"),
    ("Courier", "Courier-Bold"),
)
_MARGIN = 24.0
_LABEL_SIZE = 6.0
_VALUE_SIZE = 9.0
_ROW_HEIGHT = 27.0


def format_decimal(value: Decimal | None, places: int = 2) -> str:
    """Format a number as printed in Brazil, such as ``1.234,56``."""
    if value is None:
        return ""
    return f"{value:,.{places}f}".replace(",", "#").replace(".", ",").replace("#", ".")


def format_grouped_key(key: str) -> str:
    """Split an access key into the groups of four printed on a DANFE."""
    return " ".join(key[index : index + 4] for index in range(0, len(key), 4))


class _Sheet:
    def __init__(self, canvas: Canvas, regular: str, bold: str) -> None:
        self.canvas = canvas
        self.regular = regular
        self.bold = bold
        self.width = A4[0] - 2 * _MARGIN

    def text(self, x: float, y: float, value: str, size: float, bold: bool = False) -> None:
        self.canvas.setFont(self.bold if bold else self.regular, size)
        self.canvas.drawString(x, y, value)

    def row(self, top: float, cells: list[tuple[str, str, float]]) -> float:
        """Draw boxes with a label and a value, and return the top of the next row."""
        x = _MARGIN
        bottom = top - _ROW_HEIGHT
        for label, value, share in cells:
            width = self.width * share
            self.canvas.rect(x, bottom, width, _ROW_HEIGHT)
            self.text(x + 3, top - 8, label, _LABEL_SIZE)
            self.text(x + 3, bottom + 5, value, _VALUE_SIZE)
            x += width
        return bottom

    def section(self, top: float, title: str) -> float:
        self.text(_MARGIN, top - 11, title, 7, bold=True)
        return top - 14


def render_danfe(nota: NotaFiscal, rng: random.Random) -> bytes:
    """Render an invoice as a one-page PDF.

    Args:
        nota: The invoice. It must have an issuer and totals.
        rng: Chooses the visual variation, such as the font.

    Returns:
        The PDF content.
    """
    if nota.emitente is None or nota.destinatario is None or nota.totais is None:
        raise ValueError("Rendering requires an issuer, a recipient and totals.")

    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=A4, invariant=True)
    canvas.setTitle(DISCLAIMER)
    regular, bold = rng.choice(_FONTS)
    sheet = _Sheet(canvas, regular, bold)
    page_top = A4[1] - _MARGIN

    sheet.text(_MARGIN, page_top - 8, DISCLAIMER, 10, bold=True)

    top = page_top - 16
    header_height = 80.0
    canvas.rect(_MARGIN, top - header_height, sheet.width, header_height)
    issuer = nota.emitente
    sheet.text(_MARGIN + 4, top - 22, issuer.nome or "", 10, bold=True)
    sheet.text(_MARGIN + 4, top - 40, f"{issuer.municipio} - {issuer.uf}", 9)

    center = _MARGIN + sheet.width * 0.5
    sheet.text(center, top - 14, "DANFE", 12, bold=True)
    number = (nota.numero or "").zfill(9)
    sheet.text(center, top - 30, f"Nº {number[:3]}.{number[3:6]}.{number[6:]}", 9)
    sheet.text(center, top - 44, f"SÉRIE {(nota.serie or '').zfill(3)}", 9)
    sheet.text(center, top - 60, "CHAVE DE ACESSO", _LABEL_SIZE)
    sheet.text(center, top - 72, format_grouped_key(nota.chave_acesso or ""), 7)

    top = sheet.row(
        top - header_height, [("NATUREZA DA OPERAÇÃO", nota.natureza_operacao or "", 1.0)]
    )
    top = sheet.row(
        top,
        [
            ("INSCRIÇÃO ESTADUAL", issuer.inscricao_estadual or "", 0.5),
            ("CNPJ", issuer.documento or "", 0.5),
        ],
    )

    recipient = nota.destinatario
    top = sheet.section(top, "DESTINATÁRIO / REMETENTE")
    issued = f"{nota.data_emissao:%d/%m/%Y}" if nota.data_emissao else ""
    top = sheet.row(
        top,
        [
            ("NOME / RAZÃO SOCIAL", recipient.nome or "", 0.5),
            ("CNPJ / CPF", recipient.documento or "", 0.3),
            ("DATA DA EMISSÃO", issued, 0.2),
        ],
    )
    top = sheet.row(
        top,
        [
            ("MUNICÍPIO", recipient.municipio or "", 0.5),
            ("UF", recipient.uf or "", 0.1),
            ("INSCRIÇÃO ESTADUAL", recipient.inscricao_estadual or "", 0.4),
        ],
    )

    totals = nota.totais
    top = sheet.section(top, "CÁLCULO DO IMPOSTO")
    top = sheet.row(
        top,
        [
            ("BASE DE CÁLCULO DO ICMS", format_decimal(totals.base_calculo_icms), 0.25),
            ("VALOR DO ICMS", format_decimal(totals.valor_icms), 0.25),
            ("VALOR DO ICMS ST", format_decimal(totals.valor_icms_st), 0.25),
            ("VALOR TOTAL DOS PRODUTOS", format_decimal(totals.valor_produtos), 0.25),
        ],
    )
    top = sheet.row(
        top,
        [
            ("VALOR DO FRETE", format_decimal(totals.valor_frete), 1 / 6),
            ("VALOR DO SEGURO", format_decimal(totals.valor_seguro), 1 / 6),
            ("DESCONTO", format_decimal(totals.valor_desconto), 1 / 6),
            ("OUTRAS DESPESAS", format_decimal(totals.outras_despesas), 1 / 6),
            ("VALOR DO IPI", format_decimal(totals.valor_ipi), 1 / 6),
            ("VALOR TOTAL DA NOTA", format_decimal(totals.valor_total_nota), 1 / 6),
        ],
    )

    top = sheet.section(top, "DADOS DOS PRODUTOS / SERVIÇOS")
    columns = (
        ("CÓDIGO", 0.0),
        ("DESCRIÇÃO", 0.1),
        ("NCM", 0.42),
        ("CFOP", 0.51),
        ("UN", 0.58),
        ("QTD", 0.63),
        ("V. UNIT", 0.75),
        ("V. TOTAL", 0.87),
    )
    for label, offset in columns:
        sheet.text(_MARGIN + 3 + sheet.width * offset, top - 8, label, _LABEL_SIZE, bold=True)
    canvas.line(_MARGIN, top - 11, _MARGIN + sheet.width, top - 11)
    top -= 11
    for item in nota.itens:
        top -= 15
        values = (
            item.codigo or "",
            item.descricao or "",
            item.ncm or "",
            item.cfop or "",
            item.unidade or "",
            format_decimal(item.quantidade, 4),
            format_decimal(item.valor_unitario),
            format_decimal(item.valor_total),
        )
        for value, (_, offset) in zip(values, columns, strict=True):
            sheet.text(_MARGIN + 3 + sheet.width * offset, top + 3, value, 8)

    sheet.text(_MARGIN, _MARGIN, DISCLAIMER, 10, bold=True)
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()
