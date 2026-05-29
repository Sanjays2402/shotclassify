"""Tesseract-backed OCR with preprocessing."""
from .preprocess import deskew, preprocess_for_ocr
from .runner import OCRRunner, run_ocr

__all__ = ["OCRRunner", "run_ocr", "deskew", "preprocess_for_ocr"]
