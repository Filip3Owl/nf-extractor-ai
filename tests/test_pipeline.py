import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import BaseModel

from nf_extractor.core.document import Document, MediaType
from nf_extractor.core.document_type import DocumentType, DocumentTypeRegistry
from nf_extractor.core.pipeline import ExtractionPipeline
from nf_extractor.core.result import Extraction, Severity, TokenUsage, ValidationIssue
from nf_extractor.errors import UnknownDocumentTypeError, UnsupportedDocumentError


class Receipt(BaseModel):
    total: int


class FakeExtractor:
    def __init__(self, total: int = 10) -> None:
        self.total = total
        self.calls: list[tuple[Document, str]] = []

    def extract[T: BaseModel](
        self, document: Document, schema: type[T], instructions: str
    ) -> Extraction[T]:
        self.calls.append((document, instructions))
        return Extraction(
            data=schema.model_validate({"total": self.total}),
            model="fake-model",
            usage=TokenUsage(input_tokens=1, output_tokens=2),
        )


def _reject_negative(receipt: Receipt) -> Iterator[ValidationIssue]:
    if receipt.total < 0:
        yield ValidationIssue(code="negative", message="Negative.", severity=Severity.ERROR)


def _warn_on_zero(receipt: Receipt) -> Iterator[ValidationIssue]:
    if receipt.total == 0:
        yield ValidationIssue(code="zero", message="Zero.", severity=Severity.WARNING)


RECEIPT = DocumentType[Receipt](
    name="receipt",
    description="A receipt",
    schema=Receipt,
    instructions="Read the total.",
    validators=(_reject_negative, _warn_on_zero),
)
DOCUMENT = Document("receipt.png", MediaType.PNG, b"\x89PNG\r\n\x1a\n")


def test_pipeline_works_with_any_document_type_and_extractor() -> None:
    extractor = FakeExtractor()
    result = ExtractionPipeline(extractor).run(DOCUMENT, RECEIPT)

    assert extractor.calls == [(DOCUMENT, "Read the total.")]
    assert result.data == Receipt(total=10)
    assert result.document_name == "receipt.png"
    assert result.document_type == "receipt"
    assert result.model == "fake-model"
    assert result.issues == []
    assert result.is_valid


def test_pipeline_loads_paths(tmp_path: Path) -> None:
    path = tmp_path / "receipt.pdf"
    path.write_bytes(b"%PDF-1.7")
    extractor = FakeExtractor()
    result = ExtractionPipeline(extractor).run(path, RECEIPT)
    assert result.document_name == "receipt.pdf"
    assert extractor.calls[0][0].media_type is MediaType.PDF


def test_load_failure_does_not_reach_the_extractor(tmp_path: Path) -> None:
    extractor = FakeExtractor()
    with pytest.raises(UnsupportedDocumentError):
        ExtractionPipeline(extractor).run(tmp_path / "missing.pdf", RECEIPT)
    assert extractor.calls == []


def test_errors_invalidate_the_result_but_keep_the_data() -> None:
    result = ExtractionPipeline(FakeExtractor(total=-1)).run(DOCUMENT, RECEIPT)
    assert not result.is_valid
    assert result.data.total == -1
    assert [issue.code for issue in result.issues] == ["negative"]


def test_warnings_do_not_invalidate_the_result() -> None:
    result = ExtractionPipeline(FakeExtractor(total=0)).run(DOCUMENT, RECEIPT)
    assert result.is_valid
    assert [issue.code for issue in result.issues] == ["zero"]


def test_result_serialization_includes_data_and_validity() -> None:
    result = ExtractionPipeline(FakeExtractor()).run(DOCUMENT, RECEIPT)
    payload = json.loads(result.model_dump_json())
    assert payload["data"] == {"total": 10}
    assert payload["is_valid"] is True
    assert payload["usage"] == {"input_tokens": 1, "output_tokens": 2}


def test_registry_lookup() -> None:
    registry = DocumentTypeRegistry()
    registry.register(RECEIPT)
    assert registry.get("receipt") is RECEIPT
    assert registry.all() == [RECEIPT]


def test_registry_rejects_duplicates() -> None:
    registry = DocumentTypeRegistry()
    registry.register(RECEIPT)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(RECEIPT)


def test_registry_unknown_type_lists_available_types() -> None:
    registry = DocumentTypeRegistry()
    registry.register(RECEIPT)
    with pytest.raises(UnknownDocumentTypeError, match="Available: receipt"):
        registry.get("contract")
