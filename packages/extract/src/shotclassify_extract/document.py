"""Document-category enrichment.

Multi-page document captures (scanned contracts, PDFs, slide
decks, wiki pages) almost always print a page-number marker at
the bottom or top of each page. We surface that marker into
``DocumentFields.page_info`` as a ``{"current", "total", "label",
"continued"}`` dict so dashboards can render
``"Page 3 of 12 (continued)"`` annotations without re-parsing the
OCR text.

Recognised footer / header shapes (case-insensitive throughout):

* ``Page 3 of 12``                  -> {current: 3, total: 12}
* ``Page 3 / 12`` / ``3 / 12``      -> {current: 3, total: 12}
* ``Page 1``                        -> {current: 1, total: None}
* ``p. 7``                          -> {current: 7, total: None}
* ``- 5 -``                         -> {current: 5, total: None}
* ``Pg. 12``                        -> {current: 12, total: None}
* ``Sheet 3 of 5``                  -> {current: 3, total: 5}
* ``Slide 4 of 20``                 -> {current: 4, total: 20}

The ``(continued)`` marker (with or without parens, case-
insensitive) is detected independently and tags ``continued=True``
on the result.

Safety: bare digit pairs without a vocabulary anchor (``3 / 12``
without ``Page`` / ``Slide`` / ``Sheet`` / ``Pg`` / ``p.``) are
RECOGNISED only when the slash-shaped pair stands alone on its own
line, so a date like ``3 / 12 / 2024`` doesn't false-positive as
a page marker (it has a trailing ``/ 2024`` segment) and a math
fraction ``3 / 12 of pie`` likewise rejects.

Output dict shape:
    {
        "current": int | None,
        "total": int | None,
        "label": str,
        "continued": bool,
    }

When no recognised page marker is present, returns ``None``.
"""
from __future__ import annotations

import re

from shotclassify_common import DocumentFields, OCRResult

# Page-number patterns. Each entry is a (compiled regex, has_total)
# tuple. ``has_total`` indicates whether the regex captures a
# ``total`` named group (so the caller knows to read it). Patterns
# are ordered most-specific FIRST so the multi-word forms ``Page 3
# of 12`` beat the bare ``Page 3`` shape and bare ``3 / 12``
# slash-form.
_PAGE_PATTERNS: tuple[tuple[re.Pattern, bool], ...] = (
    # ``Page 3 of 12`` (most common; also ``Pages 3 of 12``).
    (re.compile(
        r"(?P<label>"
        r"Pages?\s+(?P<current>\d{1,4})\s+of\s+(?P<total>\d{1,4})"
        r")",
        re.IGNORECASE,
    ), True),
    # ``Page 3 / 12`` (slash variant with anchor word).
    (re.compile(
        r"(?P<label>"
        r"Pages?\s+(?P<current>\d{1,4})\s*/\s*(?P<total>\d{1,4})"
        r")",
        re.IGNORECASE,
    ), True),
    # ``Slide 4 of 20`` / ``Slide 4 / 20`` (presentation decks).
    (re.compile(
        r"(?P<label>"
        r"Slides?\s+(?P<current>\d{1,4})\s+(?:of|/)\s*(?P<total>\d{1,4})"
        r")",
        re.IGNORECASE,
    ), True),
    # ``Sheet 3 of 5`` (multi-sheet workbook style).
    (re.compile(
        r"(?P<label>"
        r"Sheets?\s+(?P<current>\d{1,4})\s+(?:of|/)\s*(?P<total>\d{1,4})"
        r")",
        re.IGNORECASE,
    ), True),
    # ``Pg. 12 of 30`` / ``Pg 12 of 30`` (abbreviated form).
    (re.compile(
        r"(?P<label>"
        r"Pg\.?\s+(?P<current>\d{1,4})\s+(?:of|/)\s*(?P<total>\d{1,4})"
        r")",
        re.IGNORECASE,
    ), True),
    # ``p. 7 of 12`` (abbreviated form).
    (re.compile(
        r"(?P<label>"
        r"p\.\s*(?P<current>\d{1,4})\s+(?:of|/)\s*(?P<total>\d{1,4})"
        r")",
        re.IGNORECASE,
    ), True),
    # ``3 / 12`` slash form WITHOUT anchor word. Recognised only
    # when it sits on its own line so a date ``3 / 12 / 2024``
    # or a math fraction ``3 / 12 of pie`` doesn't false-positive.
    # Multiline + anchors required.
    (re.compile(
        r"(?m)^\s*(?P<label>"
        r"(?P<current>\d{1,4})\s*/\s*(?P<total>\d{1,4})"
        r")\s*$",
    ), True),
    # ``Page 1`` / ``Page 12`` bare form.
    (re.compile(
        r"(?P<label>"
        r"Pages?\s+(?P<current>\d{1,4})"
        r")\b(?!\s*(?:of|/|\d))",
        re.IGNORECASE,
    ), False),
    # ``Slide 4`` / ``Slide 12`` bare form.
    (re.compile(
        r"(?P<label>"
        r"Slides?\s+(?P<current>\d{1,4})"
        r")\b(?!\s*(?:of|/|\d))",
        re.IGNORECASE,
    ), False),
    # ``Pg. 12`` / ``pg 12`` abbreviated bare form.
    (re.compile(
        r"(?P<label>"
        r"Pg\.?\s+(?P<current>\d{1,4})"
        r")\b(?!\s*(?:of|/|\d))",
        re.IGNORECASE,
    ), False),
    # ``p. 7`` lowercased abbreviated bare form. The lowercase
    # ``p.`` requires the trailing dot so a sentence ``p ride`` or
    # ``p 5`` reject.
    (re.compile(
        r"(?:^|\s)(?P<label>"
        r"p\.\s*(?P<current>\d{1,4})"
        r")\b(?!\s*(?:of|/|\d))",
    ), False),
    # ``- 5 -`` typography form, used on book / contract pages.
    # Surrounded by hyphens on both sides; sits on its own line.
    (re.compile(
        r"(?m)^\s*(?P<label>"
        r"-\s*(?P<current>\d{1,4})\s*-"
        r")\s*$",
    ), False),
)

