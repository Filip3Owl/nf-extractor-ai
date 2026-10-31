"""Command-line interface.

Exit codes:
    0: The document was extracted and passed validation. Warnings may be present.
    1: The extraction failed, so there is no output.
    2: The command was used incorrectly.
    3: The document was extracted, but validation found errors. Output is still written.
"""

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import anthropic
import typer

from nf_extractor import __version__
from nf_extractor.config import Settings
from nf_extractor.core.pipeline import ExtractionPipeline
from nf_extractor.core.ports import Extractor
from nf_extractor.document_types import default_registry
from nf_extractor.errors import NFExtractorError
from nf_extractor.extractors.claude import ClaudeExtractor
from nf_extractor.extractors.openai_compatible import (
    PROVIDERS,
    OpenAICompatibleExtractor,
    Provider,
)

EXIT_EXTRACTION_FAILED = 1
EXIT_VALIDATION_FAILED = 3

_EXTRACTOR_HELP = "`ocr` is free and local. All the others send documents to an external API."

app = typer.Typer(help="Turn unstructured documents into validated, structured data.")
eval_app = typer.Typer(help="Measure extraction quality on synthetic documents.")
app.add_typer(eval_app, name="eval")


class ExtractorName(StrEnum):
    """The available extraction backends."""

    CLAUDE = "claude"
    OCR = "ocr"
    GEMINI = "gemini"
    GROQ = "groq"
    OPENROUTER = "openrouter"
    CUSTOM = "custom"


def _build_extractor(settings: Settings) -> ClaudeExtractor:
    key = settings.anthropic_api_key
    client = anthropic.Anthropic(api_key=key.get_secret_value()) if key else anthropic.Anthropic()
    return ClaudeExtractor(
        client=client,
        model=settings.model,
        effort=settings.effort,
        max_tokens=settings.max_tokens,
    )


def _build_custom_extractor(settings: Settings) -> OpenAICompatibleExtractor:
    if not settings.llm_base_url or not settings.llm_model:
        raise NFExtractorError(
            "The custom extractor needs NF_EXTRACTOR_LLM_BASE_URL and NF_EXTRACTOR_LLM_MODEL."
        )
    return OpenAICompatibleExtractor(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key.get_secret_value() if settings.llm_api_key else None,
        max_tokens=settings.max_tokens,
    )


def _build_provider_extractor(provider: Provider, settings: Settings) -> OpenAICompatibleExtractor:
    keys = {
        "gemini": settings.gemini_api_key,
        "groq": settings.groq_api_key,
        "openrouter": settings.openrouter_api_key,
    }
    key = keys[provider.name]
    if key is None:
        raise NFExtractorError(f"Set {provider.api_key_env} to use {provider.name}.")
    return OpenAICompatibleExtractor(
        base_url=provider.base_url,
        model=settings.llm_model or provider.model,
        api_key=key.get_secret_value(),
        json_schema=provider.json_schema,
        max_tokens=settings.max_tokens,
    )


def _select_extractor(name: ExtractorName, settings: Settings) -> Extractor:
    if name is ExtractorName.CLAUDE:
        return _build_extractor(settings)
    if name is ExtractorName.CUSTOM:
        return _build_custom_extractor(settings)
    if name is not ExtractorName.OCR:
        return _build_provider_extractor(PROVIDERS[name.value], settings)
    try:
        from nf_extractor.extractors.danfe_ocr import DanfeOcrExtractor
    except ImportError as exc:
        raise NFExtractorError("Local OCR is not installed. Run: uv sync --extra ocr") from exc
    return DanfeOcrExtractor()


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """Turn unstructured documents into validated, structured data."""


