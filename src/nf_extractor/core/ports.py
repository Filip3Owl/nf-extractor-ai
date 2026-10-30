"""Interfaces that decouple the pipeline from specific extraction technologies."""

from typing import Protocol

from pydantic import BaseModel

from nf_extractor.core.document import Document
from nf_extractor.core.result import Extraction


class Extractor(Protocol):
    """Turns a document into structured data.

    Implement this protocol to add a backend, such as another LLM provider, an OCR
    engine, or a parser for XML files. The pipeline needs no changes.
    """

    def extract[T: BaseModel](
        self, document: Document, schema: type[T], instructions: str
    ) -> Extraction[T]:
        """Extract data from a document.

        Args:
            document: The document to read.
            schema: The Pydantic model that describes the expected output.
            instructions: Guidance specific to this document type.

        Returns:
            The extracted data and information about the call.

        Raises:
            ExtractionError: If the backend fails or returns an unusable response.
        """
        ...
