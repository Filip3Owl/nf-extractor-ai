"""Extraction backend for public LLM APIs that follow the OpenAI chat completions format.

It talks HTTP directly, because the only part of the format it needs is one POST request.
Most of these APIs accept only images, so PDF pages are rendered before they are sent.
"""

import base64
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx2
from pydantic import BaseModel

from nf_extractor.core.document import Document, MediaType
from nf_extractor.core.result import Extraction, TokenUsage
from nf_extractor.errors import (
    ExtractionError,
    ExtractionRefusedError,
    ExtractionTruncatedError,
)
from nf_extractor.extractors.common import SYSTEM_PROMPT, parse_output

DEFAULT_MAX_TOKENS = 16000

_TIMEOUT_SECONDS = 180.0
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES = 3
_MAX_WAIT_SECONDS = 60.0
_MAX_DETAIL_CHARACTERS = 300

# Some models write their reasoning or a code fence around the JSON.
_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^```[\w-]*\n(?P<body>.*)\n```$", re.DOTALL)


@dataclass(frozen=True)
class Provider:
    """How to reach a public LLM API.

    Free model catalogs change often, so ``model`` is only a default. It can be replaced
    with ``NF_EXTRACTOR_LLM_MODEL``.
    """

    name: str
    base_url: str
    model: str
    api_key_env: str
    json_schema: bool = True
    """Whether to request ``json_schema`` output. If not, the prompt carries the schema."""


PROVIDERS = {
    "gemini": Provider(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model="gemini-3.8-flash",
        api_key_env="GEMINI_API_KEY",
    ),
    "groq": Provider(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        model="qwen/qwen3.8-27b",
        api_key_env="GROQ_API_KEY",
        # Groq documents only JSON mode for requests that contain images.
        json_schema=False,
    ),
    "openrouter": Provider(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model="google/gemma-4-31b-it:free",
        api_key_env="OPENROUTER_API_KEY",
    ),
}


def _data_url(media_type: str, content: bytes) -> str:
    return f"data:{media_type};base64,{base64.standard_b64encode(content).decode('ascii')}"


def _image_urls(document: Document) -> list[str]:
    """Convert a document into one data URL per page."""
    if document.media_type is not MediaType.PDF:
        return [_data_url(document.media_type.value, document.content)]
    try:
        import cv2

        from nf_extractor.extractors.preprocessing import rasterize

        pages = rasterize(document)
    except ImportError as exc:
        raise ExtractionError(
            "Sending PDFs to this API requires rendering them. Run: uv sync --extra vision"
        ) from exc
    return [
        _data_url(MediaType.PNG.value, cv2.imencode(".png", page)[1].tobytes()) for page in pages
    ]


def _clean_json(text: str) -> str:
    text = _THINK_BLOCK.sub("", text).strip()
    match = _FENCE.match(text)
    return match.group("body").strip() if match else text


def _error_detail(response: httpx2.Response) -> str:
    """Read the provider's error message. It explains, for example, which quota ran out."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, list) and body:  # Gemini wraps errors in an array.
        body = body[0]
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else error
    return str(message or "")[:_MAX_DETAIL_CHARACTERS]


def _retry_delay(response: httpx2.Response, attempt: int) -> float:
    try:
        delay = float(response.headers.get("retry-after", ""))
    except ValueError:
        delay = 2.0 ** (attempt + 1)
    return min(delay, _MAX_WAIT_SECONDS)


class OpenAICompatibleExtractor:
    """Reads documents with any vision model behind a chat completions API."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        json_schema: bool = True,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client: httpx2.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create an extractor.

        Args:
            base_url: The API address, without ``/chat/completions``.
            model: The model to use. It must accept images.
            api_key: The API key. Local servers may not need one.
            json_schema: Whether the API accepts ``json_schema`` output.
            max_tokens: The limit on the response size. Long invoices need more.
            client: The HTTP client.
            sleep: Waits between retries.
        """
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._model = model
        self._api_key = api_key
        self._json_schema = json_schema
        self._max_tokens = max_tokens
        self._client = client or httpx2.Client(timeout=_TIMEOUT_SECONDS)
        self._sleep = sleep

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
            ExtractionRefusedError: If the model declines to process the document.
            ExtractionTruncatedError: If the response exceeds ``max_tokens``.
            ExtractionError: If the API call fails or the output does not match the schema.
        """
        images = _image_urls(document)
        body = self._call(images, schema, instructions, use_schema=self._json_schema)
        if body is None:
            # Support for json_schema varies by model, so the schema moves to the prompt.
            body = self._call(images, schema, instructions, use_schema=False)
        if body is None:  # pragma: no cover - the call above never returns None
            raise ExtractionError(f"The API rejected the request for {document.name}.")

        try:
            choice = body["choices"][0]
            finish_reason = choice.get("finish_reason")
            content = choice.get("message", {}).get("content")
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ExtractionError(f"The response for {document.name} has no answer.") from exc

        if finish_reason == "content_filter":
            raise ExtractionRefusedError(f"The model declined to process {document.name}.")
        if finish_reason == "length":
            raise ExtractionTruncatedError(
                f"The response for {document.name} exceeded {self._max_tokens} tokens. "
                "Increase max_tokens and try again."
            )
        if not content:
            raise ExtractionError(f"The response for {document.name} contains no text.")

        usage = body.get("usage") or {}
        return Extraction(
            data=parse_output(_clean_json(content), schema, document.name),
            model=body.get("model") or self._model,
            usage=TokenUsage(
                input_tokens=usage.get("prompt_tokens") or 0,
                output_tokens=usage.get("completion_tokens") or 0,
            ),
        )

    def _call(
        self, images: list[str], schema: type[BaseModel], instructions: str, use_schema: bool
    ) -> dict[str, Any] | None:
        """Send the request, waiting and retrying while the API is rate limited or down.

        Returns:
            The response body, or ``None`` if the API rejected the ``json_schema`` request.
        """
        json_schema = schema.model_json_schema()
        if use_schema:
            text = instructions
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "strict": True, "schema": json_schema},
            }
        else:
            text = (
                f"{instructions}\nReturn only one JSON object that matches this JSON Schema:\n"
                f"{json.dumps(json_schema)}"
            )
            response_format = {"type": "json_object"}

        payload = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "response_format": response_format,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        *({"type": "image_url", "image_url": {"url": url}} for url in images),
                        {"type": "text", "text": text},
                    ],
                },
            ],
        }
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

        attempt = 0
        while True:
            try:
                response = self._client.post(self._url, json=payload, headers=headers)
            except httpx2.HTTPError as exc:
                raise ExtractionError(f"The API call failed: {type(exc).__name__}") from exc
            if response.status_code not in _RETRY_STATUSES or attempt == _MAX_RETRIES:
                break
            self._sleep(_retry_delay(response, attempt))
            attempt += 1

        if response.status_code == 400 and use_schema:
            return None
        if response.status_code != 200:
            raise ExtractionError(
                f"The API responded with status {response.status_code}: "
                f"{_error_detail(response)}".rstrip(": ")
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise ExtractionError("The API returned a response that is not JSON.") from exc
        if not isinstance(body, dict):
            raise ExtractionError("The API returned an unexpected response.")
        return body
