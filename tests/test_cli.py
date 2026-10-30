import json
from pathlib import Path

import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

from nf_extractor import __version__, cli
from nf_extractor.config import Settings
from nf_extractor.core.document import Document
from nf_extractor.core.result import Extraction, TokenUsage
from nf_extractor.document_types.nfe import NotaFiscal
from nf_extractor.errors import ExtractionError

runner = CliRunner()


class StubExtractor:
    def __init__(self, nota: NotaFiscal) -> None:
        self.nota = nota

    def extract[T: BaseModel](
        self, document: Document, schema: type[T], instructions: str
    ) -> Extraction[T]:
        return Extraction(
            data=schema.model_validate(self.nota.model_dump()),
            model="stub",
            usage=TokenUsage(input_tokens=1, output_tokens=1),
        )


class FailingExtractor:
    def extract[T: BaseModel](
        self, document: Document, schema: type[T], instructions: str
    ) -> Extraction[T]:
        raise ExtractionError("backend down")


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    path = tmp_path / "nota.pdf"
    path.write_bytes(b"%PDF-1.7")
    return path


def _use(monkeypatch: pytest.MonkeyPatch, extractor: object) -> None:
    monkeypatch.setattr(cli, "_build_extractor", lambda _: extractor)


def test_version() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_types_lists_nfe() -> None:
    result = runner.invoke(cli.app, ["types"])
    assert result.exit_code == 0
    assert result.stdout.startswith("nfe: ")


def test_extract_prints_json(monkeypatch: pytest.MonkeyPatch, pdf: Path, nota: NotaFiscal) -> None:
    _use(monkeypatch, StubExtractor(nota))
    result = runner.invoke(cli.app, ["extract", str(pdf)])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["is_valid"] is True
    assert payload["document_type"] == "nfe"
    assert payload["data"]["chave_acesso"] == nota.chave_acesso
    assert payload["data"]["totais"]["valor_total_nota"] == "130.00"


def test_extract_writes_output_file(
    monkeypatch: pytest.MonkeyPatch, pdf: Path, nota: NotaFiscal, tmp_path: Path
) -> None:
    _use(monkeypatch, StubExtractor(nota))
    output = tmp_path / "out.json"
    result = runner.invoke(cli.app, ["extract", str(pdf), "-o", str(output)])
    assert result.exit_code == 0
    assert result.stdout == ""
    assert json.loads(output.read_text(encoding="utf-8"))["is_valid"] is True


def test_validation_errors_exit_3_and_keep_output(
    monkeypatch: pytest.MonkeyPatch, pdf: Path, nota: NotaFiscal
) -> None:
    nota.chave_acesso = "123"
    _use(monkeypatch, StubExtractor(nota))
    result = runner.invoke(cli.app, ["extract", str(pdf)])
    assert result.exit_code == 3
    assert json.loads(result.stdout)["is_valid"] is False
    assert "ERROR [chave_acesso.invalid]" in result.stderr


def test_warnings_exit_0(monkeypatch: pytest.MonkeyPatch, pdf: Path, nota: NotaFiscal) -> None:
    nota.serie = None
    _use(monkeypatch, StubExtractor(nota))
    result = runner.invoke(cli.app, ["extract", str(pdf)])
    assert result.exit_code == 0
    assert "WARNING [field.missing]" in result.stderr


def test_extraction_failure_exits_1(monkeypatch: pytest.MonkeyPatch, pdf: Path) -> None:
    _use(monkeypatch, FailingExtractor())
    result = runner.invoke(cli.app, ["extract", str(pdf)])
    assert result.exit_code == 1
    assert "backend down" in result.stderr


def test_unknown_type_exits_1(monkeypatch: pytest.MonkeyPatch, pdf: Path) -> None:
    _use(monkeypatch, FailingExtractor())
    result = runner.invoke(cli.app, ["extract", str(pdf), "--type", "contract"])
    assert result.exit_code == 1
    assert "Unknown document type" in result.stderr


def test_missing_file_exits_1(monkeypatch: pytest.MonkeyPatch, nota: NotaFiscal) -> None:
    _use(monkeypatch, StubExtractor(nota))
    result = runner.invoke(cli.app, ["extract", "/nonexistent/nota.pdf"])
    assert result.exit_code == 1
    assert "Could not read" in result.stderr


def test_build_extractor_uses_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    monkeypatch.setenv("NF_EXTRACTOR_MODEL", "custom-model")
    monkeypatch.setenv("NF_EXTRACTOR_EFFORT", "low")
    monkeypatch.setenv("NF_EXTRACTOR_MAX_TOKENS", "123")
    settings = Settings(_env_file=None)
    assert settings.anthropic_api_key is not None
    assert "from-env" not in repr(settings)

    extractor = cli._build_extractor(settings)

    assert extractor._model == "custom-model"
    assert extractor._effort == "low"
    assert extractor._max_tokens == 123
    assert extractor._client.api_key == "from-env"


def test_build_extractor_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.anthropic_api_key is None
    assert isinstance(cli._build_extractor(settings)._client.api_key, str | None)
