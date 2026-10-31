"""Turn OCR lines from a DANFE into a :class:`NotaFiscal`, using the printed field labels.

In a DANFE, each value sits in a box below its label, so labels work as anchors. OCR may
join neighboring boxes into one line, so each line is split into tokens with approximate
positions, and each token is assigned to the box that contains it.

Values are read only from where they are printed. Nothing is derived from the access key,
because the validators compare the two to detect misreadings.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from nf_extractor.core.ocr import OcrLine
from nf_extractor.document_types.nfe.schema import Item, NotaFiscal, Parte, Totais
from nf_extractor.validators.br_identifiers import normalize_identifier

_SECTION_RECIPIENT = "DESTINATARIO"
_SECTION_TOTALS = "CALCULO DO IMPOSTO"
_SECTION_ITEMS = "DADOS DOS PRODUTOS"
_SECTION_END = ("DADOS ADICIONAIS", "DOCUMENTO SINTETICO")

_FIELD_LABELS = (
    "CHAVE DE ACESSO",
    "NATUREZA DA OPERACAO",
    "INSCRICAO ESTADUAL",
    "NOME / RAZAO SOCIAL",
    "CNPJ / CPF",
    "CNPJ",
    "DATA DA EMISSAO",
    "MUNICIPIO",
    "UF",
    "BASE DE CALCULO DO ICMS",
    "VALOR DO ICMS ST",
    "VALOR DO ICMS",
    "VALOR TOTAL DOS PRODUTOS",
    "VALOR DO FRETE",
    "VALOR DO SEGURO",
    "DESCONTO",
    "OUTRAS DESPESAS",
    "VALOR DO IPI",
    "VALOR TOTAL DA NOTA",
)
_ITEM_COLUMNS = {
    "CODIGO": "codigo",
    "DESCRICAO": "descricao",
    "NCM": "ncm",
    "CFOP": "cfop",
    "UN": "unidade",
    "QTD": "quantidade",
    "V. UNIT": "valor_unitario",
    "V. TOTAL": "valor_total",
}


def normalize_text(text: str) -> str:
    """Convert text to upper case, without accents or repeated whitespace."""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(plain.upper().split())


@dataclass(frozen=True)
class _Box:
    """A piece of text with its position."""

    text: str
    left: float
    top: float
    right: float
    bottom: float

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def height(self) -> float:
        return self.bottom - self.top


def _slice(line: OcrLine, text: str, start: int, end: int) -> _Box:
    """Estimate the position of part of a line's text, assuming evenly spaced characters."""
    character_width = (line.right - line.left) / max(len(text), 1)
    return _Box(
        text=text[start:end],
        left=line.left + start * character_width,
        top=line.top,
        right=line.left + end * character_width,
        bottom=line.bottom,
    )


def _tokens(line: OcrLine) -> list[_Box]:
    return [_slice(line, line.text, m.start(), m.end()) for m in re.finditer(r"\S+", line.text)]


def _find_labels(lines: list[OcrLine], labels: tuple[str, ...]) -> list[_Box]:
    """Locate labels, matching longer ones first so "CNPJ" does not match "CNPJ / CPF"."""
    found: list[_Box] = []
    for line in lines:
        normalized = normalize_text(line.text)
        remaining = normalized
        for label in sorted(labels, key=len, reverse=True):
            pattern = rf"(?<![A-Z]){re.escape(label)}(?![A-Z])"
            for match in re.finditer(pattern, remaining):
                box = _slice(line, normalized, match.start(), match.end())
                found.append(_Box(label, box.left, box.top, box.right, box.bottom))
                remaining = (
                    remaining[: match.start()]
                    + "#" * (match.end() - match.start())
                    + remaining[match.end() :]
                )
    return found


def _first_y(lines: list[OcrLine], marker: str) -> float | None:
    positions = [line.top for line in lines if marker in normalize_text(line.text)]
    return min(positions) if positions else None


