"""Extraction backend that uses Claude's vision and structured outputs."""

import base64
from typing import Literal

import anthropic
from anthropic import transform_schema
from anthropic.types.beta import BetaContentBlockParam
from pydantic import BaseModel

from nf_extractor.core.document import Document, MediaType
from nf_extractor.core.result import Extraction, TokenUsage
from nf_extractor.errors import (
    ExtractionError,
    ExtractionRefusedError,
    ExtractionTruncatedError,
)
from nf_extractor.extractors.common import SYSTEM_PROMPT, parse_output

Effort = Literal["low", "medium", "high", "xhigh", "max"]

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT: Effort = "high"
DEFAULT_MAX_TOKENS = 16000

# Lets the API retry a request on another model if a safety classifier declines it.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _document_block(document: Document) -> BetaContentBlockParam:
    """Build the API content block for a PDF or an image."""
    data = base64.standard_b64encode(document.content).decode("ascii")
    match document.media_type:
        case MediaType.PDF:
            return {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": data},
            }
        case MediaType.PNG:
            image_type: Literal["image/png", "image/jpeg", "image/webp"] = "image/png"
        case MediaType.JPEG:
            image_type = "image/jpeg"
        case MediaType.WEBP:
            image_type = "image/webp"
    return {"type": "image", "source": {"type": "base64", "media_type": image_type, "data": data}}


class ClaudeExtractor:
    """Reads documents with Claude and validates the response against a schema."""

    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        model: str = DEFAULT_MODEL,
        effort: Effort = DEFAULT_EFFORT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        """Create an extractor.

        Args:
            client: The API client. By default, credentials come from the environment.
            model: The Claude model to use.
            effort: How much reasoning the model applies to each document.
            max_tokens: The limit on the response size. Long invoices need more.
        """
        self._client = client or anthropic.Anthropic()
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens

    def extract[T: BaseModel](
        self, document: Document, schema: type[T], instructions: str
    ) -> Extraction[T]:
        """Extract data from a document.

        Uses ``create`` rather than the SDK's ``parse`` helper, which validates the JSON
        while reading the response. That would turn a truncated response into a generic
        validation error before ``stop_reason`` could be checked.

        Args:
            document: The document to read.
            schema: The Pydantic model that describes the expected output.
            instructions: Guidance specific to this document type.

        Returns:
            The extracted data and information about the call.

        Raises:
            ExtractionRefusedError: If the model declines to process the document.
            ExtractionTruncatedError: If the response exceeds ``max_tokens``.
            ExtractionError: If the API call fails or the output does not match the schema.
        """
        try:
            response = self._client.beta.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            _document_block(document),
                            {"type": "text", "text": instructions},
                        ],
                    }
                ],
                output_config={
                    "effort": self._effort,
                    "format": {"type": "json_schema", "schema": transform_schema(schema)},
                },
                fallbacks="default",
                betas=[_FALLBACK_BETA],
            )
        except (anthropic.APIError, TypeError) as exc:
            # The SDK raises TypeError when it finds no credentials.
            raise ExtractionError(f"Claude API call failed: {exc}") from exc

        if response.stop_reason == "refusal":
            raise ExtractionRefusedError(f"The model declined to process {document.name}.")
        if response.stop_reason == "max_tokens":
            raise ExtractionTruncatedError(
                f"The response for {document.name} exceeded {self._max_tokens} tokens. "
                "Increase max_tokens and try again."
            )

        # A fallback can leave earlier blocks in the response, so the answer is the last one.
        texts = [block.text for block in response.content if block.type == "text"]
        if not texts:
            raise ExtractionError(f"The response for {document.name} contains no text.")

        return Extraction(
            data=parse_output(texts[-1], schema, document.name),
            model=response.model,
            usage=TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
        )
