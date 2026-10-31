"""Exercise the extractor against a simulated HTTP transport, so no external API is called."""

import base64
import json
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest
from typer.testing import CliRunner

from nf_extractor import cli
from nf_extractor.config import Settings
from nf_extractor.core.document import Document, MediaType
from nf_extractor.document_types.nfe import NFE, NotaFiscal
from nf_extractor.errors import (
    ExtractionError,
    ExtractionRefusedError,
    ExtractionTruncatedError,
    NFExtractorError,
)
from nf_extractor.evaluation.renderer import render_danfe
from nf_extractor.evaluation.synthetic import generate_nota
from nf_extractor.extractors.openai_compatible import PROVIDERS, OpenAICompatibleExtractor

PNG = Document("nota.png", MediaType.PNG, b"\x89PNG\r\n\x1a\nfake")

Handler = Callable[[httpx2.Request], httpx2.Response]
runner = CliRunner()


def _answer(content: str | None, finish_reason: str = "stop") -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "model": "served-model",
            "choices": [{"finish_reason": finish_reason, "message": {"content": content}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        },
    )


def _extractor(handler: Handler, waits: list[float] | None = None, **kwargs: Any) -> Any:
    return OpenAICompatibleExtractor(
        base_url="https://llm.example/v1/",
        model="vision-model",
        api_key="secret-key",
        client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        sleep=(waits if waits is not None else []).append,
        **kwargs,
    )


def test_extracts_and_reports_usage(nota: NotaFiscal) -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return _answer(nota.model_dump_json())

    extraction = _extractor(handler, max_tokens=123).extract(PNG, NotaFiscal, NFE.instructions)

    assert extraction.data == nota
    assert extraction.model == "served-model"
    assert extraction.usage.input_tokens == 100
    assert extraction.usage.output_tokens == 50

    request = requests[0]
    assert str(request.url) == "https://llm.example/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer secret-key"
    payload = json.loads(request.content)
    assert payload["model"] == "vision-model"
    assert payload["max_tokens"] == 123
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert "untrusted" in payload["messages"][0]["content"]
    image, text = payload["messages"][1]["content"]
    encoded = base64.standard_b64encode(PNG.content).decode("ascii")
    assert image["image_url"]["url"] == f"data:image/png;base64,{encoded}"
    assert text["text"] == NFE.instructions


def test_json_mode_puts_schema_in_prompt(nota: NotaFiscal) -> None:
    payloads: list[Any] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        payloads.append(json.loads(request.content))
        return _answer(nota.model_dump_json())

    _extractor(handler, json_schema=False).extract(PNG, NotaFiscal, "guide")

    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert "chave_acesso" in payloads[0]["messages"][1]["content"][-1]["text"]


def test_rejected_json_schema_falls_back_to_json_mode(nota: NotaFiscal) -> None:
    formats: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        kind = json.loads(request.content)["response_format"]["type"]
        formats.append(kind)
        if kind == "json_schema":
            return httpx2.Response(400, json={"error": {"message": "unsupported schema"}})
        return _answer(nota.model_dump_json())

    extraction = _extractor(handler).extract(PNG, NotaFiscal, "guide")

    assert extraction.data == nota
    assert formats == ["json_schema", "json_object"]


def test_second_rejection_is_reported() -> None:
    extractor = _extractor(lambda _: httpx2.Response(400, json={"error": {"message": "too big"}}))
    with pytest.raises(ExtractionError, match="status 400: too big"):
        extractor.extract(PNG, NotaFiscal, "guide")


@pytest.mark.parametrize(
    "wrap",
    ["<think>first the header</think>\n{}", "```json\n{}\n```"],
)
def test_removes_reasoning_and_code_fences(nota: NotaFiscal, wrap: str) -> None:
    content = wrap.format(nota.model_dump_json())
    extraction = _extractor(lambda _: _answer(content)).extract(PNG, NotaFiscal, "guide")
    assert extraction.data == nota


def test_pdf_pages_are_sent_as_images() -> None:
    rng = random.Random(1)
    pdf = Document("nota.pdf", MediaType.PDF, render_danfe(generate_nota(rng), rng))
    payloads: list[Any] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        payloads.append(json.loads(request.content))
        return _answer(None)

    with pytest.raises(ExtractionError, match="no text"):
        _extractor(handler).extract(pdf, NotaFiscal, "guide")

    image = payloads[0]["messages"][1]["content"][0]
    assert image["image_url"]["url"].startswith("data:image/png;base64,")


def test_missing_pdf_tools_explain_what_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(__import__("sys").modules, "cv2", None)
    pdf = Document("nota.pdf", MediaType.PDF, b"%PDF-1.7")
    with pytest.raises(ExtractionError, match="--extra vision"):
        _extractor(lambda _: _answer(None)).extract(pdf, NotaFiscal, "guide")


