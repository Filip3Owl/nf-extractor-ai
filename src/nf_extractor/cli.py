"""Command-line interface.

Exit codes:
    0: The document was extracted and passed validation. Warnings may be present.
    1: The extraction failed, so there is no output.
    2: The command was used incorrectly.
    3: The document was extracted, but validation found errors. Output is still written.
"""

from pathlib import Path
from typing import Annotated

import anthropic
import typer

from nf_extractor import __version__
from nf_extractor.config import Settings
from nf_extractor.core.pipeline import ExtractionPipeline
from nf_extractor.document_types import default_registry
from nf_extractor.errors import NFExtractorError
from nf_extractor.extractors.claude import ClaudeExtractor

EXIT_EXTRACTION_FAILED = 1
EXIT_VALIDATION_FAILED = 3

app = typer.Typer(help="Turn unstructured documents into validated, structured data.")


def _build_extractor(settings: Settings) -> ClaudeExtractor:
    key = settings.anthropic_api_key
    client = anthropic.Anthropic(api_key=key.get_secret_value()) if key else anthropic.Anthropic()
    return ClaudeExtractor(
        client=client,
        model=settings.model,
        effort=settings.effort,
        max_tokens=settings.max_tokens,
    )


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
) -> None:
    """Extract structured data from a document and validate it."""
    try:
        result = ExtractionPipeline(_build_extractor(Settings())).run(
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
