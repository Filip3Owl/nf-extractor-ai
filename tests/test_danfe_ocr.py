import random
import re
from pathlib import Path

import cv2
import numpy as np
import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

from nf_extractor import cli
from nf_extractor.config import Settings
from nf_extractor.core.document import Document, MediaType
from nf_extractor.core.ocr import OcrLine
from nf_extractor.document_types.nfe import NFE, NotaFiscal
from nf_extractor.errors import ExtractionError
from nf_extractor.evaluation.metrics import compare
from nf_extractor.evaluation.renderer import render_danfe
from nf_extractor.evaluation.synthetic import generate_nota
from nf_extractor.extractors.danfe_ocr import DanfeOcrExtractor
from nf_extractor.extractors.rapidocr_engine import RapidOcrEngine

runner = CliRunner()


class StubEngine:
    name = "stub-ocr"

    def __init__(self, lines: list[OcrLine]) -> None:
        self.lines = lines
        self.pages = 0

    def recognize(self, image: object) -> list[OcrLine]:
        self.pages += 1
        return self.lines


def _png() -> Document:
    _, encoded = cv2.imencode(".png", np.full((100, 100, 3), 255, np.uint8))
    return Document("page.png", MediaType.PNG, encoded.tobytes())


def test_extractor_reports_engine_and_zero_tokens() -> None:
    engine = StubEngine([OcrLine("DANFE", 10, 10, 90, 30)])
    extraction = DanfeOcrExtractor(engine).extract(_png(), NotaFiscal, "ignored")
    assert engine.pages == 1
    assert extraction.data.modelo == "55"
    assert extraction.model == "stub-ocr"
    assert extraction.usage.input_tokens == 0
    assert extraction.usage.output_tokens == 0


def test_extractor_stacks_pages_vertically() -> None:
    pdf = render_danfe(generate_nota(random.Random(1)), random.Random(1))
    document = Document("nota.pdf", MediaType.PDF, pdf)
    engine = StubEngine([OcrLine("DANFE", 10, 10, 90, 30)])
    extraction = DanfeOcrExtractor(engine).extract(document, NotaFiscal, "")
    assert extraction.data.modelo == "55"


def test_extractor_fails_without_text() -> None:
    with pytest.raises(ExtractionError, match="no text"):
        DanfeOcrExtractor(StubEngine([])).extract(_png(), NotaFiscal, "")


def test_extractor_rejects_other_schemas() -> None:
    class Other(BaseModel):
        value: int

    with pytest.raises(ExtractionError, match="does not support Other"):
        DanfeOcrExtractor(StubEngine([])).extract(_png(), Other, "")


def test_engine_converts_output_format(monkeypatch: pytest.MonkeyPatch) -> None:
    class Output:
        boxes = np.array([[[1, 2], [9, 2], [9, 8], [1, 8]]], dtype=np.float32)
        txts = ("DANFE",)
        scores = (0.9,)

    engine = RapidOcrEngine()
    monkeypatch.setattr(engine, "_load", lambda: lambda image: Output())
    line = engine.recognize(np.zeros((10, 10, 3), np.uint8))[0]
    assert (line.text, line.left, line.top, line.right, line.bottom) == ("DANFE", 1, 2, 9, 8)
    assert line.confidence == pytest.approx(0.9)


def test_engine_with_no_text(monkeypatch: pytest.MonkeyPatch) -> None:
    class Output:
        boxes = None

    engine = RapidOcrEngine()
    monkeypatch.setattr(engine, "_load", lambda: lambda image: Output())
    assert engine.recognize(np.zeros((10, 10, 3), np.uint8)) == []


@pytest.fixture
def no_real_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "_select_extractor",
        lambda name, settings: DanfeOcrExtractor(StubEngine([OcrLine("DANFE", 1, 1, 9, 9)])),
    )


@pytest.mark.usefixtures("no_real_ocr")
def test_cli_extract_with_ocr(tmp_path: Path) -> None:
    path = tmp_path / "page.png"
    path.write_bytes(_png().content)
    result = runner.invoke(cli.app, ["extract", str(path), "--extractor", "ocr"])
    assert result.exit_code == 0
    assert '"model": "stub-ocr"' in result.stdout


