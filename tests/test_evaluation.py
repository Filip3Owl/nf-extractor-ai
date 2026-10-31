import random
from decimal import Decimal
from pathlib import Path

import numpy as np
import pypdfium2
import pytest
from pydantic import BaseModel

from nf_extractor.core.document import Document, MediaType
from nf_extractor.core.result import Extraction, TokenUsage
from nf_extractor.document_types.nfe import NFE, NotaFiscal
from nf_extractor.errors import ExtractionError
from nf_extractor.evaluation.dataset import TRUTH_FILE, generate_dataset, iter_cases
from nf_extractor.evaluation.degradations import DEGRADATIONS
from nf_extractor.evaluation.harness import evaluate
from nf_extractor.evaluation.metrics import DocumentScore, compare, flatten, summarize
from nf_extractor.evaluation.renderer import (
    DISCLAIMER,
    format_decimal,
    format_grouped_key,
    render_danfe,
)
from nf_extractor.evaluation.synthetic import generate_nota
from nf_extractor.extractors.preprocessing import deskew, estimate_skew, rasterize


@pytest.mark.parametrize("seed", range(25))
def test_synthetic_invoice_satisfies_every_rule(seed: int) -> None:
    assert NFE.validate(generate_nota(random.Random(seed))) == []


def test_synthetic_generation_is_reproducible() -> None:
    assert generate_nota(random.Random(1)) == generate_nota(random.Random(1))
    assert generate_nota(random.Random(1)) != generate_nota(random.Random(2))


def test_format_decimal() -> None:
    assert format_decimal(Decimal("1234567.5")) == "1.234.567,50"
    assert format_decimal(Decimal("2"), 4) == "2,0000"
    assert format_decimal(None) == ""


def test_format_grouped_key() -> None:
    assert format_grouped_key("12345678") == "1234 5678"


def test_rendered_page_is_marked_as_synthetic() -> None:
    pdf = pypdfium2.PdfDocument(render_danfe(generate_nota(random.Random(1)), random.Random(1)))
    text = pdf[0].get_textpage().get_text_bounded()
    assert text.count(DISCLAIMER) == 2
    assert pdf.get_metadata_value("Title") == DISCLAIMER


def test_render_requires_complete_invoice(nota: NotaFiscal) -> None:
    nota.totais = None
    with pytest.raises(ValueError, match="requires"):
        render_danfe(nota, random.Random(1))


@pytest.fixture
def page() -> np.ndarray:
    pdf = render_danfe(generate_nota(random.Random(3)), random.Random(3))
    return rasterize(Document("page.pdf", MediaType.PDF, pdf), dpi=100)[0]


@pytest.mark.parametrize("name", sorted(DEGRADATIONS))
def test_degradations_change_the_image(name: str, page: np.ndarray) -> None:
    result = DEGRADATIONS[name](page, np.random.default_rng(1))
    assert result.dtype == np.uint8
    assert result.ndim == 3
    assert result.shape != page.shape or not np.array_equal(result, page)


def test_deskew_corrects_rotation(page: np.ndarray) -> None:
    rotated = DEGRADATIONS["rotated"](page, np.random.default_rng(1))
    assert abs(estimate_skew(rotated)) > 0.9
    assert abs(estimate_skew(deskew(rotated))) < 0.5


def test_deskew_keeps_straight_page(page: np.ndarray) -> None:
    assert deskew(page) is page


def test_estimate_skew_on_blank_page() -> None:
    assert estimate_skew(np.full((200, 200, 3), 255, np.uint8)) == 0.0


def test_rasterize_corrupted_files() -> None:
    from nf_extractor.errors import UnsupportedDocumentError

    with pytest.raises(UnsupportedDocumentError):
        rasterize(Document("bad.pdf", MediaType.PDF, b"%PDF-broken"))
    with pytest.raises(UnsupportedDocumentError):
        rasterize(Document("bad.jpg", MediaType.JPEG, b"\xff\xd8\xffbroken"))


def test_flatten_includes_nested_values_and_list_sizes(nota: NotaFiscal) -> None:
    flat = flatten(nota)
    assert flat["emitente.uf"] == "SP"
    assert flat["itens.count"] == 2
    assert flat["itens[1].cfop"] == "5102"


def test_compare_ignores_formatting_differences(nota: NotaFiscal) -> None:
    other = nota.model_copy(deep=True)
    assert other.emitente is not None
    assert other.emitente.documento is not None
    other.emitente.documento = other.emitente.documento.replace(".", "")
    other.emitente.municipio = "SAO PAULO"
    assert other.totais is not None
    other.totais.valor_frete = Decimal("10")
    assert all(compare(nota, other).values())


