# 0003. Public LLM APIs through one chat completions backend

**Status:** Accepted

## Context

For now, the project relies on public LLM APIs instead of hosting its own models. [ADR 0002](0002-claude-structured-outputs.md) added Claude, but the Claude API has no free tier, and that blocks measuring LLM accuracy during development. Gemini, Groq and OpenRouter have free options, and they all expose the same chat completions format.

## Decision

Add one `OpenAICompatibleExtractor`, plus a small table of providers with their address, default model and API key variable. `ClaudeExtractor` stays separate, because it uses features that this format does not have, such as sending PDFs directly and falling back after a refusal.

- **HTTP:** the extractor makes one POST with `httpx2`, which the Anthropic SDK already installs, so no provider SDK is needed.
- **PDFs:** pages are rendered as PNG images, because most of these APIs accept only images. This needs the `vision` extra.
- **Output format:** it requests `json_schema` output. If the API answers with a 400, it tries once more with JSON mode and the schema in the prompt, since support varies by model. Groq goes straight to JSON mode, because that is the only format it documents for requests with images.
- **Rate limits:** free tiers often answer with a 429, so the extractor waits and retries up to 3 times, for at most 60 seconds each time.
- **Default models:** they were checked against each provider's documentation in October 2026. Free catalogs change often, so `NF_EXTRACTOR_LLM_MODEL` replaces them without a code change.

## Consequences

- LLM accuracy can be measured on synthetic documents at no cost, subject to each provider's limits.
- **Free tiers are not suitable for real invoices.** For example, Google's [Gemini API terms](https://ai.google.dev/gemini-api/terms) say that content sent to unpaid services can be used to improve its products and may be read by human reviewers, and they ask users not to submit personal information. The CLI prints a warning, and the README explains this.
- Tests simulate HTTP responses, so they cannot show differences in how each provider behaves. Each provider still needs a first real call with an API key.
- A provider's limit on images per request, such as Groq's limit of 3 for its default model, appears as an API error on longer PDFs.
