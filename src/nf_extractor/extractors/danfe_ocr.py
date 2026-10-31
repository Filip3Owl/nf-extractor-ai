"""A free, offline extractor for DANFEs: OCR followed by layout rules."""

from typing import TYPE_CHECKING, cast

import cv2
import numpy as np
from pydantic import BaseModel

from nf_extractor.core.document import Document
from nf_extractor.core.ocr import OcrEngine, OcrLine
from nf_extractor.core.result import Extraction, TokenUsage
from nf_extractor.document_types.nfe.ocr_parser import normalize_text, parse_danfe
from nf_extractor.document_types.nfe.schema import NotaFiscal
from nf_extractor.errors import ExtractionError
from nf_extractor.extractors.preprocessing import deskew, rasterize
from nf_extractor.extractors.rapidocr_engine import RapidOcrEngine
from nf_extractor.validators.br_identifiers import is_valid_access_key, normalize_identifier

if TYPE_CHECKING:
    from numpy.typing import NDArray

_KEY_LABEL = "CHAVE DE ACESSO"
_REREAD_SCALES = (2, 3, 4)


class DanfeOcrExtractor:
    """Reads DANFEs with local OCR, so documents never leave the machine.

    It uses no LLM, so ``instructions`` is ignored and only :class:`NotaFiscal` is
    supported. Token usage is always zero.
    """

    def __init__(self, engine: OcrEngine | None = None) -> None:
        """Create an extractor.

        Args:
            engine: The OCR engine. Defaults to RapidOCR.
        """
        self._engine: OcrEngine = engine or RapidOcrEngine()

    def extract[T: BaseModel](
        self, document: Document, schema: type[T], instructions: str
    ) -> Extraction[T]:
        """Extract an invoice from a document.

        Args:
            document: The DANFE to read.
            schema: Must be :class:`NotaFiscal`.
            instructions: Ignored, since no LLM is involved.

        Returns:
            The extracted data and information about the call.

        Raises:
            ExtractionError: If the schema is not supported or OCR finds no text.
        """
        if schema is not NotaFiscal:
            raise ExtractionError(f"OCR extraction does not support {schema.__name__}.")

        lines: list[OcrLine] = []
        pages: list[tuple[NDArray[np.uint8], list[OcrLine]]] = []
        page_top = 0.0
        width = 0.0
        for raster in rasterize(document):
            page = deskew(raster)
            page_lines = self._engine.recognize(page)
            pages.append((page, page_lines))
            # Pages are stacked so that a table spanning pages stays in reading order.
            for line in page_lines:
                lines.append(
                    OcrLine(
                        text=line.text,
                        left=line.left,
                        top=line.top + page_top,
                        right=line.right,
                        bottom=line.bottom + page_top,
                        confidence=line.confidence,
                    )
                )
            page_top += page.shape[0]
            width = max(width, page.shape[1])

        if not lines:
            raise ExtractionError(f"OCR found no text in {document.name}.")

        nota = parse_danfe(lines, width)
        if not is_valid_access_key(nota.chave_acesso or ""):
            key = self._reread_access_key(pages)
            if key is not None:
                nota = nota.model_copy(update={"chave_acesso": key})

        return Extraction(
            data=cast(T, nota),
            model=self._engine.name,
            usage=TokenUsage(input_tokens=0, output_tokens=0),
        )

    def _reread_access_key(
        self, pages: "list[tuple[NDArray[np.uint8], list[OcrLine]]]"
    ) -> str | None:
        """Read the access key again from an enlarged crop, since it is printed very small.

        A new reading is accepted only if its check digit is correct. Otherwise, the first
        reading stays in the result, so that the validators report it.
        """
        for page, page_lines in pages:
            for label in page_lines:
                if _KEY_LABEL not in normalize_text(label.text):
                    continue
                height = label.bottom - label.top
                crop = page[
                    int(label.bottom) : int(label.bottom + 3 * height),
                    max(int(label.left - height), 0) :,
                ]
                if crop.size == 0:
                    continue
                for scale in _REREAD_SCALES:
                    enlarged = cv2.resize(
                        crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
                    )
                    found = self._engine.recognize(np.asarray(enlarged, dtype=np.uint8))
                    ordered = sorted(found, key=lambda line: line.left)
                    key = normalize_identifier(" ".join(line.text for line in ordered))
                    if is_valid_access_key(key):
                        return key
        return None
