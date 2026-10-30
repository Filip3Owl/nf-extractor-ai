"""Exercise the real SDK against a simulated HTTP transport, so no API credits are spent."""

import base64
import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest

from nf_extractor.core.document import Document, MediaType
from nf_extractor.document_types.nfe import NFE, NotaFiscal
from nf_extractor.errors import (
    ExtractionError,
    ExtractionRefusedError,
    ExtractionTruncatedError,
)
from nf_extractor.extractors.claude import ClaudeExtractor

PDF = Document("nota.pdf", MediaType.PDF, b"%PDF-1.7")

Handler = Callable[[httpx2.Request], httpx2.Response]


def _message(
    content: list[dict[str, Any]], stop_reason: str = "end_turn", model: str = "claude-opus-5-5"
) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        },
    )


def _extractor(handler: Handler) -> ClaudeExtractor:
    client = anthropic.Anthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    return ClaudeExtractor(client=client)


def _text(nota: NotaFiscal) -> dict[str, Any]:
    return {"type": "text", "text": nota.model_dump_json()}


def test_extracts_and_validates_response(nota: NotaFiscal) -> None:
    extraction = _extractor(lambda _: _message([_text(nota)])).extract(
        PDF, NotaFiscal, NFE.instructions
    )
    assert extraction.data == nota
    assert extraction.model == "claude-opus-5-5"
    assert extraction.usage.input_tokens == 100
    assert extraction.usage.output_tokens == 50


def test_request_for_pdf(nota: NotaFiscal) -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return _message([_text(nota)])

    _extractor(handler).extract(PDF, NotaFiscal, "Read it.")

    assert "server-side-fallback-2026-07-01" in requests[0].headers["anthropic-beta"]
    body = json.loads(requests[0].content)
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert body["output_config"]["effort"] == "high"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "thinking" not in body
    document_block, text_block = body["messages"][0]["content"]
    assert document_block["type"] == "document"
    assert document_block["source"]["media_type"] == "application/pdf"
    assert base64.b64decode(document_block["source"]["data"]) == PDF.content
    assert text_block == {"type": "text", "text": "Read it."}


@pytest.mark.parametrize("media_type", [MediaType.PNG, MediaType.JPEG, MediaType.WEBP])
def test_request_for_image_uses_image_block(nota: NotaFiscal, media_type: MediaType) -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return _message([_text(nota)])

    document = Document("nota", media_type, b"image")
    _extractor(handler).extract(document, NotaFiscal, "Read it.")
    block = json.loads(requests[0].content)["messages"][0]["content"][0]
    assert block["type"] == "image"
    assert block["source"]["media_type"] == media_type.value


def test_output_schema_is_strict() -> None:
    schema = anthropic.transform_schema(NotaFiscal)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(NotaFiscal.model_fields)


def test_refusal_raises_before_reading_content() -> None:
    with pytest.raises(ExtractionRefusedError, match=r"nota\.pdf"):
        _extractor(lambda _: _message([], stop_reason="refusal")).extract(PDF, NotaFiscal, "x")


def test_truncated_response_has_a_specific_error() -> None:
    partial = [{"type": "text", "text": '{"chave_acesso": "35'}]
    with pytest.raises(ExtractionTruncatedError, match="max_tokens"):
        _extractor(lambda _: _message(partial, stop_reason="max_tokens")).extract(
            PDF, NotaFiscal, "x"
        )


def test_response_without_text_is_an_error() -> None:
    with pytest.raises(ExtractionError, match="no text"):
        _extractor(lambda _: _message([])).extract(PDF, NotaFiscal, "x")


def test_schema_mismatch_error_does_not_expose_values() -> None:
    bad = [{"type": "text", "text": '{"chave_acesso": "SENSITIVE-VALUE"}'}]
    with pytest.raises(ExtractionError, match="does not match the schema") as caught:
        _extractor(lambda _: _message(bad)).extract(PDF, NotaFiscal, "x")
    assert "SENSITIVE-VALUE" not in str(caught.value)


def test_api_failure_is_wrapped() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            500, json={"type": "error", "error": {"type": "api_error", "message": "boom"}}
        )

    with pytest.raises(ExtractionError, match="API call failed"):
        _extractor(handler).extract(PDF, NotaFiscal, "x")


def test_last_text_block_is_used(nota: NotaFiscal) -> None:
    content = [{"type": "text", "text": "partial"}, _text(nota)]
    extraction = _extractor(lambda _: _message(content, model="fallback-model")).extract(
        PDF, NotaFiscal, "x"
    )
    assert extraction.data == nota
    assert extraction.model == "fallback-model"