class _Page:
    """Answers "what is printed in the box under this label?"."""

    def __init__(self, lines: list[OcrLine], width: float) -> None:
        self.lines = lines
        self.width = width
        self.labels = _find_labels(lines, _FIELD_LABELS)
        self.tokens = [token for line in lines for token in _tokens(line)]

    def value(self, label: str, y_min: float = 0, y_max: float = float("inf")) -> str | None:
        """Read the value under the first occurrence of a label within a vertical range."""
        matches = [
            box for box in self.labels if box.text == label and y_min <= box.center_y < y_max
        ]
        if not matches:
            return None
        anchor = min(matches, key=lambda box: box.center_y)

        # A box ends where the next label on the same row begins.
        neighbors = [
            box.left
            for box in self.labels
            if abs(box.center_y - anchor.center_y) < anchor.height and box.left > anchor.left + 1
        ]
        right = min(neighbors, default=self.width)
        margin = anchor.height

        inside = [
            token
            for token in self.tokens
            if anchor.left - margin <= token.center_x < right - margin / 2
            and anchor.bottom - anchor.height / 3 <= token.center_y <= anchor.bottom + 4 * margin
            and not self._is_label_text(token)
        ]
        if not inside:
            return None
        first_row = min(token.center_y for token in inside)
        row = [token for token in inside if abs(token.center_y - first_row) < margin * 0.8]
        return " ".join(token.text for token in sorted(row, key=lambda token: token.left))

    def _is_label_text(self, token: _Box) -> bool:
        """Tell whether a token overlaps a label, so that it is not read as a value."""
        return any(
            box.left - 1 <= token.center_x <= box.right + 1
            and abs(box.center_y - token.center_y) < box.height / 2
            for box in self.labels
        )


def _parse_decimal(text: str | None) -> Decimal | None:
    """Parse "1.234,56", tolerating stray characters and a misread decimal separator."""
    if not text:
        return None
    cleaned = re.sub(r"[^0-9.,]", "", text)
    match = re.fullmatch(r"([0-9.,]*?)[.,]([0-9]{1,4})", cleaned)
    if match:
        cleaned = re.sub(r"[.,]", "", match.group(1)) + "." + match.group(2)
    else:
        cleaned = re.sub(r"[.,]", "", cleaned)
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_date(text: str | None) -> date | None:
    match = re.search(r"([0-9]{2})\s*/\s*([0-9]{2})\s*/\s*([0-9]{4})", text or "")
    if not match:
        return None
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def _parse_header_number(lines: list[OcrLine], pattern: str) -> str | None:
    for line in lines:
        match = re.search(pattern, normalize_text(line.text))
        if match:
            digits = re.sub(r"[^0-9]", "", match.group(1)).lstrip("0")
            return digits or "0"
    return None


def _parse_issuer(page: _Page, y_max: float) -> Parte:
    block = [
        line
        for line in page.lines
        if line.top < y_max
        and line.right < page.width * 0.45
        and "DOCUMENTO SINTETICO" not in normalize_text(line.text)
        and not _find_labels([line], _FIELD_LABELS)
    ]
    block.sort(key=lambda line: line.top)
    city = next(
        (
            match
            for line in block
            if (match := re.fullmatch(r"(.+?)\s*-\s*([A-Z]{2})", line.text.strip()))
        ),
        None,
    )
    return Parte(
        nome=block[0].text.strip() if block else None,
        documento=page.value("CNPJ", y_max=y_max),
        inscricao_estadual=page.value("INSCRICAO ESTADUAL", y_max=y_max),
        municipio=city.group(1) if city else None,
        uf=city.group(2) if city else None,
    )


def _parse_recipient(page: _Page, y_min: float, y_max: float) -> Parte | None:
    if y_min == float("inf"):
        return None
    return Parte(
        nome=page.value("NOME / RAZAO SOCIAL", y_min, y_max),
        documento=page.value("CNPJ / CPF", y_min, y_max),
        inscricao_estadual=page.value("INSCRICAO ESTADUAL", y_min, y_max),
        municipio=page.value("MUNICIPIO", y_min, y_max),
        uf=page.value("UF", y_min, y_max),
    )


def _parse_totals(page: _Page, y_min: float, y_max: float) -> Totais | None:
    if y_min == float("inf"):
        return None

    def read(label: str) -> Decimal | None:
        return _parse_decimal(page.value(label, y_min, y_max))

    return Totais(
        base_calculo_icms=read("BASE DE CALCULO DO ICMS"),
        valor_icms=read("VALOR DO ICMS"),
        valor_icms_st=read("VALOR DO ICMS ST"),
        valor_ipi=read("VALOR DO IPI"),
        valor_produtos=read("VALOR TOTAL DOS PRODUTOS"),
        valor_frete=read("VALOR DO FRETE"),
        valor_seguro=read("VALOR DO SEGURO"),
        valor_desconto=read("DESCONTO"),
        outras_despesas=read("OUTRAS DESPESAS"),
        valor_total_nota=read("VALOR TOTAL DA NOTA"),
    )


