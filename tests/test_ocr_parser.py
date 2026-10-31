from datetime import date
from decimal import Decimal

import pytest

from nf_extractor.core.ocr import OcrLine
from nf_extractor.document_types.nfe.ocr_parser import (
    _parse_date,
    _parse_decimal,
    normalize_text,
    parse_danfe,
)

WIDTH = 1654.0
KEY = "3526 1011 2223 3300 0181 5500 1000 0001 2311 2345 6783"


def _line(text: str, left: float, top: float) -> OcrLine:
    return OcrLine(text, left, top, left + len(text) * 12, top + 24)


def _page(unit_header: str = "UN") -> list[OcrLine]:
    return [
        _line("DOCUMENTO SINTÉTICO - SEM VALOR FISCAL", 60, 60),
        _line("DANFE", 820, 120),
        _line("Serviços Ensaio LTDA", 70, 150),
        _line("N° 000.000.123", 820, 170),
        _line("Rio de Janeiro - RJ", 70, 200),
        _line("SÉRIE 001", 820, 210),
        _line("CHAVE DE ACESSO", 820, 260),
        _line(KEY, 820, 295),
        _line("NATUREZA DA OPERAÇÃO", 70, 340),
        _line("Venda de mercadoria", 70, 377),
        _line("INSCRIÇÃO ESTADUAL", 70, 414),
        _line("CNPJ", 830, 414),
        _line("597971147104", 70, 450),
        _line("11.222.333/0001-81", 830, 450),
        _line("DESTINATÁRIO / REMETENTE", 60, 495),
        _line("NOME / RAZÃO SOCIAL", 70, 530),
        _line("CNPJ / CPF", 830, 530),
        _line("DATA DA EMISSÃO", 1290, 530),
        _line("Pessoa Exemplo", 70, 562),
        _line("529.982.247-25", 830, 562),
        _line("15/10/2026", 1290, 562),
        _line("MUNICÍPIO", 70, 602),
        _line("UF", 830, 602),
        _line("INSCRIÇÃO ESTADUAL", 985, 602),
        _line("Curitiba", 70, 637),
        _line("PR", 830, 637),
        _line("CÁLCULO DO IMPOSTO", 60, 684),
        # OCR joined these two neighboring boxes into a single line.
        _line("VALOR DO FRETE    VALOR DO SEGURO", 70, 790),
        _line("10,00             5,50", 70, 825),
        _line("VALOR TOTAL DA NOTA", 1340, 790),
        _line("1.130,00", 1340, 825),
        _line("DADOS DOS PRODUTOS / SERVIÇOS", 60, 876),
        _line("CÓDIGO", 70, 905),
        _line("DESCRIÇÃO", 220, 905),
        _line("NCM", 708, 905),
        _line("CFOP", 845, 905),
        _line(unit_header, 950, 905),
        _line("QTD", 1027, 905),
        _line("V. UNIT", 1210, 905),
        _line("V. TOTAL", 1390, 905),
        _line("P1", 70, 945),
        _line("Fita adesiva", 220, 945),
        _line("09378657", 708, 945),
        _line("6108", 845, 945),
        _line("KG", 950, 945),
        _line("2,0000", 1027, 945),
        _line("50,00", 1210, 945),
        _line("100,00", 1390, 945),
        _line("DOCUMENTO SINTÉTICO - SEM VALOR FISCAL", 60, 2260),
    ]


def test_header_fields() -> None:
    nota = parse_danfe(_page(), WIDTH)
    assert nota.chave_acesso == KEY.replace(" ", "")
    assert nota.modelo == "55"
    assert nota.numero == "123"
    assert nota.serie == "1"
    assert nota.natureza_operacao == "Venda de mercadoria"


def test_issuer_is_separated_from_recipient() -> None:
    nota = parse_danfe(_page(), WIDTH)
    assert nota.emitente is not None
    assert nota.emitente.nome == "Serviços Ensaio LTDA"
    assert nota.emitente.documento == "11.222.333/0001-81"
    assert nota.emitente.inscricao_estadual == "597971147104"
    assert nota.emitente.municipio == "Rio de Janeiro"
    assert nota.emitente.uf == "RJ"


def test_recipient() -> None:
    nota = parse_danfe(_page(), WIDTH)
    assert nota.destinatario is not None
    assert nota.destinatario.nome == "Pessoa Exemplo"
    assert nota.destinatario.documento == "529.982.247-25"
    assert nota.destinatario.municipio == "Curitiba"
    assert nota.destinatario.uf == "PR"
    assert nota.data_emissao == date(2026, 10, 15)


def test_empty_box_is_none_rather_than_a_neighboring_value() -> None:
    nota = parse_danfe(_page(), WIDTH)
    assert nota.destinatario is not None
    assert nota.destinatario.inscricao_estadual is None


def test_values_in_merged_lines_go_to_the_right_box() -> None:
    nota = parse_danfe(_page(), WIDTH)
    assert nota.totais is not None
    assert nota.totais.valor_frete == Decimal("10.00")
    assert nota.totais.valor_seguro == Decimal("5.50")
    assert nota.totais.valor_total_nota == Decimal("1130.00")


def test_unread_total_is_none() -> None:
    nota = parse_danfe(_page(), WIDTH)
    assert nota.totais is not None
    assert nota.totais.valor_produtos is None


def test_items() -> None:
    nota = parse_danfe(_page(), WIDTH)
    assert len(nota.itens) == 1
    item = nota.itens[0]
    assert item.codigo == "P1"
    assert item.descricao == "Fita adesiva"
    assert item.ncm == "09378657"
    assert item.cfop == "6108"
    assert item.unidade == "KG"
    assert item.quantidade == Decimal("2.0000")
    assert item.valor_unitario == Decimal("50.00")
    assert item.valor_total == Decimal("100.00")


def test_misread_unit_header_is_recovered_by_position() -> None:
    nota = parse_danfe(_page(unit_header="NO"), WIDTH)
    assert nota.itens[0].cfop == "6108"
    assert nota.itens[0].unidade == "KG"


def test_cell_with_header_text_is_not_mistaken_for_the_header() -> None:
    lines = [_line("UN", 950, 945) if line.text == "KG" else line for line in _page()]
    nota = parse_danfe(lines, WIDTH)
    assert len(nota.itens) == 1
    assert nota.itens[0].codigo == "P1"
    assert nota.itens[0].unidade == "UN"


def test_missing_sections_produce_empty_values() -> None:
    nota = parse_danfe([_line("texto qualquer", 10, 10)], WIDTH)
    assert nota.chave_acesso is None
    assert nota.modelo is None
    assert nota.destinatario is None
    assert nota.totais is None
    assert nota.itens == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.234,56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),
        ("R$ 10,00", Decimal("10.00")),
        ("298,0000", Decimal("298.0000")),
        ("15", Decimal("15")),
        ("sem numero", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_decimal(text: str | None, expected: Decimal | None) -> None:
    assert _parse_decimal(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("15/10/2026", date(2026, 10, 15)),
        ("15 / 10 / 2026", date(2026, 10, 15)),
        ("31/02/2026", None),
        ("sem data", None),
        (None, None),
    ],
)
def test_parse_date(text: str | None, expected: date | None) -> None:
    assert _parse_date(text) == expected


def test_normalize_text() -> None:
    assert normalize_text("  Razão   Social ") == "RAZAO SOCIAL"
