"""Cross-category percentage extractor.

Percentages show up across every category of screenshot --
performance dashboards print ``CPU 87%`` / ``Memory 64%``,
sentiment-poll captures show ``Yes 65% No 35%``, financial
captures cite ``+12.5%`` / ``-3.2%`` price moves, code-review
captures show coverage ``Tests passed 98.5%``, marketing receipts
print discount percentages ``20% off``, and battery / progress
indicators all use percent units. Rather than teach each
per-category extractor (or the LLM) to find percent values, we
run :func:`extract_percentages` once on the OCR text and stash the
typed list under ``ExtractedFields.raw["percentages"]`` so
dashboards can overlay sparklines and detect "this capture is
mostly metrics" without per-category coupling.

Output shape: a list of ``{"value", "label", "sign"}`` dicts.

* ``value`` is a float (negative when a leading ``-`` was
  printed, positive otherwise -- a leading ``+`` is captured but
  the value is stored positive because ``+12%`` means up-12, not
  signed-twelve). Out-of-range values (above 1000% or below
  -1000%) are rejected because OCR confuses ``1230`` and
  ``123O``.
* ``label`` is the nearest preceding lowercase context word from
  a curated vocabulary (``cpu`` / ``memory`` / ``disk`` /
  ``battery`` / ``progress`` / ``loading`` / ``loaded`` /
  ``coverage`` / ``passed`` / ``failed`` / ``uptime`` / ``yes`` /
  ``no`` / ``win`` / ``loss`` / ``discount`` / ``off`` / ``up`` /
  ``down`` / ``apr`` / ``apy`` / etc.). ``None`` when no
  recognised context word sits on the same line.
* ``sign`` is ``"+"`` / ``"-"`` / ``None`` -- captures the
  printed direction (so dashboards know ``+12%`` is an up move
  even though we store the magnitude positive).

Recognised shapes:

* **Bare integer**: ``50%`` / ``100%`` / ``0%``
* **Decimal**: ``12.5%`` / ``99.9%`` / ``0.5%`` (US/UK)
  / ``12,5%`` (EU)
* **Signed**: ``+12.5%`` / ``-3.2%`` / ``±5%``
* **Range endpoints** (each captured separately):
  ``5-10%`` / ``5%-10%`` / ``5% to 10%``
* **Context-labelled**: ``CPU 87%`` / ``Battery: 64%`` /
  ``Yes 65%`` / ``Apr 6.5%``

Deliberately NOT matched:

* Bare digit runs without ``%`` suffix (those are captured
  elsewhere -- amounts, identifiers, phones).
* Fractional notation (``1/2`` -- belongs in the per-line
  parser).
* Values above 1000% or below -1000% (almost always OCR noise,
  not a real percent value).

The matcher de-dupes on the ``(value, label, sign)`` triple so a
percent printed twice in the same capture collapses to one entry.
First-seen order is preserved. Capped at 100 entries because a
dashboard screenshot can legitimately show 30+ percentages.
"""
from __future__ import annotations

import re

# Curated context vocabulary -- the lowercase token printed
# immediately before (or as a prefix label for) the percent
# value. Tuned to the kinds of dashboard / poll / code-review
# / receipt screenshots we actually OCR. Add words conservatively
# -- the value alone has plenty of detection power even without
# a context label.
_LABEL_VOCAB: frozenset[str] = frozenset({
    # System metrics
    "cpu", "memory", "mem", "ram", "disk", "swap", "io", "gpu",
    "load", "usage", "used", "free",
    # Network / connectivity
    "uptime", "downtime", "availability", "latency",
    "packet", "bandwidth",
    # Progress / state
    "progress", "loading", "loaded", "complete", "completed",
    "done", "remaining", "pending", "queued",
    # Battery
    "battery", "charge", "charging", "discharge", "power",
    # Test / coverage
    "coverage", "passed", "failed", "skipped", "tested",
    "passing", "failing",
    # Polls / sentiment
    "yes", "no", "agree", "disagree", "maybe", "approval",
    "approve", "reject", "support", "oppose",
    # Finance
    "apr", "apy", "interest", "rate", "yield", "growth",
    "gain", "loss", "return", "returns", "roi", "margin",
    "profit", "revenue",
    # Trading / market
    "up", "down", "change", "delta", "move", "moved",
    # Marketing / promos
    "discount", "off", "save", "saved", "savings", "sale",
    "promo", "cashback", "tip", "tax", "vat", "gst", "hst",
    "service",
    # Engagement / analytics
    "open", "click", "ctr", "conversion", "bounce", "engagement",
    "retention", "churn", "open_rate",
    # Health / fitness
    "heart", "humidity", "alcohol", "fat", "protein", "carbs",
    "sugar", "sodium", "fiber",
    # Win / loss / rank
    "win", "winrate", "lose", "rank", "percentile", "score",
    "accuracy",
    # Generic
    "total", "ratio", "share", "percent", "percentage",
})

