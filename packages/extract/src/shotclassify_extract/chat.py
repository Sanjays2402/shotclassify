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


# Hashtag: ``#`` followed by 1+ Unicode-letter / digit / underscore.
# Word-boundary anchored so a literal ``#`` inside a URL fragment
# (``...#frag``) or a Python comment line is not captured. We allow
# digits in the tail but reject a pure-digit tag (``#123``) because
# those are almost always issue numbers, ticket refs, or list markers
# in screenshots — not hashtags.
_HASHTAG_RE = re.compile(r"(?<![\w&])#([A-Za-z_][\w]{0,49})\b")

# Mention: ``@`` followed by 1+ word chars (dot/dash/underscore allowed
# inside, not at the edges). Word-boundary anchored on the LEFT so
# ``foo@bar.com`` (an email) does NOT produce a ``@bar`` mention.
# Rejects bare ``@`` and a single trailing punctuation.
_MENTION_RE = re.compile(r"(?<![\w&.])@([A-Za-z_][A-Za-z0-9_.\-]{0,49})")


# Channel-level mention keywords used by Slack/Discord that we want
# to capture without stripping the ``@`` prefix (they are part of the
# canonical form). We surface them lowercased and include the prefix.
_CHANNEL_MENTIONS = ("@channel", "@here", "@everyone")


# Read / delivered / unread / typing status markers. Each entry
# matches the canonical phrase printed by the major chat platforms.
# Pattern groups: (canonical_status_tag, regex). The regex captures
# an optional trailing timestamp into a ``time`` named group when
# present (iMessage's ``Read 11:14 AM`` shape, WhatsApp's ``Read at
# 11:14``); platforms that omit the time (``Delivered`` on its own
# line) leave the ``time`` group None.
_STATUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # iMessage "Read 11:14 AM" / "Read at 11:14" / "Read yesterday".
    # The time portion is optional so a bare "Read" line still tags.
    ("read", re.compile(
        r"\bRead(?:\s+(?:at|on))?\s*(?P<time>"
        r"\d{1,2}:\d{2}(?:\s*[AaPp]\.?[Mm]\.?)?"
        r"|yesterday|today"
        r")?\b",
    )),
    # iMessage "Delivered" + optional trailing time. Distinct from
    # "Read" so we tag separately.
    ("delivered", re.compile(
        r"\bDelivered(?:\s+(?:at|on))?\s*(?P<time>"
        r"\d{1,2}:\d{2}(?:\s*[AaPp]\.?[Mm]\.?)?"
        r"|yesterday|today"
        r")?\b",
    )),
    # WhatsApp/Telegram "Seen" + optional time. Used in lieu of "Read"
    # by some platforms.
    ("seen", re.compile(
        r"\bSeen(?:\s+(?:at|on))?\s*(?P<time>"
        r"\d{1,2}:\d{2}(?:\s*[AaPp]\.?[Mm]\.?)?"
        r"|yesterday|today)?\b",
    )),
    # "Sent" with optional time. Less common as a status indicator
    # but appears in some platforms (Telegram outgoing badge).
    ("sent", re.compile(
        r"\bSent(?:\s+(?:at|on))?\s*(?P<time>"
        r"\d{1,2}:\d{2}(?:\s*[AaPp]\.?[Mm]\.?)?"
        r")?\b",
    )),
    # Unread count badge: "3 unread messages" / "Unread" / "2 unread".
    # Captures the count (when present) into the ``time`` slot
    # repurposed as ``count`` later -- but the simpler form just
    # tags the unread state.
    ("unread", re.compile(
        r"\b(?:(?P<time>\d+)\s+)?[Uu]nread(?:\s+messages?)?\b",
    )),
    # Typing indicator: "Alice is typing..." / "typing...".
    ("typing", re.compile(
        r"\b(?:[A-Z][\w ]{0,24}\s+is\s+)?[Tt]yping\b(?:\s*\.{0,3})?",
    )),
)


_MAX_STATUSES = 20


