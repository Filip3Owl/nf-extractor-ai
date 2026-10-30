"""The orchestration flow: load, extract, then validate."""

from pathlib import Path

from pydantic import BaseModel

from nf_extractor.core.document import Document, load_document
from nf_extractor.core.document_type import DocumentType
from nf_extractor.core.ports import Extractor
from nf_extractor.core.result import ExtractionResult


class ExtractionPipeline:
    """Runs documents through an extractor and checks the output.

    The pipeline knows nothing about Brazilian invoices or about any LLM provider:
    both are supplied from the outside, which keeps it reusable for future projects.
    """

    def __init__(self, extractor: Extractor) -> None:
        """Create a pipeline.

        Args:
            extractor: The backend that reads the documents.
        """
        self._extractor = extractor

    def run[T: BaseModel](
        self, source: Path | Document, document_type: DocumentType[T]
    ) -> ExtractionResult[T]:
        """Process one document.

        Failing business rules is reported through ``ExtractionResult.issues`` rather
        than raised, so callers keep the extracted data and can send it for review.

        Args:
            source: A path to load, or a document already in memory.
            document_type: Defines the output schema and the rules to check.

        Returns:
            The extracted data together with any issues found.

        Raises:
            UnsupportedDocumentError: If the file cannot be loaded.
            ExtractionError: If the extractor fails.
        """
        document = load_document(source) if isinstance(source, Path) else source
        extraction = self._extractor.extract(
            document, document_type.schema, document_type.instructions
        )
        return ExtractionResult[T](
            document_name=document.name,
            document_type=document_type.name,
            model=extraction.model,
            usage=extraction.usage,
            data=extraction.data,
            issues=document_type.validate(extraction.data),
        )
