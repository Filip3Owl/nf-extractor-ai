"""Create and read datasets of synthetic documents with known answers.

Layout on disk::

    dataset/
    └── case_0001/
        ├── truth.json
        ├── clean.pdf
        ├── rotated.jpg
        └── ...
"""

import random
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from nf_extractor.core.document import Document, MediaType
from nf_extractor.document_types.nfe.schema import NotaFiscal
from nf_extractor.evaluation.degradations import DEGRADATIONS
from nf_extractor.evaluation.renderer import render_danfe
from nf_extractor.evaluation.synthetic import generate_nota
from nf_extractor.extractors.preprocessing import rasterize

TRUTH_FILE = "truth.json"
CLEAN_VARIANT = "clean"
_JPEG_QUALITY = 95


@dataclass(frozen=True)
class Case:
    """One document file and the values it is known to contain."""

    case_id: str
    variant: str
    path: Path
    truth: NotaFiscal


def generate_dataset(output: Path, count: int, seed: int) -> None:
    """Write a reproducible dataset.

    Args:
        output: The target directory, created if needed.
        count: The number of invoices. Each one is saved clean and in every degradation.
        seed: The same seed always produces the same dataset.
    """
    rng = random.Random(seed)
    image_rng = np.random.default_rng(seed)
    for index in range(1, count + 1):
        nota = generate_nota(rng)
        pdf = render_danfe(nota, rng)

        folder = output / f"case_{index:04d}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / TRUTH_FILE).write_text(nota.model_dump_json(indent=2) + "\n", encoding="utf-8")
        (folder / f"{CLEAN_VARIANT}.pdf").write_bytes(pdf)

        page = rasterize(Document("page.pdf", MediaType.PDF, pdf))[0]
        for name, degrade in DEGRADATIONS.items():
            image = degrade(page, image_rng)
            cv2.imwrite(
                str(folder / f"{name}.jpg"), image, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY]
            )


def iter_cases(dataset: Path) -> Iterator[Case]:
    """Read every document in a dataset, in a stable order."""
    for truth_path in sorted(dataset.glob(f"*/{TRUTH_FILE}")):
        truth = NotaFiscal.model_validate_json(truth_path.read_text(encoding="utf-8"))
        for path in sorted(truth_path.parent.iterdir()):
            if path.name != TRUTH_FILE:
                yield Case(truth_path.parent.name, path.stem, path, truth)
