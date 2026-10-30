"""Input documents and how they are loaded from disk."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from nf_extractor.errors import UnsupportedDocumentError

# Base64 encoding grows a file by a third, so this keeps requests under the 32 MB API limit.
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


class MediaType(StrEnum):
    """File formats accepted by the pipeline."""

    PDF = "application/pdf"
    PNG = "image/png"
    JPEG = "image/jpeg"
    WEBP = "image/webp"


@dataclass(frozen=True, repr=False)
class Document:
    """A document held in memory, ready to be sent to an extractor."""

    name: str
    media_type: MediaType
    content: bytes

    def __repr__(self) -> str:
        """Describe the document without exposing its contents in logs."""
        return (
            f"Document(name={self.name!r}, media_type={self.media_type.value!r}, "
            f"bytes={len(self.content)})"
        )


def detect_media_type(content: bytes) -> MediaType | None:
    """Identify a file format from its magic bytes, since extensions can be wrong.

    Args:
        content: The raw file content.

    Returns:
        The detected media type, or ``None`` if the format is not supported.
    """
    if content.startswith(b"%PDF-"):
        return MediaType.PDF
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return MediaType.PNG
    if content.startswith(b"\xff\xd8\xff"):
        return MediaType.JPEG
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return MediaType.WEBP
    return None


def load_document(path: Path) -> Document:
    """Read and check a document from disk.

    Args:
        path: Location of a PDF, PNG, JPEG or WebP file.

    Returns:
        The loaded document.

    Raises:
        UnsupportedDocumentError: If the file cannot be read, is empty, is larger than
            :data:`MAX_DOCUMENT_BYTES`, or has an unsupported format.
    """
    try:
        size = path.stat().st_size
        if size > MAX_DOCUMENT_BYTES:
            raise UnsupportedDocumentError(
                f"{path.name} has {size} bytes; the limit is {MAX_DOCUMENT_BYTES}."
            )
        content = path.read_bytes()
    except OSError as exc:
        raise UnsupportedDocumentError(f"Could not read {path}: {exc}") from exc

    if not content:
        raise UnsupportedDocumentError(f"{path.name} is empty.")

    media_type = detect_media_type(content)
    if media_type is None:
        supported = ", ".join(item.value for item in MediaType)
        raise UnsupportedDocumentError(
            f"{path.name} has an unsupported format. Supported formats: {supported}."
        )
    return Document(name=path.name, media_type=media_type, content=content)