def test_rate_limit_waits_as_requested_and_retries(nota: NotaFiscal) -> None:
    responses = [
        httpx2.Response(429, headers={"retry-after": "7"}),
        httpx2.Response(503, headers={"retry-after": "9999"}),
        httpx2.Response(500),
        _answer(nota.model_dump_json()),
    ]
    waits: list[float] = []

    extraction = _extractor(lambda _: responses.pop(0), waits).extract(PNG, NotaFiscal, "guide")

    assert extraction.data == nota
    assert waits == [7.0, 60.0, 8.0]


def test_rate_limit_stops_after_the_last_retry() -> None:
    calls: list[int] = []

    def handler(_: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return httpx2.Response(429, json=[{"error": {"message": "daily quota exceeded"}}])

    with pytest.raises(ExtractionError, match="status 429: daily quota exceeded"):
        _extractor(handler).extract(PNG, NotaFiscal, "guide")
    assert len(calls) == 4


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx2.Response(401, text="not json"), r"status 401$"),
        (httpx2.Response(403, json={"error": "denied"}), "status 403: denied"),
        (httpx2.Response(200, text="not json"), "not JSON"),
        (httpx2.Response(200, json=[]), "unexpected"),
        (httpx2.Response(200, json={"choices": []}), "no answer"),
        (_answer(None), "no text"),
        (_answer("not json"), "does not match the schema"),
    ],
)
def test_unusable_responses_raise(response: httpx2.Response, message: str) -> None:
    with pytest.raises(ExtractionError, match=message):
        _extractor(lambda _: response, json_schema=False).extract(PNG, NotaFiscal, "guide")


def test_connection_failure_hides_details() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("https://llm.example?key=secret-key", request=request)

    with pytest.raises(ExtractionError, match="ConnectError") as info:
        _extractor(handler).extract(PNG, NotaFiscal, "guide")
    assert "secret-key" not in str(info.value)


def test_content_filter_is_a_refusal() -> None:
    extractor = _extractor(lambda _: _answer(None, "content_filter"))
    with pytest.raises(ExtractionRefusedError):
        extractor.extract(PNG, NotaFiscal, "guide")


def test_truncation_has_its_own_error() -> None:
    extractor = _extractor(lambda _: _answer('{"chave', "length"))
    with pytest.raises(ExtractionTruncatedError):
        extractor.extract(PNG, NotaFiscal, "guide")


def test_missing_usage_counts_as_zero(nota: NotaFiscal) -> None:
    body = {"choices": [{"message": {"content": nota.model_dump_json()}}]}
    extraction = _extractor(lambda _: httpx2.Response(200, json=body)).extract(
        PNG, NotaFiscal, "guide"
    )
    assert extraction.model == "vision-model"
    assert extraction.usage.input_tokens == 0


@pytest.mark.parametrize("name", sorted(PROVIDERS))
def test_providers_need_their_own_key(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    provider = PROVIDERS[name]
    monkeypatch.delenv(provider.api_key_env, raising=False)
    with pytest.raises(NFExtractorError, match=provider.api_key_env):
        cli._build_provider_extractor(provider, Settings(_env_file=None))

    monkeypatch.setenv(provider.api_key_env, "provider-key")
    settings = Settings(_env_file=None)
    assert "provider-key" not in repr(settings)
    extractor = cli._build_provider_extractor(provider, settings)
    assert extractor._api_key == "provider-key"
    assert extractor._model == provider.model
    assert extractor._json_schema is provider.json_schema


def test_model_can_be_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "key")
    monkeypatch.setenv("NF_EXTRACTOR_LLM_MODEL", "newer-model")
    extractor = cli._build_provider_extractor(PROVIDERS["groq"], Settings(_env_file=None))
    assert extractor._model == "newer-model"


def test_custom_extractor_needs_address_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NF_EXTRACTOR_LLM_BASE_URL", raising=False)
    with pytest.raises(NFExtractorError, match="NF_EXTRACTOR_LLM_BASE_URL"):
        cli._select_extractor(cli.ExtractorName.CUSTOM, Settings(_env_file=None))

    monkeypatch.setenv("NF_EXTRACTOR_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("NF_EXTRACTOR_LLM_MODEL", "local-vision")
    extractor = cli._select_extractor(cli.ExtractorName.CUSTOM, Settings(_env_file=None))
    assert isinstance(extractor, OpenAICompatibleExtractor)
    assert extractor._api_key is None


def test_cli_warns_before_sending_to_a_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "nota.pdf"
    path.write_bytes(b"%PDF-1.7")

    result = runner.invoke(cli.app, ["extract", str(path), "-e", "gemini"])

    assert result.exit_code == 1
    assert "do not send real invoices" in result.stderr
    assert "Set GEMINI_API_KEY" in result.stderr