def _recover_unit_header(section: list[OcrLine], headers: list[_Box]) -> list[_Box]:
    """Find the "UN" column by position, since OCR often misreads such a short label."""
    by_name = {box.text: box for box in headers}
    if "UN" in by_name or "CFOP" not in by_name or "QTD" not in by_name:
        return headers
    before, after = by_name["CFOP"], by_name["QTD"]
    for line in section:
        for token in _tokens(line):
            if (
                before.right < token.center_x < after.left
                and abs(token.center_y - before.center_y) < before.height
            ):
                unit = _Box("UN", token.left, token.top, token.right, token.bottom)
                return sorted([*headers, unit], key=lambda box: box.left)
    return headers


def _parse_items(page: _Page, y_min: float) -> list[Item]:
    section = [line for line in page.lines if line.top >= y_min]
    headers = [
        box for box in _find_labels(section, tuple(_ITEM_COLUMNS)) if box.text in _ITEM_COLUMNS
    ]
    if not headers:
        return []
    # Only the first row is the header: a cell in the table can also contain the text "UN".
    first_header = min(headers, key=lambda box: box.center_y)
    headers = [
        box for box in headers if abs(box.center_y - first_header.center_y) < first_header.height
    ]
    headers.sort(key=lambda box: box.left)
    headers = _recover_unit_header(section, headers)
    table_top = max(box.bottom for box in headers)

    ends = [y for marker in _SECTION_END if (y := _first_y(section, marker)) is not None]
    table_bottom = min(ends, default=float("inf"))

    tokens = [
        token
        for line in section
        if table_top <= (line.top + line.bottom) / 2 < table_bottom
        for token in _tokens(line)
    ]
    tokens.sort(key=lambda token: token.center_y)

    rows: list[list[_Box]] = []
    for token in tokens:
        if rows and abs(token.center_y - rows[-1][0].center_y) < token.height * 0.6:
            rows[-1].append(token)
        else:
            rows.append([token])

    # Columns are split halfway between header positions, since values may be right-aligned.
    starts = [box.left for box in headers]
    items = []
    for row in rows:
        cells: dict[str, list[str]] = {}
        for token in sorted(row, key=lambda token: token.left):
            index = max(
                (position for position, start in enumerate(starts) if token.center_x >= start),
                default=0,
            )
            cells.setdefault(_ITEM_COLUMNS[headers[index].text], []).append(token.text)

        def text(column: str, cells: dict[str, list[str]] = cells) -> str | None:
            return " ".join(cells[column]) if column in cells else None

        items.append(
            Item(
                codigo=text("codigo"),
                descricao=text("descricao"),
                ncm=text("ncm"),
                cfop=text("cfop"),
                unidade=text("unidade"),
                quantidade=_parse_decimal(text("quantidade")),
                valor_unitario=_parse_decimal(text("valor_unitario")),
                valor_total=_parse_decimal(text("valor_total")),
            )
        )
    return items


def parse_danfe(lines: list[OcrLine], width: float) -> NotaFiscal:
    """Interpret the OCR output of a DANFE.

    Args:
        lines: The recognized lines, across all pages.
        width: The page width, in pixels.

    Returns:
        The invoice. Values that could not be located are ``None``.
    """
    page = _Page(lines, width)
    infinity = float("inf")
    recipient_y = _first_y(lines, _SECTION_RECIPIENT) or infinity
    totals_y = _first_y(lines, _SECTION_TOTALS) or infinity
    items_y = _first_y(lines, _SECTION_ITEMS) or infinity

    key = page.value("CHAVE DE ACESSO", y_max=recipient_y)
    is_danfe = any("DANFE" in normalize_text(line.text) for line in lines)
    return NotaFiscal(
        chave_acesso=normalize_identifier(key) or None if key else None,
        modelo="55" if is_danfe else None,
        numero=_parse_header_number(lines, r"N[O0º°.]*\s*[:.]?\s*([0-9][0-9. ]{2,})"),
        serie=_parse_header_number(lines, r"SERIE\s*[:.]?\s*([0-9]+)"),
        data_emissao=_parse_date(page.value("DATA DA EMISSAO", recipient_y, totals_y)),
        natureza_operacao=page.value("NATUREZA DA OPERACAO", y_max=recipient_y),
        emitente=_parse_issuer(page, recipient_y),
        destinatario=_parse_recipient(page, recipient_y, totals_y),
        itens=_parse_items(page, items_y) if items_y != infinity else [],
        totais=_parse_totals(page, totals_y, items_y),
    )