def test_compare_detects_wrong_and_missing_values(nota: NotaFiscal) -> None:
    other = nota.model_copy(deep=True)
    other.numero = "999"
    other.itens.pop()
    result = compare(nota, other)
    assert not result["numero"]
    assert not result["itens.count"]
    assert not result["itens[1].cfop"]
    assert result["itens[0].cfop"]


def test_compare_with_failed_extraction(nota: NotaFiscal) -> None:
    assert not any(compare(nota, None).values())


def _score(variant: str, correct: bool, flagged: bool, failed: bool = False) -> DocumentScore:
    return DocumentScore(
        case_id="c",
        variant=variant,
        fields={"a": correct, "itens[0].b": True},
        flagged=flagged,
        failed=failed,
        seconds=2.0,
        input_tokens=1,
        output_tokens=2,
    )


def test_summarize_computes_rates() -> None:
    report = summarize(
        "x",
        [
            _score("clean", True, False),
            _score("clean", True, True),
            _score("clean", False, True),
            _score("clean", False, False),
            _score("noisy", False, False, failed=True),
        ],
    )
    clean, noisy = report.variants
    assert clean.documents == 4
    assert clean.field_accuracy == pytest.approx(6 / 8)
    assert clean.perfect_documents == pytest.approx(0.5)
    assert clean.error_detection_rate == pytest.approx(0.5)
    assert clean.false_alarm_rate == pytest.approx(0.5)
    assert noisy.failures == 1
    assert noisy.error_detection_rate is None
    assert noisy.false_alarm_rate is None
    assert report.field_accuracy["itens[].b"] == 1.0
    assert report.input_tokens == 5
    assert report.output_tokens == 10


def test_report_markdown() -> None:
    markdown = summarize("ocr", [_score("clean", True, False)]).to_markdown()
    assert "`ocr`" in markdown
    assert "| clean | 1 | 0 | 100.0% | 100.0% | 2.0 s | n/a | 0.0% |" in markdown
    assert "| `itens[].b` | 100.0% |" in markdown


class TruthExtractor:
    """Returns the known answer for most documents, so that the harness can be checked."""

    def __init__(self, truth_by_name: dict[str, NotaFiscal]) -> None:
        self.truth_by_name = truth_by_name

    def extract[T: BaseModel](
        self, document: Document, schema: type[T], instructions: str
    ) -> Extraction[T]:
        if document.name.startswith("noisy"):
            raise ExtractionError("unreadable")
        data = self.truth_by_name["any"].model_dump()
        if document.name.startswith("blurred"):
            data["chave_acesso"] = "123"
        return Extraction(
            data=schema.model_validate(data),
            model="truth",
            usage=TokenUsage(input_tokens=1, output_tokens=1),
        )


def test_dataset_and_harness_end_to_end(tmp_path: Path) -> None:
    generate_dataset(tmp_path, count=1, seed=5)
    folder = tmp_path / "case_0001"
    expected_files = {TRUTH_FILE, "clean.pdf"} | {f"{name}.jpg" for name in DEGRADATIONS}
    assert {path.name for path in folder.iterdir()} == expected_files

    cases = list(iter_cases(tmp_path))
    assert len(cases) == 1 + len(DEGRADATIONS)
    assert {case.variant for case in cases} == {"clean", *DEGRADATIONS}

    seen = []
    report = evaluate(
        tmp_path,
        TruthExtractor({"any": cases[0].truth}),
        "truth",
        NFE,
        on_progress=lambda score: seen.append(score.variant),
    )
    assert len(seen) == len(cases)
    by_name = {item.variant: item for item in report.variants}
    assert by_name["clean"].perfect_documents == 1.0
    assert by_name["clean"].false_alarm_rate == 0.0
    assert by_name["noisy"].failures == 1
    assert by_name["noisy"].field_accuracy == 0.0
    assert by_name["blurred"].perfect_documents == 0.0
    assert by_name["blurred"].error_detection_rate == 1.0


def test_dataset_generation_is_reproducible(tmp_path: Path) -> None:
    generate_dataset(tmp_path / "a", count=1, seed=9)
    generate_dataset(tmp_path / "b", count=1, seed=9)
    for name in ("truth.json", "clean.pdf", "photo.jpg"):
        first = (tmp_path / "a" / "case_0001" / name).read_bytes()
        assert first == (tmp_path / "b" / "case_0001" / name).read_bytes()