# Decimal value pattern accepts US ``12.5`` and EU ``12,5`` styles
# but NOT thousands grouping because percentages above 1000% are
# rejected anyway.
# Sign is captured so we know if the printer wrote ``+12%`` /
# ``-3%`` / ``±5%`` even though we store value positive.
_PCT_RE = re.compile(
    r"(?P<sign>[+\-\u00B1])?(?P<num>\d{1,4}(?:[.,]\d{1,4})?)%",
)

# Range form: ``5-10%`` / ``5%-10%`` / ``5% to 10%`` / ``5 to 10%``.
# We split these and emit each endpoint separately so dashboards
# can render the bounds independently. The matcher LOOKS LIKE the
# bare form when the digits between the two ``%`` boundary form
# a contiguous number.
_RANGE_RE = re.compile(
    r"(?P<lo>\d{1,4}(?:[.,]\d{1,4})?)\s*%?\s*"
    r"(?:-|to|–|—|–)\s*"
    r"(?P<hi>\d{1,4}(?:[.,]\d{1,4})?)\s*%",
    re.IGNORECASE,
)

# Label-before-percent matcher: ``CPU 87%`` / ``Battery: 64%`` /
# ``Coverage: 98.5%`` / ``Yes 65%``. Captures the label so we can
# emit it alongside the value. The separator class deliberately
# omits ``-`` so a leading sign on the value (``Change -3%``) is
# preserved as the sign group instead of being eaten as separator.
_LABELLED_RE = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z_]{0,30})"
    r"[ \t:=]+"
    r"(?P<sign>[+\-\u00B1])?(?P<num>\d{1,4}(?:[.,]\d{1,4})?)%",
)

_MAX_PERCENTAGE_ENTRIES = 100

# Bounds: drop OCR noise that produced unreasonable percent values.
# Real-world percentages stay within ±1000% (10x the base) for the
# vast majority of dashboards. Past that it's almost certainly
# digit-misread or a unit-misclassification.
_MIN_VALUE: float = -1000.0
_MAX_VALUE: float = 1000.0


def _normalise_pct(num: str) -> float | None:
    """Parse a percent magnitude token into a positive float.

    Accepts US (``12.5``) and EU (``12,5``) decimal styles. Returns
    ``None`` on parse failure.
    """
    text = num.replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return value


def _normalise_label(label: str) -> str | None:
    """Return the curated label tag for ``label`` or ``None``."""
    lower = label.lower().strip()
    if lower in _LABEL_VOCAB:
        return lower
    return None


def _line_for(text: str, offset: int) -> str:
    """Return the line of ``text`` containing position ``offset``."""
    line_start = text.rfind("\n", 0, offset) + 1
    line_end = text.find("\n", offset)
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end]


def _label_from_line(text: str, offset: int) -> str | None:
    """Find the nearest preceding label token on the same line.

    Walk backwards through the line containing ``offset`` and return
    the closest token from ``_LABEL_VOCAB``. Returns ``None`` when
    no recognised label sits on the line.
    """
    line_start = text.rfind("\n", 0, offset) + 1
    prefix = text[line_start:offset]
    # Split the prefix into tokens, walk from right to left.
    tokens = re.findall(r"[A-Za-z][A-Za-z_]{0,30}", prefix)
    for tok in reversed(tokens):
        label = _normalise_label(tok)
        if label is not None:
            return label
    return None


