"""Run an extractor over a dataset and score the results."""

from collections.abc import Callable, Iterable
from pathlib import Path
from time import perf_counter

from nf_extractor.core.document_type import DocumentType
from nf_extractor.core.pipeline import ExtractionPipeline
from nf_extractor.core.ports import Extractor
from nf_extractor.document_types.nfe.schema import NotaFiscal
from nf_extractor.errors import NFExtractorError
from nf_extractor.evaluation.dataset import Case, iter_cases
from nf_extractor.evaluation.metrics import DocumentScore, EvaluationReport, compare, summarize


def score_case(
    case: Case, pipeline: ExtractionPipeline, document_type: DocumentType[NotaFiscal]
) -> DocumentScore:
    """Process one document and compare the output with its known values.

    A failed extraction counts as every field being wrong, rather than stopping the run.
    """
    start = perf_counter()
    try:
        result = pipeline.run(case.path, document_type)
    except NFExtractorError as exc:
        return DocumentScore(
            case_id=case.case_id,
            variant=case.variant,
            fields=compare(case.truth, None),
            failed=True,
            error=str(exc),
            seconds=perf_counter() - start,
        )
    return DocumentScore(
        case_id=case.case_id,
        variant=case.variant,
        fields=compare(case.truth, result.data),
        flagged=bool(result.issues),
        seconds=perf_counter() - start,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
    )


def evaluate(
    dataset: Path,
    extractor: Extractor,
    extractor_name: str,
    document_type: DocumentType[NotaFiscal],
    on_progress: Callable[[DocumentScore], None] | None = None,
    cases: Iterable[Case] | None = None,
) -> EvaluationReport:
    """Evaluate an extractor on a dataset.

    Args:
        dataset: The directory created by ``generate_dataset``.
        extractor: The extractor to measure.
        extractor_name: The name shown in the report.
        document_type: Defines the validation rules to apply.
        on_progress: Called after each document.
        cases: Replaces the documents read from ``dataset``, to evaluate a subset.

    Returns:
        The aggregated results.
    """
    pipeline = ExtractionPipeline(extractor)
    scores = []
    for case in iter_cases(dataset) if cases is None else cases:
        score = score_case(case, pipeline, document_type)
        scores.append(score)
        if on_progress is not None:
            on_progress(score)
    return summarize(extractor_name, scores)
