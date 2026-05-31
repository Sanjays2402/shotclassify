"""PII redaction for OCR text and extracted fields.

This module is the single source of truth for what counts as PII inside
shotclassify. The :func:`redact_text` helper takes a string and a set of
mode names (``email``, ``phone``, ``ssn``, ``credit_card``, ``ip``,
``iban``) and returns a copy with each match replaced by a typed
placeholder such as ``[REDACTED:email]``. The :func:`redact_fields`
helper walks an arbitrary JSON-shaped value (dict / list / str) and
applies the same rules to every string leaf, which lets the pipeline
sanitize OCR results and extracted structured fields with one call
before any of it is persisted or shipped to an outbound webhook.

The regexes are intentionally conservative: they aim for very low false
positives at the cost of missing exotic formats. A buyer's procurement
review wants to see redaction working on the obvious cases (email,
phone, credit card, SSN) without garbling unrelated text in their
screenshots. Specialist DLP belongs in a dedicated downstream service.

Adding a new mode is two edits: append it to ``_PATTERNS`` here and to
``PII_REDACT_MODES`` in ``shotclassify_store.tenant_settings`` so the
admin UI and the storage allow-list stay in lockstep.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

# Order matters: longer / more specific patterns first so that, for
# example, a credit-card-shaped number is not partially consumed by the
# phone matcher.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "email",
        re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
    ),
    (
        # US SSN: 3-2-4. Reject the obvious invalids (000, 666, 9xx area).
        "ssn",
        re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"),
    ),
    (
        # 13-19 digit runs allowing single spaces or dashes as separators.
        # Followed by a Luhn check below to keep false positives in check.
        "credit_card",
        re.compile(r"\b(?:\d[ -]?){12,18}\d\b"),
    ),
    (
        # IBAN: 2 letters, 2 digits, then 11-30 alphanumerics. Allows a
        # single space every four chars to match how humans paste them.
        "iban",
        re.compile(
            r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}[ ]?[A-Z0-9]{1,4}\b"
        ),
    ),
    (
        # NANP-ish phone: optional +country, then 10 digits separated by
        # space / dash / dot / parens. Requires at least one separator so
        # we do not eat plain integer sequences.
        "phone",
        re.compile(
            r"(?:\+?\d{1,3}[ .-]?)?(?:\(\d{3}\)[ .-]?|\d{3}[ .-])\d{3}[ .-]\d{4}\b"
        ),
    ),
    (
        # IPv4 dotted quad. IPv6 is intentionally omitted: most screenshots
        # do not contain it and the regex bloat is not worth the recall.
        "ip",
        re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"
        ),
    ),
)


def _luhn_ok(digits: str) -> bool:
    """Return True if ``digits`` passes the Luhn checksum."""
    s = 0
    alt = False
    for ch in reversed(digits):
        if not ch.isdigit():
            continue
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        s += d
        alt = not alt
    return s > 0 and s % 10 == 0


def _placeholder(mode: str) -> str:
    return f"[REDACTED:{mode}]"


def _normalize_modes(modes: Iterable[str] | None) -> set[str]:
    if not modes:
        return set()
    return {m.strip().lower() for m in modes if isinstance(m, str) and m.strip()}


def redact_text(text: str, modes: Iterable[str] | None) -> str:
    """Return ``text`` with every PII match for the requested modes redacted.

    Unknown modes are silently ignored so a future caller cannot break the
    pipeline by asking for a mode this build does not yet ship.
    """
    if not text or not isinstance(text, str):
        return text
    active = _normalize_modes(modes)
    if not active:
        return text
    out = text
    for mode, pattern in _PATTERNS:
        if mode not in active:
            continue
        if mode == "credit_card":
            def _sub_cc(m: re.Match[str]) -> str:
                digits = "".join(ch for ch in m.group(0) if ch.isdigit())
                if 13 <= len(digits) <= 19 and _luhn_ok(digits):
                    return _placeholder("credit_card")
                return m.group(0)
            out = pattern.sub(_sub_cc, out)
        else:
            out = pattern.sub(_placeholder(mode), out)
    return out


def redact_fields(value: Any, modes: Iterable[str] | None) -> Any:
    """Recursively redact every string leaf inside ``value``.

    Dicts and lists are walked in place semantics (a new container of the
    same shape is returned). Non-string, non-container leaves are
    returned unchanged so numeric extracted fields like totals or
    confidences are preserved exactly.
    """
    active = _normalize_modes(modes)
    if not active:
        return value
    if isinstance(value, str):
        return redact_text(value, active)
    if isinstance(value, dict):
        return {k: redact_fields(v, active) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_fields(v, active) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_fields(v, active) for v in value)
    return value


__all__ = ["redact_text", "redact_fields"]
