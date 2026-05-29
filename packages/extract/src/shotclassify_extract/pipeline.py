"""Pipeline that runs the right extractor for the classified category."""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult

from .chat import enrich_chat
from .code import enrich_code
from .error import enrich_error
from .receipt import enrich_receipt


def enrich(category: Category, fields: ExtractedFields, ocr: OCRResult) -> ExtractedFields:
    out = fields.model_copy(deep=True)
    if category == Category.receipt:
        out.receipt = enrich_receipt(out.receipt, ocr)
    elif category == Category.code_snippet:
        out.code = enrich_code(out.code, ocr)
    elif category == Category.error_stacktrace:
        out.error = enrich_error(out.error, ocr)
    elif category == Category.chat_screenshot:
        out.chat = enrich_chat(out.chat, ocr)
    # meme/document/ui_mockup/chart/other rely on LLM fields; nothing to enrich
    return out
