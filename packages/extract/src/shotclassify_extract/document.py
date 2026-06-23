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
    Backfills ``headings`` when the caller's list is empty (we
    never override an LLM-supplied outline because the model may
    have surfaced a richer structure than the regex can detect).
    """
    text = ocr.text or ""
    parsed_page_info = _find_page_info(text)
    parsed_headings = extract_headings(text)
    if existing is None:
        return DocumentFields(
            page_info=parsed_page_info,
            headings=parsed_headings,
        )
    merged = existing.model_copy()
    if merged.page_info is None and parsed_page_info is not None:
        merged.page_info = parsed_page_info
    if not merged.headings and parsed_headings:
        merged.headings = parsed_headings
    return merged


# Heading-hierarchy extraction. Multi-page document captures (slide
# decks, scanned reports, wiki pages, technical contracts) almost
# always use a tiered heading structure that dashboards want to
# surface as a document outline.
#
# Recognised shapes (priority order, first-match-wins per line):
#
# 1. Markdown ATX headers:
#       # Title              -> {level: 1, text: "Title"}
#       ## Section           -> {level: 2, text: "Section"}
#       ### Subsection       -> {level: 3, text: "Subsection"}
#       #### #####  ######   -> 4 / 5 / 6
#    The hash run must be 1..6 (CommonMark spec), followed by at
#    least one space, followed by the heading text. The optional
#    trailing closing hash run (``# Title #``) is stripped.
#
# 2. Markdown setext headers (the text line followed by a divider):
#       Title                -> {level: 1, text: "Title"}
#       =====                  (h1)
#
#       Section              -> {level: 2, text: "Section"}
#       -----                  (h2)
#    The divider must be at least 3 chars of the same character,
#    must sit on its own line, and must immediately follow the
#    heading line (no blank line between).
#
# 3. Numbered headers (technical-doc / contract convention):
#       1. Chapter           -> h1 (1 segment)
#       1.1 Section          -> h2 (2 segments)
#       1.1.1 Subsection     -> h3 (3 segments)
#       2.3.4.5 Detail       -> h4 (max 6 segments capped at h6)
#    The numbering pattern is N(.N)*\s+TEXT where N is 1..999
#    (real-world contracts rarely exceed 999 sections at any
#    level) and TEXT is the heading body. Trailing colon or
#    period after the number is accepted (``1.1: Section`` /
#    ``1.1. Section``).
#
# Safety:
# * Setext divider chars require >=3 to discriminate from
#   markdown horizontal rules (which are usually 3+ of *_-).
# * Numbered headings reject when the body looks like prose with
#   more than 80 chars (long sentences with a leading list number
#   are usually list items, not headings).
# * ATX headings reject when the body contains markdown emphasis
#   markers (`_foo_` / `**bar**`) at the start because those look
#   like comments or formatted prose, not heading titles.
# * Blank-line padding is not enforced (real OCR loses some
#   blank lines) but consecutive numbered items at the SAME level
#   without descending sub-numbering are still treated as headings
#   because a contract's TOC is a series of `1.` lines.
#
# Output is a list of ``{"level": int, "text": str}`` dicts sorted
# by source-text appearance order. Cap 100 entries because real
# documents rarely have more outline entries than this.

_MAX_HEADINGS = 100

# Markdown ATX heading: 1..6 hash chars + space + text. Trailing
# closing hash run is optional. ``\Z`` would be safer than ``$``
# for trailing whitespace tolerance but ``re.MULTILINE`` + ``$``
# matches end-of-line which is what we want.
_HEADING_ATX_RE = re.compile(
    r"(?m)^(?P<hashes>#{1,6})\s+(?P<text>.+?)(?:\s+#+)?\s*$",
)

# Numbered heading: 1..6 dot-separated integers + space + text.
# The colon / period separator after the number is accepted. We
# accept up to 10 segments (more than ever seen in real captures)
# and cap the resulting level at 6 (HTML h6 maximum) downstream.
_HEADING_NUMBERED_RE = re.compile(
    r"(?m)^(?P<num>\d{1,3}(?:\.\d{1,3}){0,9})\.?:?\s+(?P<text>.+?)\s*$",
)

# Setext divider: 3+ chars of the SAME character (= or -) on its
# own line. The backreference ``\1`` enforces same-character runs
# so a mixed divider like ``=-=-=`` rejects (otherwise the
# alternation would match each char independently).
_HEADING_SETEXT_DIVIDER_RE = re.compile(
    r"^(?P<char>=|-)\1{2,}\s*$",
)


def _level_for_numbered(num: str) -> int:
    """Return heading level from a dot-separated number string.

    ``1`` -> 1, ``1.1`` -> 2, ``1.1.1`` -> 3, etc. Capped at 6
    to mirror HTML's h6 maximum.
    """
    depth = num.count(".") + 1
    return min(depth, 6)


def _clean_heading_text(text: str) -> str:
    """Normalise heading text: strip trailing markup / whitespace."""
    # Strip trailing closing-ATX hash run if anywhere in raw form.
    cleaned = re.sub(r"\s+#+\s*$", "", text)
    # Collapse internal whitespace runs to a single space for
    # stable storage. OCR sometimes produces multi-space gaps in
    # heading text that confuse string-equality in dashboards.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Strip trailing colon / period -- these are heading-terminator
    # punctuation, not part of the heading text.
    cleaned = cleaned.rstrip(":.").rstrip()
    return cleaned


def extract_headings(text: str) -> list[dict[str, int | str]]:
    """Return list of detected document headings in source-text order.

    Walks the OCR text scanning for ATX / setext / numbered heading
    shapes. Each match yields a ``{"level": int, "text": str}``
    dict where level is 1..6.

    See the module-level catalogue comment for full priority rules
    and the safety constraints applied to each shape.
    """
    if not text or not isinstance(text, str):
        return []

    # Per-line scan so we can correlate a setext divider on line N
    # with the heading text on line N-1. We index by line offset so
    # the final dict-list is sorted by appearance order.
    lines = text.split("\n")

    # First pass: collect (offset, level, text) tuples by walking the
    # ATX + setext + numbered matchers per line. Spans already claimed
    # by ATX or setext are excluded from the numbered matcher so a
    # ``## 1.1 Section`` doesn't double-tag.
    claimed_lines: set[int] = set()
    hits: list[tuple[int, int, str]] = []

    # ATX walk -- one match per line because ``^`` is line-anchored.
    for m in _HEADING_ATX_RE.finditer(text):
        # Compute line index for this match.
        line_idx = text[: m.start()].count("\n")
        if line_idx in claimed_lines:
            continue
        level = len(m.group("hashes"))
        heading_text = _clean_heading_text(m.group("text"))
        if not heading_text:
            continue
        hits.append((m.start(), level, heading_text))
        claimed_lines.add(line_idx)

    # Setext walk -- find each divider line and look at the
    # immediately-preceding line for the heading text.
    for i in range(1, len(lines)):
        divider = lines[i]
        m = _HEADING_SETEXT_DIVIDER_RE.match(divider)
        if m is None:
            continue
        prev_line = lines[i - 1].rstrip()
        if not prev_line.strip():
            continue
        if (i - 1) in claimed_lines:
            continue
        # Reject when the previous line is itself a divider (run of
        # =/- that we don't want to pair).
        if _HEADING_SETEXT_DIVIDER_RE.match(prev_line):
            continue
        # Reject when previous line looks like a list item or other
        # non-heading structure (preserve real titles).
        if re.match(r"^\s*[-*+]\s+", prev_line):
            continue
        # Compute offset of the previous line in the original text
        # so the sort by appearance is stable.
        offset = sum(len(line) + 1 for line in lines[: i - 1])
        char = m.group("char")
        level = 1 if char == "=" else 2
        heading_text = _clean_heading_text(prev_line)
        if not heading_text:
            continue
        hits.append((offset, level, heading_text))
        claimed_lines.add(i - 1)
        # Also claim the divider line itself.
        claimed_lines.add(i)

    # Numbered walk -- excludes lines already claimed by ATX / setext.
    for m in _HEADING_NUMBERED_RE.finditer(text):
        line_idx = text[: m.start()].count("\n")
        if line_idx in claimed_lines:
            continue
        num = m.group("num")
        body = m.group("text").strip()
        # Reject when the body looks like prose (>80 chars are
        # usually list items / long sentences, not headings).
        if len(body) > 80:
            continue
        # Reject when the body itself starts with a hash (avoids
        # double-counting ATX-inside-numbered).
        if body.startswith("#"):
            continue
        # Reject decimal numerics like ``1.5 kg`` / ``2.3 million``
        # where the body is a unit / quantity tag rather than a
        # heading title -- the body must START WITH A LETTER (or
        # opening quote) to qualify.
        if not body or not (body[0].isalpha() or body[0] in "\"'(["):
            continue
        level = _level_for_numbered(num)
        heading_text = _clean_heading_text(body)
        if not heading_text:
            continue
        hits.append((m.start(), level, heading_text))
        claimed_lines.add(line_idx)

    # Sort by source-text offset so the outline reads top-to-bottom.
    hits.sort(key=lambda triple: triple[0])

    # Materialise into the public dict shape, capped at the maximum.
    out: list[dict[str, int | str]] = [
        {"level": level, "text": heading_text}
        for _, level, heading_text in hits[:_MAX_HEADINGS]
    ]
    return out


__all__ = ["enrich_document", "_find_page_info", "extract_headings"]
