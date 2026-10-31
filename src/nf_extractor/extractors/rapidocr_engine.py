"""Local OCR with RapidOCR. It runs offline and has no per-document cost."""

from typing import TYPE_CHECKING, Any

from nf_extractor.core.ocr import OcrLine
from nf_extractor.errors import ExtractionError

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


class RapidOcrEngine:
    """Adapter for RapidOCR, running its models on OpenVINO.

    The models are downloaded the first time the engine runs. After that, no network
    access is needed and documents stay on the local machine.
    """

    name = "rapidocr-openvino"

    def __init__(self) -> None:
        """Create the engine. The models load on first use."""
        self._engine: Any = None

    def _load(self) -> Any:
        if self._engine is None:
            try:
                from rapidocr import EngineType, RapidOCR
            except ImportError as exc:
                raise ExtractionError(
                    "Local OCR is not installed. Run: uv sync --extra ocr"
                ) from exc
            self._engine = RapidOCR(
                params={
                    "Det.engine_type": EngineType.OPENVINO,
                    "Cls.engine_type": EngineType.OPENVINO,
                    "Rec.engine_type": EngineType.OPENVINO,
                    "Global.log_level": "error",
                }
            )
        return self._engine

    def recognize(self, image: "NDArray[np.uint8]") -> list[OcrLine]:
        """Return the lines of text found in a BGR image."""
        output = self._load()(image)
        if output.boxes is None:
            return []
        return [
            OcrLine(
                text=text,
                left=float(min(point[0] for point in box)),
                top=float(min(point[1] for point in box)),
                right=float(max(point[0] for point in box)),
                bottom=float(max(point[1] for point in box)),
                confidence=float(score),
            )
            for box, text, score in zip(
                output.boxes.tolist(), output.txts, output.scores, strict=True
            )
        ]
