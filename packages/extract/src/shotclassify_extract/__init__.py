"""Category-specific extractors that polish LLM output using OCR text."""
from .receipt import enrich_receipt, parse_receipt_text
from .code import detect_framework, detect_language, enrich_code
from .error import enrich_error, parse_error_text
from .chat import enrich_chat
from .pipeline import enrich

__all__ = [
    "enrich",
    "enrich_receipt",
    "parse_receipt_text",
    "detect_framework",
    "detect_language",
    "enrich_code",
    "enrich_error",
    "parse_error_text",
    "enrich_chat",
]
