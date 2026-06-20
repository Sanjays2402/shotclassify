"""Pipeline that runs the right extractor for the classified category."""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult

from .chat import enrich_chat
from .code import enrich_code
from .error import enrich_error
from .paths import extract_paths
from .receipt import enrich_receipt
from .urls import extract_urls


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

    # Cross-category: stash every http(s) URL found in the OCR text
    # under raw["urls"]. Runs for EVERY category because URLs show up
    # everywhere (error -> docs link, receipt -> Yelp page, chat ->
    # mostly links). Callers that need only one category's URLs can
    # ignore the key; storage already persists raw as a JSON column.
    text = ocr.text or ""
    urls = extract_urls(text)
    if urls:
        out.raw = dict(out.raw or {})
        out.raw["urls"] = urls

    # Cross-category: stash filesystem paths found in the OCR text
    # under raw["paths"]. Mirrors the URL extractor (also runs for
    # every category) -- error stacktraces, code snippets, terminal
    # screenshots, and documents all reference paths and dashboards
    # want a single key to look at. URL spans are masked out before
    # scanning so a URL's path component does not double-count.
    paths = extract_paths(text)
    if paths:
        out.raw = dict(out.raw or {})
        out.raw["paths"] = paths

    return out
