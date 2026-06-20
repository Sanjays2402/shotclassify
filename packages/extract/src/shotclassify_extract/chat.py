"""Chat screenshot extractor."""
from __future__ import annotations

import re

from shotclassify_common import ChatFields, OCRResult

_PLATFORMS = {
    "slack": ["slack", "#general", "@channel"],
    "discord": ["discord"],
    "imessage": ["imessage", "delivered", "read"],
    "whatsapp": ["whatsapp"],
    "telegram": ["telegram"],
    "twitter": ["x.com", "twitter", "retweet"],
}


# Recognised timestamp shapes found in chat screenshots. Each entry is
# (pattern, normalizer). Patterns are anchored with a leading non-word
# context so we never eat a digit out of the middle of a phone number.
# Normalizers turn the matched text into a single canonical form:
#   - bare clock times (``12:34`` / ``12:34 PM``) -> ``HH:MM`` 24h
#     when AM/PM was provided, otherwise the original ``H:MM``.
#   - ISO8601 timestamps -> the original string (trimmed). We do NOT
#     reformat the ISO value because callers downstream may want the
#     timezone the screenshot was taken in.
#
# The list is checked in order, so the most-specific (ISO) wins first.
_ISO_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\b"
)
_CLOCK_AMPM_RE = re.compile(
    r"\b(\d{1,2}):(\d{2})\s*([AaPp])\.?[Mm]\.?\b"
)
_CLOCK_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def _normalize_clock_24h(hour: int, minute: int, ampm: str) -> str:
    """Convert a 12-hour ``H:MM`` + AM/PM marker into ``HH:MM`` 24h.

    AM 12 -> 00, PM 1..11 -> 13..23. PM 12 stays 12. Values outside the
    valid 1..12 range are returned in 24h form unchanged so a garbled
    OCR like ``25:99 PM`` does not crash the caller.
    """
    if not (1 <= hour <= 12) or not (0 <= minute <= 59):
        return f"{hour:02d}:{minute:02d}"
    ampm = ampm.upper()
    h = hour % 12  # 12 -> 0, 1..11 stay
    if ampm == "P":
        h += 12
    return f"{h:02d}:{minute:02d}"


def parse_timestamp(line: str) -> str | None:
    """Return the first chat-style timestamp found in ``line``.

    Recognised shapes:
      * ISO8601 (``2026-01-01T12:34:56Z``, with optional offset/seconds).
      * 12-hour clock with AM/PM marker (``12:34 PM``, ``9:05a.m.``).
      * 24-hour bare clock (``13:42``).

    ISO matches are returned verbatim; AM/PM matches are normalised to
    24h ``HH:MM`` so dashboards can sort them lexicographically.
    Returns ``None`` when no recognisable stamp is in the line.
    """
    if not line:
        return None
    m = _ISO_RE.search(line)
    if m:
        return m.group(1)
    m = _CLOCK_AMPM_RE.search(line)
    if m:
        return _normalize_clock_24h(int(m.group(1)), int(m.group(2)), m.group(3))
    m = _CLOCK_RE.search(line)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        # Reject obvious non-time matches (e.g. "33:33" is not a clock).
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{hh:02d}:{mm:02d}"
    return None


def _strip_timestamp(text: str) -> str:
    """Remove the leading / trailing timestamp so message text stays clean.

    Only strips the first stamp matched by :func:`parse_timestamp` to
    avoid eating a legitimate ``12:34`` that the user typed inside
    their message. Removes a single adjacent dash / pipe separator too
    so a Slack-style ``12:34 — hi there`` collapses to ``hi there``.
    """
    if not text:
        return text
    for pat in (_ISO_RE, _CLOCK_AMPM_RE, _CLOCK_RE):
        m = pat.search(text)
        if not m:
            continue
        s, e = m.span()
        cleaned = (text[:s] + text[e:]).strip()
        # Drop a single separator that was sitting next to the stamp.
        cleaned = re.sub(r"^[\-\u2013\u2014|:\s]+", "", cleaned)
        cleaned = re.sub(r"[\-\u2013\u2014|\s]+$", "", cleaned)
        return cleaned
    return text


def _guess_platform(text: str) -> str | None:
    low = text.lower()
    for name, needles in _PLATFORMS.items():
        if any(n in low for n in needles):
            return name
    return None


def enrich_chat(existing: ChatFields | None, ocr: OCRResult) -> ChatFields:
    text = ocr.text or ""
    platform = (existing.platform if existing and existing.platform else None) or _guess_platform(text)
    participants = list(existing.participants) if existing else []
    if not participants:
        # crude: lines starting with NAME:
        for line in text.splitlines():
            m = re.match(r"^([A-Z][A-Za-z0-9 _\-]{1,24}):\s+\S", line)
            if m:
                name = m.group(1).strip()
                if name not in participants and len(participants) < 6:
                    participants.append(name)
    messages = list(existing.messages) if existing else []
    if not messages:
        for line in text.splitlines():
            m = re.match(r"^([A-Z][A-Za-z0-9 _\-]{1,24}):\s+(.+)$", line)
            if m:
                body = m.group(2).strip()
                ts = parse_timestamp(body)
                msg: dict[str, str] = {"sender": m.group(1).strip()}
                if ts:
                    msg["time"] = ts
                    msg["text"] = _strip_timestamp(body)
                else:
                    msg["text"] = body
                messages.append(msg)
            if len(messages) >= 30:
                break
    else:
        # Backfill ``time`` on caller-supplied messages that lack one
        # but contain a recognisable stamp inside their text. This lets
        # an LLM provide raw lines and still benefit from normalisation.
        for msg in messages:
            if msg.get("time"):
                continue
            body = msg.get("text") or ""
            ts = parse_timestamp(body)
            if ts:
                msg["time"] = ts
                msg["text"] = _strip_timestamp(body)
    return ChatFields(platform=platform, participants=participants, messages=messages)