def extract_percentages(text: str) -> list[dict]:
    """Return percent values found in ``text``.

    Each entry is a ``{"value": float, "label": str | None,
    "sign": str | None}`` dict. Preserves first-seen order.
    De-dupes on the ``(value, label, sign)`` triple. Capped at
    100 entries.

    Recognises bare ``50%``, decimal ``12.5%`` / EU ``12,5%``,
    signed ``+12.5%`` / ``-3.2%`` / ``±5%``, range endpoints
    ``5-10%`` / ``5% to 10%``, and context-labelled
    ``CPU 87%`` / ``Battery: 64%`` / ``Yes 65%`` shapes.
    """
    if not text or not isinstance(text, str):
        return []
    work = text
    candidates: list[tuple[int, float, str | None, str | None]] = []
    consumed: list[tuple[int, int]] = []  # (start, end) spans claimed

    def _claim(start: int, end: int) -> None:
        consumed.append((start, end))

    def _is_consumed(start: int, end: int) -> bool:
        for cs, ce in consumed:
            # Overlap if the candidate falls inside a claimed span
            # OR shares any position with one.
            if start < ce and end > cs:
                return True
        return False

    # PASS 1: range form ``5-10%`` / ``5% to 10%`` etc. We process
    # ranges FIRST so the inner percent matchers don't steal them
    # asymmetrically (a ``5-10%`` would otherwise yield only ``10%``
    # because the trailing ``%`` is the only one printed).
    for m in _RANGE_RE.finditer(work):
        lo_val = _normalise_pct(m.group("lo"))
        hi_val = _normalise_pct(m.group("hi"))
        if lo_val is None or hi_val is None:
            continue
        if not (_MIN_VALUE <= lo_val <= _MAX_VALUE):
            continue
        if not (_MIN_VALUE <= hi_val <= _MAX_VALUE):
            continue
        start = m.start()
        end = m.end()
        label = _label_from_line(work, start)
        # Emit BOTH endpoints as separate entries.
        candidates.append((start, lo_val, label, None))
        candidates.append((start + 1, hi_val, label, None))
        _claim(start, end)

    # PASS 2: labelled form ``Label: 87%`` -- captures both the
    # value AND the inline label. Skips spans already claimed by
    # the range matcher.
    for m in _LABELLED_RE.finditer(work):
        start = m.start("num")
        end = m.end()
        if _is_consumed(start, end):
            continue
        value = _normalise_pct(m.group("num"))
        if value is None:
            continue
        sign_raw = m.group("sign")
        # If a sign was captured, apply it to the stored value
        # (negative-only -- ``+`` is direction info only).
        signed_value = -value if sign_raw == "-" else value
        if not (_MIN_VALUE <= signed_value <= _MAX_VALUE):
            continue
        label = _normalise_label(m.group("label"))
        if label is None:
            # Fall through to bare matcher to find a preceding
            # label on the same line -- the labelled matcher's
            # prefix may have eaten a non-vocab word like
            # ``HTTP``. Skip so the bare matcher gets it.
            continue
        sign = sign_raw if sign_raw in ("+", "-", "\u00B1") else None
        candidates.append((start, signed_value, label, sign))
        _claim(m.start(), end)

    # PASS 3: bare ``50%`` / signed ``+12%`` / ``-3%`` -- the
    # broadest pattern, runs LAST so labelled and range forms
    # win their spans.
    for m in _PCT_RE.finditer(work):
        start = m.start()
        end = m.end()
        if _is_consumed(start, end):
            continue
        value = _normalise_pct(m.group("num"))
        if value is None:
            continue
        sign_raw = m.group("sign")
        signed_value = -value if sign_raw == "-" else value
        if not (_MIN_VALUE <= signed_value <= _MAX_VALUE):
            continue
        label = _label_from_line(work, start)
        sign = sign_raw if sign_raw in ("+", "-", "\u00B1") else None
        candidates.append((start, signed_value, label, sign))
        _claim(start, end)

    # Sort by source-text offset.
    candidates.sort(key=lambda x: x[0])

    out: list[dict] = []
    seen: set[tuple[float, str | None, str | None]] = set()
    for _start, value, label, sign in candidates:
        key = (value, label, sign)
        if key in seen:
            continue
        seen.add(key)
        out.append({"value": value, "label": label, "sign": sign})
        if len(out) >= _MAX_PERCENTAGE_ENTRIES:
            break
    return out


__all__ = ["extract_percentages"]