def _extract_statuses(text: str) -> list[dict[str, str]]:
    """Return unique status markers found in ``text``.

    Each entry has at minimum a ``status`` key (``read`` /
    ``delivered`` / ``seen`` / ``sent`` / ``unread`` / ``typing``)
    and optionally a ``time`` key when the marker carried a
    trailing time / day. ``parse_timestamp`` normalises the time
    into ``HH:MM`` 24h form when it looks like a clock; non-clock
    times (``yesterday`` / ``today``) are stored verbatim.

    De-duplicates on the (status, time-or-count) pair so a screenshot
    that shows the same "Read 11:14 AM" twice does not bloat the list.
    Preserves first-seen-in-OCR order across all matchers (sorting
    by source-text offset, not by matcher iteration order, so a
    "Delivered" line that appears BEFORE a "Read" line lands first).
    Capped at 20 entries.
    """
    if not text:
        return []
    candidates: list[tuple[int, dict[str, str]]] = []
    for tag, pattern in _STATUS_PATTERNS:
        for m in pattern.finditer(text):
            time_raw = (m.groupdict().get("time") or "").strip()
            entry: dict[str, str] = {"status": tag}
            if time_raw:
                if tag == "unread":
                    # The captured "time" group is actually the unread
                    # count for this pattern. Store as count for
                    # clarity in downstream consumers.
                    entry["count"] = time_raw
                else:
                    # Try to normalise to ``HH:MM`` via parse_timestamp;
                    # fall back to the raw form (``yesterday`` / etc.).
                    normalised = parse_timestamp(time_raw) or time_raw
                    entry["time"] = normalised
            candidates.append((m.start(), entry))
    # Sort by source-text offset so the order matches what a human
    # reading the screenshot top-to-bottom would see, rather than the
    # matcher iteration order.
    candidates.sort(key=lambda x: x[0])
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _, entry in candidates:
        key = (entry["status"], entry.get("time", "") or entry.get("count", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
        if len(out) >= _MAX_STATUSES:
            break
    return out


_MAX_TAGS = 50
_MAX_MENTIONS = 50


def _extract_hashtags(text: str) -> list[str]:
    """Return unique ``#tag`` matches preserving first-seen order.

    Tags are NOT lowercased because case carries meaning on most
    platforms (``#OpenAI`` vs ``#openai``). We compare via the original
    surface form when de-duping. Pure-digit tails (``#123``) are
    rejected at the regex level. Capped at 50.
    """
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _HASHTAG_RE.finditer(text):
        tag = "#" + m.group(1)
        # Reject pure-digit tails defensively (regex requires a leading
        # letter / underscore already, but a future regex change shouldn't
        # be allowed to silently change this).
        body = tag[1:]
        if body.isdigit():
            continue
        if tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
        if len(out) >= _MAX_TAGS:
            break
    return out


def _extract_mentions(text: str) -> list[str]:
    """Return unique ``@user`` mentions preserving first-seen order.

    Includes the canonical channel-level mentions (``@channel``,
    ``@here``, ``@everyone``) up front when present. Trims a single
    trailing ``.`` / ``,`` that survived the regex tail because those
    are almost always sentence punctuation. Capped at 50.
    """
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    low = text.lower()
    for ch in _CHANNEL_MENTIONS:
        if ch in low and ch not in seen:
            seen.add(ch)
            out.append(ch)
    for m in _MENTION_RE.finditer(text):
        mention = "@" + m.group(1)
        # Trim a stray trailing dot / dash from the regex tail.
        while mention.endswith((".", "-", "_")):
            mention = mention[:-1]
        if mention == "@" or mention.lower() in seen:
            continue
        seen.add(mention.lower())
        out.append(mention)
        if len(out) >= _MAX_MENTIONS:
            break
    return out


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
    # Hashtags and mentions: union of caller-supplied + freshly-parsed.
    # We parse against the FULL OCR text (not just the message bodies)
    # so a screenshot header that lists ``#chan @owner`` outside the
    # transcript is still captured. Caller values are preserved
    # verbatim and de-duped case-insensitively for mentions; hashtags
    # keep case because case carries meaning on most platforms.
    seen_tags: set[str] = set()
    hashtags = list(existing.hashtags) if existing else []
    for t in hashtags:
        seen_tags.add(t)
    for t in _extract_hashtags(text):
        if t not in seen_tags:
            seen_tags.add(t)
            hashtags.append(t)

    seen_mentions: set[str] = set()
    mentions = list(existing.mentions) if existing else []
    for m in mentions:
        seen_mentions.add(m.lower())
    for m in _extract_mentions(text):
        if m.lower() not in seen_mentions:
            seen_mentions.add(m.lower())
            mentions.append(m)

    # Status markers (read / delivered / unread / typing / seen / sent)
    # found in the OCR text are merged with any caller-supplied
    # statuses. The merge de-dupes on the (status, time-or-count) key
    # so an LLM-supplied "Read 11:14 AM" plus an OCR-parsed identical
    # marker collapses to one entry. Caller order is preserved first.
    statuses: list[dict[str, str]] = list(existing.statuses) if existing else []
    seen_status: set[tuple[str, str]] = set()
    for s in statuses:
        key = (s.get("status", ""), s.get("time", "") or s.get("count", ""))
        seen_status.add(key)
    for s in _extract_statuses(text):
        key = (s.get("status", ""), s.get("time", "") or s.get("count", ""))
        if key in seen_status:
            continue
        seen_status.add(key)
        statuses.append(s)

    return ChatFields(
        platform=platform,
        participants=participants,
        messages=messages,
        hashtags=hashtags,
        mentions=mentions,
        statuses=statuses,
    )
