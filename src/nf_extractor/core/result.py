"""Outputs of the extraction pipeline."""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, SerializeAsAny, computed_field


class Severity(StrEnum):
    """How much a validation issue should affect trust in the extracted data."""

    WARNING = "warning"
    """The data looks unusual or incomplete and may deserve human review."""

    ERROR = "error"
    """The data breaks a rule that a genuine document always satisfies."""


class ValidationIssue(BaseModel):
    """A problem found while checking extracted data."""

    code: str
    message: str
    severity: Severity
    field: str | None = None


class TokenUsage(BaseModel):
    """Tokens consumed by one extraction, used to track cost."""

    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class Extraction[T: BaseModel]:
    """What an extractor returns: structured data plus information about the call."""

    data: T
    model: str
    usage: TokenUsage


class ExtractionResult[T: BaseModel](BaseModel):
    """The final output of the pipeline for one document."""

    document_name: str
    document_type: str
    model: str
    usage: TokenUsage
    data: SerializeAsAny[T]
    issues: list[ValidationIssue]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_valid(self) -> bool:
        """Whether no issue has error severity. Warnings do not invalidate a result."""
        return not any(issue.severity is Severity.ERROR for issue in self.issues)
