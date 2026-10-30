# 0002. Claude structured outputs as the first backend

**Status:** Accepted

## Context

Traditional DANFE extraction combines preprocessing, OCR, layout analysis and per-layout rules. A vision LLM can read varied layouts with much less code, but it costs more per document, needs an external service, and can produce plausible errors.

## Decision

Start with a Claude extractor that sends the PDF or image directly to the API and requests JSON that matches the Pydantic schema through structured outputs.

- **Default model:** `claude-opus-5-5`, with `high` effort. Both are configurable.
- **Refusals:** the request sets `fallbacks: "default"`, so a request declined by a safety classifier is retried on another model. Fallback uses a beta API, and the model that actually answered is recorded in `ExtractionResult.model`.
- **Response handling:** the extractor calls `messages.create` and validates the JSON itself, instead of using the SDK's `messages.parse`. `parse` validates while reading the response, so a truncated response would surface as a generic validation error before `stop_reason` could be checked.
- **Trust:** model output is never considered correct on its own. Deterministic validators check it afterward.

## Consequences

- There is a working end-to-end flow with little code, with no OCR dependencies to install.
- Documents leave the local environment, which has privacy implications. See the README.
- Cost per document is higher than with local OCR. Token usage is recorded so that it can be measured, and the model and effort can be lowered if measurements show that quality holds.
- Accuracy has not been measured yet. Choosing between this and other approaches needs the evaluation harness on the roadmap.
