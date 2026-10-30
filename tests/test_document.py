from pathlib import Path

import pytest

from nf_extractor.core import document as document_module
from nf_extractor.core.document import Document, MediaType, detect_media_type, load_document
from nf_extractor.errors import UnsupportedDocumentError


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"%PDF-1.7 content", MediaType.PDF),
        (b"\x89PNG\r\n\x1a\ncontent", MediaType.PNG),
        (b"\xff\xd8\xff\xe0content", MediaType.JPEG),
        (b"RIFF\x00\x00\x00\x00WEBPcontent", MediaType.WEBP),
        (b"plain text", None),
        (b"RIFF\x00\x00\x00\x00WAVEcontent", None),
    ],
)
def test_detect_media_type(content: bytes, expected: MediaType | None) -> None:
    assert detect_media_type(content) is expected


def test_load_document_uses_content_rather_than_extension(tmp_path: Path) -> None:
    path = tmp_path / "invoice.txt"
    path.write_bytes(b"%PDF-1.7 content")
    document = load_document(path)
    assert document.name == "invoice.txt"
    assert document.media_type is MediaType.PDF
    assert document.content == b"%PDF-1.7 content"


def test_load_document_missing_file(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedDocumentError, match="Could not read"):
        load_document(tmp_path / "missing.pdf")


def test_load_document_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    path.touch()
    with pytest.raises(UnsupportedDocumentError, match="empty"):
        load_document(path)


def test_load_document_unsupported_format(tmp_path: Path) -> None:
    path = tmp_path / "notes.pdf"
    path.write_text("not a pdf")
    with pytest.raises(UnsupportedDocumentError, match="unsupported format"):
        load_document(path)


def test_load_document_too_large(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(document_module, "MAX_DOCUMENT_BYTES", 4)
    path = tmp_path / "large.pdf"
    path.write_bytes(b"%PDF-1.7")
    with pytest.raises(UnsupportedDocumentError, match="limit"):
        load_document(path)


def test_repr_does_not_expose_content() -> None:
    document = Document("nota.pdf", MediaType.PDF, b"secret")
    assert "secret" not in repr(document)
    assert "bytes=6" in repr(document)
