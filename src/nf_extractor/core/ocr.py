"""The interface between OCR engines and the parsers that interpret their output."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True)
class OcrLine:
    """A line of recognized text and its position, in pixels."""

    text: str
    left: float
    top: float
    right: float
    bottom: float
    confidence: float = 1.0


class OcrEngine(Protocol):
    """Recognizes text in an image. Implement this to add another OCR engine."""

    name: str

    def recognize(self, image: "NDArray[np.uint8]") -> list[OcrLine]:
        """Return the lines of text found in a BGR image."""
        ...
