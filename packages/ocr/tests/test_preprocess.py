import numpy as np

from shotclassify_ocr.preprocess import (
    deskew,
    estimate_skew_angle,
    preprocess_for_ocr,
    to_grayscale,
)


def test_grayscale_passthrough():
    arr = np.zeros((10, 10), dtype=np.uint8)
    assert to_grayscale(arr).shape == (10, 10)


def test_grayscale_rgb():
    arr = np.zeros((10, 10, 3), dtype=np.uint8)
    arr[..., 0] = 255
    g = to_grayscale(arr)
    assert g.shape == (10, 10)
    assert g.max() > 0


def test_skew_zero_for_blank():
    arr = np.full((50, 50), 255, dtype=np.uint8)
    assert estimate_skew_angle(arr) == 0.0


def test_deskew_returns_tuple():
    arr = np.full((20, 20, 3), 255, dtype=np.uint8)
    out, angle = deskew(arr)
    assert out.shape == arr.shape
    assert isinstance(angle, float)


def test_preprocess_returns_array():
    arr = np.full((30, 30, 3), 255, dtype=np.uint8)
    out, _ = preprocess_for_ocr(arr, do_deskew=False)
    assert out.ndim in (2, 3)