@app.command()
def extract(
    file: Annotated[Path, typer.Argument(help="PDF, PNG, JPEG or WebP file to read.")],
    document_type: Annotated[
        str, typer.Option("--type", "-t", help="Document type. See the `types` command.")
    ] = "nfe",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the JSON here instead of standard output."),
    ] = None,
    extractor: Annotated[
        ExtractorName,
        typer.Option("--extractor", "-e", help=_EXTRACTOR_HELP),
    ] = ExtractorName.CLAUDE,
) -> None:
    """Extract structured data from a document and validate it."""
    if extractor.value in PROVIDERS:
        typer.echo(
            f"Note: this document will be sent to {extractor.value}. Free tiers may use what "
            "they receive to improve their products, so do not send real invoices to them.",
            err=True,
        )
    try:
        result = ExtractionPipeline(_select_extractor(extractor, Settings())).run(
            file, default_registry().get(document_type)
        )
    except NFExtractorError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(EXIT_EXTRACTION_FAILED) from exc

    content = result.model_dump_json(indent=2)
    if output is None:
        typer.echo(content)
    else:
        output.write_text(content + "\n", encoding="utf-8")

    for issue in result.issues:
        typer.echo(f"{issue.severity.value.upper()} [{issue.code}] {issue.message}", err=True)

    if not result.is_valid:
        raise typer.Exit(EXIT_VALIDATION_FAILED)


@app.command("types")
def list_types() -> None:
    """List the available document types."""
    for document_type in default_registry().all():
        typer.echo(f"{document_type.name}: {document_type.description}")


@eval_app.command("generate")
def eval_generate(
    output: Annotated[Path, typer.Option("--output", "-o", help="Target directory.")] = Path(
        "data/synthetic"
    ),
    count: Annotated[int, typer.Option("--count", "-n", min=1, help="Invoices to create.")] = 20,
    seed: Annotated[int, typer.Option(help="The same seed gives the same dataset.")] = 42,
) -> None:
    """Create a dataset of fictional invoices, each in several image qualities."""
    try:
        from nf_extractor.evaluation.dataset import generate_dataset
    except ImportError as exc:
        typer.echo("Error: Evaluation tools are not installed. Run: uv sync --extra eval", err=True)
        raise typer.Exit(EXIT_EXTRACTION_FAILED) from exc
    generate_dataset(output, count, seed)
    typer.echo(f"Created {count} invoices in {output}")


@eval_app.command("run")
def eval_run(
    dataset: Annotated[Path, typer.Option("--dataset", "-d", help="Dataset directory.")] = Path(
        "data/synthetic"
    ),
    output: Annotated[Path, typer.Option("--output", "-o", help="Report directory.")] = Path(
        "reports"
    ),
    extractor: Annotated[
        ExtractorName,
        typer.Option("--extractor", "-e", help=_EXTRACTOR_HELP),
    ] = ExtractorName.OCR,
) -> None:
    """Measure an extractor on a dataset, and write JSON and Markdown reports."""
    try:
        from nf_extractor.document_types.nfe import NFE
        from nf_extractor.evaluation.dataset import iter_cases
        from nf_extractor.evaluation.harness import evaluate

        cases = list(iter_cases(dataset))
        if not cases:
            raise NFExtractorError(f"No documents found in {dataset}.")
        report = evaluate(
            dataset,
            _select_extractor(extractor, Settings()),
            extractor.value,
            NFE,
            on_progress=lambda score: typer.echo(
                f"{score.case_id}/{score.variant}" + (f": {score.error}" if score.error else ""),
                err=True,
            ),
            cases=cases,
        )
    except (ImportError, NFExtractorError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(EXIT_EXTRACTION_FAILED) from exc

    # A report of zeros would look like poor accuracy when the cause is, say, a bad API key.
    if sum(variant.failures for variant in report.variants) == report.documents:
        typer.echo("Error: every extraction failed, so no report was written.", err=True)
        raise typer.Exit(EXIT_EXTRACTION_FAILED)

    output.mkdir(parents=True, exist_ok=True)
    (output / f"{extractor.value}.json").write_text(
        report.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    markdown = report.to_markdown()
    (output / f"{extractor.value}.md").write_text(markdown, encoding="utf-8")
    typer.echo(markdown)
