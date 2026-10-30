"""Document type definitions and the registry that makes them discoverable."""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from nf_extractor.core.result import ValidationIssue
from nf_extractor.errors import UnknownDocumentTypeError


@dataclass(frozen=True)
class DocumentType[T: BaseModel]:
    """Everything the pipeline needs to know about one kind of document.

    Attributes:
        name: Unique identifier used by the CLI and the registry, such as ``"nfe"``.
        description: One-line summary shown to users.
        schema: The Pydantic model that describes the extracted data.
        instructions: Guidance for the extractor about this kind of document.
        validators: Business rules checked after extraction.
    """

    name: str
    description: str
    schema: type[T]
    instructions: str
    validators: Sequence[Callable[[T], Iterable[ValidationIssue]]] = ()

    def validate(self, data: T) -> list[ValidationIssue]:
        """Run every validator and collect the issues they find."""
        return [issue for validator in self.validators for issue in validator(data)]


class DocumentTypeRegistry:
    """A lookup table of the document types available to an application."""

    def __init__(self) -> None:
        """Create an empty registry."""
        self._types: dict[str, DocumentType[Any]] = {}

    def register(self, document_type: DocumentType[Any]) -> None:
        """Add a document type.

        Raises:
            ValueError: If the name is already registered.
        """
        if document_type.name in self._types:
            raise ValueError(f"Document type already registered: {document_type.name}")
        self._types[document_type.name] = document_type

    def get(self, name: str) -> DocumentType[Any]:
        """Look up a document type by name.

        Raises:
            UnknownDocumentTypeError: If the name is not registered.
        """
        try:
            return self._types[name]
        except KeyError:
            available = ", ".join(sorted(self._types)) or "none"
            raise UnknownDocumentTypeError(
                f"Unknown document type: {name}. Available: {available}."
            ) from None

    def all(self) -> list[DocumentType[Any]]:
        """Return every registered document type, sorted by name."""
        return [self._types[name] for name in sorted(self._types)]
