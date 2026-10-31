"""Compare extracted data with known answers, and summarize the results."""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from statistics import median
from typing import Any

from pydantic import BaseModel

_LIST_INDEX = re.compile(r"\[\d+\]")


def flatten(model: BaseModel) -> dict[str, Any]:
    """Convert a model into a flat mapping, such as ``{"itens[0].cfop": "5102"}``.

    Each list also gets a ``<name>.count`` entry, so that lines that were skipped or
    invented affect the score.
    """
    flat: dict[str, Any] = {}

    def visit(value: Any, path: str) -> None:
        if isinstance(value, BaseModel):
            for name in type(value).model_fields:
                visit(getattr(value, name), f"{path}.{name}" if path else name)
        elif isinstance(value, list):
            flat[f"{path}.count"] = len(value)
            for index, element in enumerate(value):
                visit(element, f"{path}[{index}]")
        else:
            flat[path] = value

    visit(model, "")
    return flat


def _normalize(value: Any) -> Any:
    """Ignore differences that do not change meaning: case, accents and punctuation."""
    if isinstance(value, str):
        plain = unicodedata.normalize("NFKD", value)
        stripped = "".join(char for char in plain if not unicodedata.combining(char))
        return re.sub(r"[^a-z0-9]", "", stripped.lower()) or None
    if isinstance(value, Decimal):
        return value.normalize()
    if isinstance(value, date):
        return value.isoformat()
    return value


def compare(truth: BaseModel, predicted: BaseModel | None) -> dict[str, bool]:
    """Score each field of a document.

    Args:
        truth: The known values.
        predicted: The extracted values, or ``None`` if the extraction failed.

    Returns:
        Whether each field in the known values was read correctly.
    """
    expected = flatten(truth)
    actual = flatten(predicted) if predicted is not None else {}
    return {
        path: path in actual and _normalize(actual[path]) == _normalize(value)
        for path, value in expected.items()
    }


class DocumentScore(BaseModel):
    """The outcome for one document file."""

    case_id: str
    variant: str
    fields: dict[str, bool]
    failed: bool = False
    error: str | None = None
    flagged: bool = False
    seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def is_correct(self) -> bool:
        """Whether every field was read correctly."""
        return not self.failed and all(self.fields.values())


class VariantSummary(BaseModel):
    """Results for one kind of image quality."""

    variant: str
    documents: int
    failures: int
    field_accuracy: float
    perfect_documents: float
    median_seconds: float
    error_detection_rate: float | None
    false_alarm_rate: float | None


class EvaluationReport(BaseModel):
    """The complete results of an evaluation."""

    extractor: str
    documents: int
    variants: list[VariantSummary]
    field_accuracy: dict[str, float]
    input_tokens: int
    output_tokens: int

    def to_markdown(self) -> str:
        """Render the report as Markdown tables."""
        lines = [
            f"# Evaluation of `{self.extractor}`",
            "",
            f"Documents: {self.documents}. Tokens: {self.input_tokens} input, "
            f"{self.output_tokens} output.",
            "",
            "| Variant | Documents | Failures | Field accuracy | Perfect documents | "
            "Median time | Errors flagged | False alarms |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for item in self.variants:
            lines.append(
                f"| {item.variant} | {item.documents} | {item.failures} "
                f"| {_percent(item.field_accuracy)} | {_percent(item.perfect_documents)} "
                f"| {item.median_seconds:.1f} s | {_percent(item.error_detection_rate)} "
                f"| {_percent(item.false_alarm_rate)} |"
            )
        lines += ["", "| Field | Accuracy |", "|---|---:|"]
        lines += [
            f"| `{name}` | {_percent(accuracy)} |" for name, accuracy in self.field_accuracy.items()
        ]
        return "\n".join(lines) + "\n"


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _rate(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def _summarize_variant(variant: str, scores: list[DocumentScore]) -> VariantSummary:
    results = [result for score in scores for result in score.fields.values()]
    return VariantSummary(
        variant=variant,
        documents=len(scores),
        failures=sum(score.failed for score in scores),
        field_accuracy=_rate(results) or 0.0,
        perfect_documents=_rate([score.is_correct for score in scores]) or 0.0,
        median_seconds=median(score.seconds for score in scores),
        # Of the documents with a wrong value that returned output, how many were flagged?
        error_detection_rate=_rate(
            [s.flagged for s in scores if not s.failed and not s.is_correct]
        ),
        # Of the fully correct documents, how many were flagged without need?
        false_alarm_rate=_rate([s.flagged for s in scores if s.is_correct]),
    )


def summarize(extractor: str, scores: Iterable[DocumentScore]) -> EvaluationReport:
    """Combine document scores into a report."""
    all_scores = list(scores)
    by_variant: dict[str, list[DocumentScore]] = defaultdict(list)
    by_field: dict[str, list[bool]] = defaultdict(list)
    for score in all_scores:
        by_variant[score.variant].append(score)
        for path, correct in score.fields.items():
            by_field[_LIST_INDEX.sub("[]", path)].append(correct)
    return EvaluationReport(
        extractor=extractor,
        documents=len(all_scores),
        variants=[_summarize_variant(name, by_variant[name]) for name in sorted(by_variant)],
        field_accuracy={name: _rate(by_field[name]) or 0.0 for name in sorted(by_field)},
        input_tokens=sum(score.input_tokens for score in all_scores),
        output_tokens=sum(score.output_tokens for score in all_scores),
    )
