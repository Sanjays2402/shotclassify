"""Image preprocessing for OCR: grayscale, denoise, threshold, deskew."""
from __future__ import annotations

import math
from typing import Tuple

import numpy as np

try:  # cv2 is heavy; tolerate absence in tests
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore


def _to_array(image) -> np.ndarray:
    if isinstance(image, np.ndarray):
        return image
    from PIL import Image  # local import

    if isinstance(image, Image.Image):
        return np.array(image.convert("RGB"))
    raise TypeError(f"Unsupported image type: {type(image)}")


def to_grayscale(image) -> np.ndarray:
    arr = _to_array(image)
    if arr.ndim == 2:
        return arr
    if cv2 is not None:
        return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    # Fallback luminance
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    return (0.299 * r + 0.587 * g + 0.114 * b).astype(np.uint8)


def estimate_skew_angle(gray: np.ndarray) -> float:
    """Estimate skew angle in degrees from a binarized image.

    Uses the minimum-area rectangle of non-background pixels. Pure numpy
    fallback covers the no-cv2 path used in CI.
    """
    if gray.size == 0:
        return 0.0
    threshold = max(1, int(gray.mean() * 0.6))
    coords = np.column_stack(np.where(gray < threshold))
    if coords.shape[0] < 50:
        return 0.0
    if cv2 is not None:
        angle = cv2.minAreaRect(coords[:, ::-1])[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        return float(angle)
    # numpy fallback: principal axis via SVD
    centered = coords - coords.mean(axis=0)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    primary = vt[0]
    angle_rad = math.atan2(primary[0], primary[1])
    angle_deg = math.degrees(angle_rad)
    if angle_deg > 45:
        angle_deg -= 90
    if angle_deg < -45:
        angle_deg += 90
    return float(angle_deg)


def deskew(image, max_angle: float = 15.0) -> Tuple[np.ndarray, float]:
    """Return (deskewed_array, angle_applied)."""
    arr = _to_array(image)
    gray = to_grayscale(arr)
    angle = estimate_skew_angle(gray)
    if abs(angle) < 0.25 or abs(angle) > max_angle:
        return arr, 0.0
    if cv2 is None:
        return arr, 0.0
    h, w = arr.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rotated = cv2.warpAffine(
        arr, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    return rotated, angle


def preprocess_for_ocr(image, do_deskew: bool = True) -> Tuple[np.ndarray, float]:
    arr = _to_array(image)
    angle = 0.0
    if do_deskew:
        arr, angle = deskew(arr)
    gray = to_grayscale(arr)
    if cv2 is None:
        return gray, angle
    denoised = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)
    _, binarized = cv2.threshold(
        denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    return binarized, angle