# Continuation marker. Detected independently of the page-number
# matcher so a ``(continued)`` notice that sits a line away from
# the page number still tags ``continued=True``.
_CONTINUED_RE = re.compile(
    r"\(\s*continued\s*\)|"
    r"(?:^|\s)continued\s+from\s+(?:previous|prev|page|p\.)|"
    r"(?:^|\s)cont(?:inued)?\.\s*(?:on|from)\s+(?:next|previous|prev)\s+page",
    re.IGNORECASE,
)


def _find_page_info(text: str) -> dict[str, int | str | bool | None] | None:
    """Return page-info dict or None when no page marker present.

    Walks the page-pattern catalogue most-specific-first and
    returns the FIRST matching pattern's result. The continuation
    marker is detected separately and OR'd into the result so a
    page can be tagged ``continued=True`` even when the
    ``(continued)`` text sits a couple of lines away from the
    ``Page N of M`` marker.
    """
    if not text:
        return None
    continued = bool(_CONTINUED_RE.search(text))
    for pat, has_total in _PAGE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        label = m.group("label").strip()
        # Normalise multiple internal spaces.
        label = re.sub(r"\s+", " ", label)
        try:
            current_str = m.group("current")
            current = int(current_str) if current_str else None
        except (IndexError, ValueError):
            current = None
        total: int | None = None
        if has_total:
            try:
                total_str = m.group("total")
                total = int(total_str) if total_str else None
            except (IndexError, ValueError):
                total = None
            # Sanity: total must be >= current; otherwise we likely
            # hit a date-shape false positive (e.g. 12/3 reversed).
            if total is not None and current is not None and total < current:
                continue
        # Reject 0 as current page number (page numbering starts at 1).
        if current is not None and current <= 0:
            continue
        if total is not None and total <= 0:
            total = None
        return {
            "current": current,
            "total": total,
            "label": label,
            "continued": continued,
        }
    # No structured marker found. If only a continuation notice
    # is present, surface that alone with no page numbers.
    if continued:
        m = _CONTINUED_RE.search(text)
        return {
            "current": None,
            "total": None,
            "label": m.group(0).strip() if m else "(continued)",
            "continued": True,
        }
    return None


def enrich_document(existing: DocumentFields | None, ocr: OCRResult) -> DocumentFields:
    """Enrich a DocumentFields object with page-info detection.

    Preserves all caller-supplied fields verbatim. Backfills
    ``page_info`` only when the caller did not supply one.
    """
    text = ocr.text or ""
    parsed_page_info = _find_page_info(text)
    if existing is None:
        return DocumentFields(page_info=parsed_page_info)
    merged = existing.model_copy()
    if merged.page_info is None and parsed_page_info is not None:
        merged.page_info = parsed_page_info
    return merged


__all__ = ["enrich_document", "_find_page_info"]
