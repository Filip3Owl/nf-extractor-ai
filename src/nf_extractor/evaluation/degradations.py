"""Simulate what happens to documents when they are scanned or photographed."""

from collections.abc import Callable
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

Degradation = Callable[["NDArray[np.uint8]", np.random.Generator], "NDArray[np.uint8]"]


def rotated(image: "NDArray[np.uint8]", rng: np.random.Generator) -> "NDArray[np.uint8]":
    """Rotate by up to 4 degrees, like a page placed crookedly on a scanner."""
    magnitude = rng.uniform(1.0, 4.0)
    angle = magnitude if rng.random() < 0.5 else -magnitude
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    result = cv2.warpAffine(
        image, matrix, (width, height), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255)
    )
    return np.asarray(result, dtype=np.uint8)


def noisy(image: "NDArray[np.uint8]", rng: np.random.Generator) -> "NDArray[np.uint8]":
    """Add sensor noise."""
    noise = rng.normal(0, 18, image.shape)
    return np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def blurred(image: "NDArray[np.uint8]", rng: np.random.Generator) -> "NDArray[np.uint8]":
    """Blur the image, like a camera that is slightly out of focus."""
    result = cv2.GaussianBlur(image, (5, 5), rng.uniform(1.0, 1.6))
    return np.asarray(result, dtype=np.uint8)


def low_resolution(image: "NDArray[np.uint8]", _rng: np.random.Generator) -> "NDArray[np.uint8]":
    """Reduce a 200 DPI page to about 110 DPI."""
    result = cv2.resize(image, None, fx=0.55, fy=0.55, interpolation=cv2.INTER_AREA)
    return np.asarray(result, dtype=np.uint8)


def jpeg_artifacts(image: "NDArray[np.uint8]", _rng: np.random.Generator) -> "NDArray[np.uint8]":
    """Apply heavy JPEG compression, like an image forwarded through messaging apps."""
    _, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 15])
    result = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    return np.asarray(result, dtype=np.uint8)


def photo(image: "NDArray[np.uint8]", rng: np.random.Generator) -> "NDArray[np.uint8]":
    """Combine perspective, uneven lighting, blur and noise, like a phone photo."""
    height, width = image.shape[:2]
    corners = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32)
    shift = rng.uniform(-0.02, 0.02, corners.shape) * np.array([width, height])
    matrix = cv2.getPerspectiveTransform(corners, (corners + shift).astype(np.float32))
    warped = cv2.warpPerspective(image, matrix, (width, height), borderValue=(200, 200, 200))

    shadow = np.linspace(rng.uniform(0.65, 0.85), 1.0, width, dtype=np.float32)
    if rng.random() < 0.5:
        shadow = shadow[::-1]
    lit = warped.astype(np.float32) * shadow[np.newaxis, :, np.newaxis]

    softened = cv2.GaussianBlur(lit, (3, 3), 0.8)
    grainy = softened + rng.normal(0, 8, softened.shape)
    return np.clip(grainy, 0, 255).astype(np.uint8)


DEGRADATIONS: dict[str, Degradation] = {
    "rotated": rotated,
    "noisy": noisy,
    "blurred": blurred,
    "low_resolution": low_resolution,
    "jpeg_artifacts": jpeg_artifacts,
    "photo": photo,
}