def test_select_extractor_never_uses_paid_api_for_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_: Settings) -> None:
        raise AssertionError("The paid backend must not be built.")

    monkeypatch.setattr(cli, "_build_extractor", fail)
    extractor = cli._select_extractor(cli.ExtractorName.OCR, Settings(_env_file=None))
    assert isinstance(extractor, DanfeOcrExtractor)


@pytest.mark.usefixtures("no_real_ocr")
def test_cli_generate_and_evaluate(tmp_path: Path) -> None:
    dataset = tmp_path / "data"
    reports = tmp_path / "reports"
    generated = runner.invoke(
        cli.app, ["eval", "generate", "-o", str(dataset), "-n", "1", "--seed", "3"]
    )
    assert generated.exit_code == 0

    result = runner.invoke(cli.app, ["eval", "run", "-d", str(dataset), "-o", str(reports)])
    assert result.exit_code == 0
    assert "Field accuracy" in result.stdout
    assert (reports / "ocr.json").exists()
    assert (reports / "ocr.md").exists()


def test_cli_evaluate_empty_dataset_fails(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["eval", "run", "-d", str(tmp_path), "-o", str(tmp_path)])
    assert result.exit_code == 1
    assert "No documents found" in result.stderr


@pytest.mark.ocr
def test_real_ocr_reads_a_rendered_danfe() -> None:
    """Uses the real models, to catch problems that the stub engine cannot show."""
    truth = generate_nota(random.Random(11))
    pdf = render_danfe(truth, random.Random(11))
    document = Document("nota.pdf", MediaType.PDF, pdf)

    extraction = DanfeOcrExtractor().extract(document, NotaFiscal, "")

    scores = compare(truth, extraction.data)
    assert sum(scores.values()) / len(scores) > 0.9
    assert extraction.data.chave_acesso == truth.chave_acesso
    assert re.fullmatch(r"[0-9]+", extraction.data.numero or "")
    assert not [issue for issue in NFE.validate(extraction.data) if issue.code.endswith("invalid")]


class SequenceEngine:
    """Returns the full page first, and then one answer for each enlarged crop."""

    name = "sequence-ocr"

    def __init__(self, *answers: list[OcrLine]) -> None:
        self.answers = list(answers)

    def recognize(self, image: object) -> list[OcrLine]:
        return self.answers.pop(0) if self.answers else []


def _page_with_key(key: str) -> list[OcrLine]:
    return [
        OcrLine("DANFE", 10, 2, 40, 8),
        OcrLine("CHAVE DE ACESSO", 10, 10, 90, 20),
        OcrLine(key, 10, 22, 90, 32),
    ]


def test_unreadable_key_is_read_again_from_an_enlarged_crop(nota: NotaFiscal) -> None:
    key = nota.chave_acesso or ""
    engine = SequenceEngine(
        _page_with_key("292555"),
        [OcrLine("not the key", 0, 0, 10, 10)],
        [OcrLine(key[22:], 100, 0, 200, 10), OcrLine(key[:22], 0, 0, 90, 10)],
    )
    extraction = DanfeOcrExtractor(engine).extract(_png(), NotaFiscal, "")
    assert extraction.data.chave_acesso == key


def test_first_reading_stays_when_no_crop_has_a_valid_key() -> None:
    extraction = DanfeOcrExtractor(SequenceEngine(_page_with_key("292555"))).extract(
        _png(), NotaFiscal, ""
    )
    assert extraction.data.chave_acesso == "292555"
    assert any(issue.code == "chave_acesso.invalid" for issue in NFE.validate(extraction.data))


def test_key_label_outside_the_image_is_ignored() -> None:
    lines = [OcrLine("CHAVE DE ACESSO", 10, 500, 90, 510)]
    extraction = DanfeOcrExtractor(SequenceEngine(lines)).extract(_png(), NotaFiscal, "")
    assert extraction.data.chave_acesso is None


def test_eval_run_reports_why_every_extraction_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner.invoke(cli.app, ["eval", "generate", "-o", str(tmp_path / "data"), "-n", "1"])

    class Failing:
        def extract(self, *_: object) -> None:
            raise ExtractionError("quota exceeded")

    monkeypatch.setattr(cli, "_select_extractor", lambda *_: Failing())
    result = runner.invoke(
        cli.app, ["eval", "run", "-d", str(tmp_path / "data"), "-o", str(tmp_path / "out")]
    )

    assert result.exit_code == 1
    assert "quota exceeded" in result.stderr
    assert "no report was written" in result.stderr
    assert not (tmp_path / "out").exists()
