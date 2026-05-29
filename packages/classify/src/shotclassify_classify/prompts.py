"""Prompt templates for vision classification + extraction."""
from __future__ import annotations

from shotclassify_common import Category

CLASSIFY_SYSTEM = """You are ShotClassify, a screenshot triage system.

You analyse a single image plus an OCR transcript and decide:
  1. which category it belongs to,
  2. how confident you are in every category,
  3. structured fields appropriate to the chosen category.

Always respond with JSON matching the provided schema. Never invent fields
that are not present in the image. When a field is missing, set it to null.
Do not include commentary outside the JSON object.
"""


CATEGORY_HINTS = {
    Category.receipt: "Look for vendor name, totals, line items, tax, date.",
    Category.code_snippet: "Detect programming language, return raw code as-is.",
    Category.error_stacktrace: "Identify framework (Python, Node, JVM, etc.), exception, message, likely cause.",
    Category.chat_screenshot: "Identify platform (iMessage, Slack, WhatsApp, Discord) and participants.",
    Category.meme: "Identify template if known; pull top and bottom captions.",
    Category.document: "PDF page, slide, article. Summarise in one sentence.",
    Category.ui_mockup: "Figma, design tool, or wireframe; list main components.",
    Category.chart: "Identify chart type (bar, line, pie), axes, series.",
    Category.other: "Use only when nothing else fits.",
}


SCHEMA_HINT = """Respond with this exact JSON shape:
{
  "primary": "<one of: receipt|code_snippet|error_stacktrace|chat_screenshot|meme|document|ui_mockup|chart|other>",
  "confidences": [{"category": "<cat>", "score": <0..1>}, ...nine entries...],
  "rationale": "<one sentence>",
  "fields": {
    "receipt": null | {"vendor": ..., "date": ..., "subtotal": ..., "tax": ..., "total": ..., "currency": ..., "items": [{"description": ..., "qty": ..., "price": ...}]},
    "code": null | {"language": ..., "code": "...", "line_count": <int>},
    "error": null | {"framework": ..., "exception": ..., "message": ..., "likely_cause": ..., "file": ..., "line": <int>},
    "chat": null | {"platform": ..., "participants": [...], "messages": [{"sender": ..., "text": ...}]},
    "meme": null | {"template": ..., "top_text": ..., "bottom_text": ...},
    "document": null | {"title": ..., "summary": ..., "page_kind": ...},
    "ui_mockup": null | {"framework_guess": ..., "components": [...]},
    "chart": null | {"chart_type": ..., "title": ..., "axes": {"x": ..., "y": ...}, "series": [...]}
  }
}
Only populate the field object that matches the primary category. Set all others to null.
"""


def build_user_prompt(ocr_text: str, note: str | None = None) -> str:
    hints = "\n".join(f"- {c.value}: {h}" for c, h in CATEGORY_HINTS.items())
    note_block = f"\nUser note: {note}\n" if note else ""
    ocr_block = ocr_text.strip()[:6000] if ocr_text else "(no OCR text)"
    return f"""Classify this screenshot.
{note_block}
Category hints:
{hints}

OCR transcript:
---
{ocr_block}
---

{SCHEMA_HINT}
"""
