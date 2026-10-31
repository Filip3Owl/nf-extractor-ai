"""Image preparation that helps OCR read scans and photos."""

from typing import TYPE_CHECKING

import cv2
import numpy as np

from nf_extractor.core.document import Document, MediaType
from nf_extractor.errors import UnsupportedDocumentError

if TYPE_CHECKING:
    from numpy.typing import NDArray

RENDER_DPI = 200
_MAX_SKEW_DEGREES = 15.0
_MIN_SKEW_DEGREES = 0.2


def rasterize(document: Document, dpi: int = RENDER_DPI) -> "list[NDArray[np.uint8]]":
    """Convert a document into one BGR image per page.

    Args:
        document: A PDF or an image.
        dpi: The resolution used to render PDF pages.

    Returns:
        The page images.

    Raises:
        UnsupportedDocumentError: If the file is corrupted.
    """
    if document.media_type is MediaType.PDF:
        import pypdfium2

        try:
            pdf = pypdfium2.PdfDocument(document.content)
        except pypdfium2.PdfiumError as exc:
            raise UnsupportedDocumentError(f"Could not read {document.name}: {exc}") from exc
        pages = []
        for page in pdf:
            # pypdfium2 renders in BGR order, which is what OpenCV expects.
            bgr = page.render(scale=dpi / 72).to_numpy()
            pages.append(np.asarray(bgr[:, :, :3], dtype=np.uint8).copy())
        pdf.close()
        return pages

    image = cv2.imdecode(np.frombuffer(document.content, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise UnsupportedDocumentError(f"Could not decode {document.name}.")
    return [np.asarray(image, dtype=np.uint8)]


def estimate_skew(image: "NDArray[np.uint8]") -> float:
    """Estimate page rotation in degrees from long, nearly horizontal lines.

    Fiscal documents are full of ruled boxes, which give a much stronger signal than text.
    Returns 0 when too few lines are found to be confident.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    width = image.shape[1]
    segments = cv2.HoughLinesP(
        edges, 1, np.pi / 720, threshold=120, minLineLength=width // 4, maxLineGap=10
    )
    if segments is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in segments[:, 0]:
        angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        if abs(angle) <= _MAX_SKEW_DEGREES:
            angles.append(angle)
    return float(np.median(angles)) if len(angles) >= 3 else 0.0


def deskew(image: "NDArray[np.uint8]") -> "NDArray[np.uint8]":
    """Rotate a page so that its ruled lines become horizontal."""
    angle = estimate_skew(image)
    if abs(angle) < _MIN_SKEW_DEGREES:
        return image
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    rotated = cv2.warpAffine(
        image, matrix, (width, height), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255)
    )
    return np.asarray(rotated, dtype=np.uint8)
