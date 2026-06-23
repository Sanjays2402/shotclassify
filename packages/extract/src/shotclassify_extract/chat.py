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


# Edited-message marker detection. Modern chat platforms append a
# small marker to the body of a message that was modified after
# being sent. The exact phrasing varies by platform:
#
#   * iMessage / generic:       ``(edited)``
#   * WhatsApp:                  ``(edited)``
#   * Discord (with elapsed):    ``(edited 2m)`` / ``(edited 5h)``
#   * Slack (with relative):     ``(edited)`` / ``(edited just now)``
#                                / ``(edited 12 minutes ago)``
#   * Slack web (with stamp):    ``edited at 12:34``
#   * Telegram bots:             ``[edited]``
#   * Some clients (modified):   ``(modified)`` / ``(updated)``
#
# We surface the markers via :func:`_extract_edits`. The output is a
# list of ``{"sender", "text", "tail"}`` dicts; ``sender`` is the
# nearest preceding ``Sender: text`` speaker (or ``None`` for bare
# lines), ``text`` is the message body with the edit marker stripped,
# ``tail`` is the exact captured tail (``edited 2m``) so dashboards
# can render the elapsed time without re-parsing.

_EDIT_TAIL_RE = re.compile(
    r"\s*"
    r"(?:"
    # Parenthesised: (edited) / (edited 2m) / (edited just now) /
    # (edited 12 minutes ago) / (edited 2024-01-01) / (modified) /
    # (updated)
    r"\(\s*(?P<tail_paren>edited(?:[\s,]+[\w\d:\-./ ]{1,40})?"
    r"|modified|updated)\s*\)"
    r"|"
    # Bracketed: [edited]
    r"\[\s*(?P<tail_bracket>edited)\s*\]"
    r"|"
    # Trailing inline: edited at 12:34 / edited 2m ago. Requires a
    # space-separated start so a word boundary protects against
    # picking up substring "edited" inside prose.
    r"(?<=\s)(?P<tail_inline>edited(?:[\s,]+at[\s,]+\d{1,2}:\d{2}"
    r"(?:\s*[AaPp]\.?[Mm]\.?)?|[\s,]+\d+[smhd](?:\s+ago)?))"
    r")"
    r"\s*$",
    re.IGNORECASE,
)


_MAX_EDITS = 30


def _extract_edits(text: str) -> list[dict[str, str]]:
    """Return edit-marker entries found in ``text``.

    Each entry is a ``{"sender", "text", "tail"}`` dict. ``sender``
    is the speaker the message belongs to when extractable from a
    leading ``Sender: text`` pattern on the same line; ``None``
    otherwise (a bare line that just shows the edited body).
    ``text`` is the message body with the edit marker stripped.
    ``tail`` is the matched marker tail (``edited`` / ``edited 2m`` /
    ``modified`` / ``updated``) so dashboards can surface the
    elapsed time without re-parsing.

    Order preserves first-seen-in-OCR-text order. Capped at 30
    entries because a single screenshot rarely shows more than a
    handful of edits.
    """
    if not text:
        return []
    out: list[dict[str, str]] = []
    sender_re = re.compile(r"^(?P<sender>[A-Z][A-Za-z0-9 _\-]{1,24}):\s+(?P<body>.+)$")
    for line in text.splitlines():
        m = _EDIT_TAIL_RE.search(line)
        if not m:
            continue
        tail_raw = (
            m.group("tail_paren")
            or m.group("tail_bracket")
            or m.group("tail_inline")
            or ""
        )
        # Canonical tail form: lowercased, normalised whitespace.
        tail = re.sub(r"\s+", " ", tail_raw.strip().lower())
        body = line[: m.start()].rstrip()
        sender: str | None = None
        sm = sender_re.match(body)
        if sm:
            sender = sm.group("sender").strip()
            body = sm.group("body").strip()
        entry: dict[str, str] = {"text": body, "tail": tail}
        if sender:
            entry["sender"] = sender
        out.append(entry)
        if len(out) >= _MAX_EDITS:
            break
    return out


# Per-message emoji reaction footer detection. Modern chat platforms
# show small reaction counters below a message body. The exact
# format varies:
#
#   * Slack (web/desktop):       ``:eyes: 3   :+1: 2   :tada: 1``
#     (text-form emoji shortcodes followed by a count)
#   * Discord:                    ``👀 3   👍 2   🎉 1``
#     (inline Unicode emoji + count pairs separated by 2+ spaces)
#   * iMessage:                   ``❤️ by Alice`` / ``👍 by Bob``
#     (reaction-by lines from a single user)
#   * WhatsApp:                   ``❤️ 3``
#   * Generic standalone:         ``💯 5``
#
# We surface the matches via :func:`_extract_reactions`. The output
# is a list of ``{"sender", "reactions": [{emoji, count}, ...]}``
# dicts; ``sender`` is the most recent ``Sender:`` speaker preceding
# the reaction line in OCR order (``None`` when no transcript
# speaker is set).

# Slack-style ``:eyes: 3`` shortcode + count.
_SLACK_REACTION_RE = re.compile(
    r"(?P<emoji>:(?:[a-z0-9_+\-]{1,40}):)\s+(?P<count>\d{1,4})\b"
)

# Inline Unicode emoji + count. The emoji is matched as any single
# character outside the BMP plus a small list of BMP emoji code
# points we care about (👍 ❤ 🎉 etc.). We use a permissive Unicode
# range so all common emoji families fire; the digit count must
# follow within a single non-newline space.
_REACTION_EMOJI_RE = re.compile(
    r"(?P<emoji>"
    # Surrogate-pair emoji (non-BMP). Most reaction-worthy emojis sit
    # in U+1F300..U+1FAFF (heart variations, gestures, faces, hands).
    r"[\U0001F300-\U0001FAFF]"
    # BMP emoji + variation selector (heart ❤️ = U+2764 + U+FE0F).
    r"|[\u2600-\u27BF](?:\uFE0F)?"
    r")"
    r"\s+(?P<count>\d{1,4})\b"
)

# iMessage "❤️ by Alice" / "👍 by Bob" reaction-by line.
_REACTION_BY_RE = re.compile(
    r"(?P<emoji>"
    r"[\U0001F300-\U0001FAFF]"
    r"|[\u2600-\u27BF](?:\uFE0F)?"
    r")"
    r"\s+by\s+(?P<who>[A-Z][\w\- ]{1,24})\b"
)


_MAX_REACTIONS_PER_MSG = 20
_MAX_REACTION_ENTRIES = 30


# Replied-to / quoted-message detection. Modern chat platforms
# render a reply by stacking the quoted parent message above the
# new message. Three common shapes:
#
#   * Slack / IRC / email-style: ``> quoted text`` (line-leading
#     ``>`` prefix on the parent body). Multiple consecutive ``>``
#     lines collapse into one quote block. The shape may also carry
#     an attribution header (``> Bob: hi``) where the sender of
#     the parent is preserved.
#   * iMessage / WhatsApp / Telegram: a small inline preview block
#     above the new message body, with the parent's speaker name as
#     a header and the parent body indented below. We detect the
#     ``Replying to <name>: <body>`` / ``In reply to <name>:`` /
#     ``Quoting <name>:`` / ``Reply to <name>:`` shapes.
#   * Discord: ``> @<user> <body>`` inline form (a reply-mention
#     printed inside a single bare quote line).
#
# Output is a list of ``{"sender", "quoted_sender", "quoted_text",
# "reply_text"}`` dicts. ``sender`` is the speaker of the REPLY,
# ``quoted_sender`` is the speaker of the PARENT (None when no
# attribution was printed), ``quoted_text`` is the parent body
# with the quote marker stripped, ``reply_text`` is the new
# message body that follows the quote block (empty string when
# the reply hasn't started yet on the same OCR line).

# Line-leading ``>`` quote marker. We accept one or more leading
# spaces before the ``>`` so Discord's slightly-indented form
# works. The ``>`` MUST be followed by whitespace OR end-of-line
# so a ``->`` arrow or ``=>`` lambda body doesn't false-positive.
# Markdown's autolink ``<https://...>`` is unaffected because the
# ``<`` is the opener, not ``>``.
_QUOTE_LINE_RE = re.compile(r"^[ \t]{0,4}>[ \t]*(?P<body>.*)$")

# ``Replying to <name>: <body>`` / ``In reply to <name>:`` /
# ``Quoting <name>:`` / ``Reply to <name>:`` preamble form used
# by iMessage / WhatsApp / Telegram / Discord. Name is up to 32
# chars of letters / digits / spaces / dots / underscores /
# hyphens / single-quotes; body may be empty (the reply hasn't
# started yet on the same OCR line) or a stripped trailing body.
_REPLYING_TO_RE = re.compile(
    r"^(?P<verb>Replying to|In reply to|Quoting|Reply to)\s+"
    r"(?P<quoted_sender>[A-Za-z][A-Za-z0-9 ._\-']{0,31}?)\s*:\s*"
    r"(?P<body>.*)$",
    re.IGNORECASE,
)

# Slack-style ``> Sender: text`` attribution-inside-quote shape.
# Recognised when the body inside a ``>`` quote line opens with a
# capitalised name + ``:`` + body. Distinct from a bare ``> hi``
# quote line.
_QUOTE_ATTR_RE = re.compile(
    r"^(?P<quoted_sender>[A-Z][A-Za-z0-9 _\-]{1,31}):\s+(?P<body>.+)$"
)

# Discord reply-mention shape: ``> @user body``. The ``@user``
# token sits inside the ``>`` line. We pull the mention as the
# quoted_sender (without the ``@``) so downstream consumers can
# join against ChatFields.mentions.
_DISCORD_REPLY_RE = re.compile(
    r"^@(?P<quoted_sender>[A-Za-z_][A-Za-z0-9_.\-]{0,49})\s+(?P<body>.+)$"
)


_MAX_QUOTES = 20


def _extract_quotes(text: str) -> list[dict[str, str]]:
    """Return reply / quote blocks found in ``text``.

    Each entry is a ``{"sender", "quoted_sender", "quoted_text",
    "reply_text"}`` dict. Order preserves first-seen-in-OCR-text
    order. Capped at 20 entries.

    Three shapes are recognised:
      * Line-leading ``>`` quote runs (Slack / IRC / email /
        Discord). Consecutive ``>`` lines collapse into one
        ``quoted_text`` body joined by newlines.
      * ``Replying to <name>:`` preambles (iMessage / WhatsApp /
        Telegram / Discord). The body after the ``:`` (when
        present) is the parent body; the FOLLOWING non-empty
        line is the reply body.
      * ``> Sender: text`` attribution-inside-quote shapes
        (Slack quoted-with-attribution).
    """
    if not text:
        return []
    out: list[dict[str, str]] = []
    sender_re = re.compile(r"^(?P<sender>[A-Z][A-Za-z0-9 _\-]{1,24}):\s+\S")
    lines = text.splitlines()
    current_sender: str | None = None
    i = 0
    while i < len(lines) and len(out) < _MAX_QUOTES:
        line = lines[i]
        # Replying to <name>: <body> preamble form -- check FIRST so
        # the sender_re below doesn't mistake "Replying to Alice" as
        # a transcript speaker named "Replying to Alice".
        rm = _REPLYING_TO_RE.match(line.strip())
        if rm:
            quoted_sender = rm.group("quoted_sender").strip() or None
            quoted_body = rm.group("body").strip()
            # Walk forward to find the reply body (the next
            # non-empty, non-quote-marker line that isn't another
            # preamble). Skip blank lines.
            reply_body = ""
            j = i + 1
            while j < len(lines):
                nxt = lines[j].strip()
                if not nxt:
                    j += 1
                    continue
                if _QUOTE_LINE_RE.match(lines[j]):
                    # Reply body hasn't started -- skip past any
                    # additional quoted lines that follow the
                    # preamble.
                    j += 1
                    continue
                if _REPLYING_TO_RE.match(nxt):
                    # Another reply chain immediately follows; the
                    # current reply has no body.
                    break
                # Strip a leading Sender: prefix from the reply
                # body so the reply_text doesn't double up the
                # speaker name (we already track sender separately).
                sm2 = sender_re.match(lines[j])
                if sm2:
                    reply_body = lines[j][sm2.end() - 1:].strip()
                else:
                    reply_body = nxt
                break
            entry = {
                "quoted_text": quoted_body,
                "reply_text": reply_body,
            }
            if current_sender:
                entry["sender"] = current_sender
            if quoted_sender:
                entry["quoted_sender"] = quoted_sender
            out.append(entry)
            i += 1
            continue
        # Track the current speaker so a `>` block landing inside
        # a transcript gets attributed to the right reply author.
        sm = sender_re.match(line)
        if sm:
            current_sender = sm.group("sender").strip()
            # The same line may carry a body that's just text; we
            # still advance past it normally below.
        # Line-leading `>` quote run (Slack / IRC / email / Discord).
        qm = _QUOTE_LINE_RE.match(line)
        if qm:
            body_first = qm.group("body").strip()
            # Check for `> @user body` Discord reply-mention form.
            dm = _DISCORD_REPLY_RE.match(body_first)
            if dm:
                quoted_sender = dm.group("quoted_sender").strip()
                quoted_body = dm.group("body").strip()
                bodies = [quoted_body] if quoted_body else []
            else:
                # Check for `> Sender: text` attribution form.
                am = _QUOTE_ATTR_RE.match(body_first)
                if am:
                    quoted_sender = am.group("quoted_sender").strip()
                    bodies = [am.group("body").strip()]
                else:
                    quoted_sender = None
                    bodies = [body_first] if body_first else []
            # Collapse consecutive `>` lines into one quote block.
            j = i + 1
            while j < len(lines):
                nm = _QUOTE_LINE_RE.match(lines[j])
                if not nm:
                    break
                nb = nm.group("body").strip()
                if nb:
                    bodies.append(nb)
                else:
                    # A blank `>` line terminates the quote block
                    # (Slack convention: an empty quoted line marks
                    # the end of the quoted preamble).
                    j += 1
                    break
                j += 1
            quoted_text = "\n".join(bodies).strip()
            # Find the reply body on the next non-empty non-quote
            # non-preamble line. Strip a leading Sender: prefix.
            # A subsequent ``>`` line is treated as a NEW quote
            # block (not skipped), because consecutive `>` runs
            # separated by a blank line are distinct quotes.
            reply_body = ""
            k = j
            while k < len(lines):
                nxt = lines[k].strip()
                if not nxt:
                    k += 1
                    continue
                if _QUOTE_LINE_RE.match(lines[k]):
                    # Another `>` block starts here -- no reply
                    # body for the current quote.
                    break
                if _REPLYING_TO_RE.match(nxt):
                    break
                sm2 = sender_re.match(lines[k])
                if sm2:
                    reply_body = lines[k][sm2.end() - 1:].strip()
                else:
                    reply_body = nxt
                break
            # Skip bare prompt-character lines that produced no
            # quoted body (just a stray `>`). We require at least
            # one non-empty quoted body to count as a quote block.
            if not quoted_text:
                i = j
                continue
            entry = {
                "quoted_text": quoted_text,
                "reply_text": reply_body,
            }
            if current_sender:
                entry["sender"] = current_sender
            if quoted_sender:
                entry["quoted_sender"] = quoted_sender
            out.append(entry)
            i = j
            continue
        i += 1
    return out


def _strip_quote_lines(text: str) -> str:
    """Return ``text`` with line-leading ``>`` quote markers stripped.

    Used by message-parsing helpers that want the body without the
    quote prefix (so the speaker's actual reply lands in
    ChatFields.messages rather than the quoted parent).
    """
    out_lines: list[str] = []
    for ln in text.splitlines():
        m = _QUOTE_LINE_RE.match(ln)
        if m:
            # Drop the quote marker line entirely; the reply body
            # (the next non-quote line) will land in the output.
            continue
        out_lines.append(ln)
    return "\n".join(out_lines)


# Attachment marker detection. Modern chat platforms render
# attachments as a small bracketed token or emoji-prefixed label
# in place of the message body. Recognised shapes:
#
#   * WhatsApp / iMessage bracketed: ``[Image]`` / ``[Video]`` /
#     ``[Voice note 0:23]`` / ``[Sticker]`` / ``[Document]`` /
#     ``[GIF]`` / ``[Location]`` / ``[Contact]``
#   * Telegram emoji-prefixed: ``📷 Photo`` / ``🎥 Video`` /
#     ``🎤 Voice (0:42)`` / ``📎 Document`` / ``📍 Location``
#   * Slack inline: ``📎 Attached file: <name>``
#   * Generic English: ``Voice message (0:42)`` / ``Photo`` /
#     ``Video call · 1m 23s`` / ``Missed video call``
#
# Output is a list of ``{sender, kind, duration?, name?}`` dicts.

# Canonical attachment-type tags. ``kind`` values stay lowercase
# so dashboards can switch on a fixed enum-like vocabulary
# without normalisation gymnastics.
_ATTACH_KIND_ALIASES: dict[str, str] = {
    # Image
    "image": "image",
    "photo": "image",
    "picture": "image",
    "img": "image",
    # Video
    "video": "video",
    "vid": "video",
    "movie": "video",
    # Voice / audio
    "voice": "voice",
    "voice note": "voice",
    "voice message": "voice",
    "audio note": "voice",
    "voice memo": "voice",
    "audio": "audio",
    "audio message": "audio",
    "music": "audio",
    # Document / file
    "document": "document",
    "doc": "document",
    "file": "document",
    "pdf": "document",
    # Sticker / GIF
    "sticker": "sticker",
    "gif": "gif",
    "animated gif": "gif",
    # Location / contact
    "location": "location",
    "live location": "location",
    "contact": "contact",
    "contact card": "contact",
    # Calls
    "video call": "video_call",
    "missed video call": "video_call",
    "audio call": "audio_call",
    "voice call": "audio_call",
    "missed audio call": "audio_call",
    "missed voice call": "audio_call",
    "missed call": "audio_call",
}

# Bracketed shape: [Image] / [Voice note 0:23] / [Voice note (0:23)]
# / [Document: file.pdf] / [Photo]. The captured label is
# lower-cased + normalised before lookup against
# _ATTACH_KIND_ALIASES. Brackets are required around the entire
# token so prose with [issue-id] doesn't false-positive (the
# captured text is checked against the alias map, so unknown
# bracketed labels are rejected).
_BRACKET_ATTACH_RE = re.compile(
    r"\[\s*(?P<label>[A-Za-z][A-Za-z ]{0,28})"
    r"(?:\s*[:\-]?\s*(?P<duration>\d{1,2}:\d{2}(?::\d{2})?))?"
    r"(?:\s*[:\-]\s*(?P<name>[^\]]{1,80}))?"
    r"\s*\]"
)

# Emoji-prefixed shape: 📷 Photo / 🎤 Voice (0:42) / 📎 Document /
# 🎥 Video. The emoji catalogue is a small curated set so we
# don't false-positive on every leading emoji.
_ATTACH_EMOJI = (
    "📷", "📸", "🖼", "🖼️",      # photo / image
    "🎥", "📹", "📽", "📽️",      # video
    "🎤", "🎙", "🎙️", "🗣",      # voice
    "🎵", "🎶", "🔊",              # audio / music
    "📎", "📄", "📑", "📋",      # document
    "📍", "🗺", "🗺️",            # location
    "👤", "📇",                    # contact
    "💬",                          # sticker (Telegram convention)
    "🎬",                          # GIF
)
_EMOJI_ATTACH_RE = re.compile(
    r"(?P<emoji>"
    + "|".join(re.escape(e) for e in _ATTACH_EMOJI)
    + r")\s+"
    r"(?P<label>[A-Za-z][A-Za-z ]{0,28}?)"
    r"(?:\s*\(\s*(?P<duration>\d{1,2}:\d{2}(?::\d{2})?)\s*\))?"
    r"(?:\s*[:\-]\s*(?P<name>[^\n]{1,80}))?"
    r"(?=\s|$|[.,;:])"
)

# Standalone duration suffix for `(0:42)` / `(1:23)` / `(3:12:45)`
# parens. Used by the bracket and emoji shapes' duration groups
# above; documented here for clarity.

# Generic English shape: ``Voice message (0:42)`` / ``Video call ·
# 1m 23s`` / ``Missed video call`` / ``Voice memo - 0:30``. Must
# sit on its own (line-bounded) so prose like "I voiced my opinion"
# doesn't fire. The label MUST appear in the alias catalogue --
# we reject unknown bare-English labels because the false-positive
# surface is too large.
_ENGLISH_ATTACH_RE = re.compile(
    r"^\s*(?P<label>"
    r"Missed video call|Missed audio call|Missed voice call|Missed call|"
    r"Video call|Audio call|Voice call|Voice message|Voice note|"
    r"Voice memo|Audio message|Photo|Image|Picture|Video|Sticker|GIF|"
    r"Location|Live Location|Contact|Document|Attached file)\b"
    r"(?:\s*[·\-]\s*(?P<duration>\d{1,2}(?::\d{2}){1,2}|\d+m(?:\s*\d+s)?|\d+s))?"
    r"(?:\s*\(\s*(?P<duration2>\d{1,2}:\d{2}(?::\d{2})?)\s*\))?"
    r"(?:\s*[:\-]\s*(?P<name>[^\n]{1,80}))?"
    r"\s*$",
    re.IGNORECASE,
)


_MAX_ATTACHMENTS = 30


def _kind_for(label: str) -> str | None:
    """Return the canonical attachment kind for ``label`` or None."""
    if not label:
        return None
    key = re.sub(r"\s+", " ", label.strip().lower())
    if key in _ATTACH_KIND_ALIASES:
        return _ATTACH_KIND_ALIASES[key]
    # Allow "Voice note" / "Voice memo" / etc multi-word forms.
    # We already canonicalised them in the alias map above; this
    # branch is a no-op safety net.
    return None


def _extract_attachments(text: str) -> list[dict[str, str | None]]:
    """Return attachment-marker entries found in ``text``.

    Each entry is a ``{sender, kind, duration?, name?}`` dict.
    ``sender`` is the speaker the attachment belongs to (the
    nearest preceding ``Sender:`` line) or ``None`` when no
    transcript context surrounds the marker.

    Order preserves first-seen-in-OCR-text offset (across all
    matchers). De-dupes on the (sender, kind, duration, name)
    tuple so the same WhatsApp ``[Image]`` printed twice
    collapses to one entry. Capped at 30 entries.
    """
    if not text:
        return []
    sender_re = re.compile(r"^(?P<sender>[A-Z][A-Za-z0-9 _\-]{1,24}):\s+\S")

    # Build a per-line sender map so each match's sender can be
    # looked up by source-text offset without walking the whole
    # transcript every time.
    line_starts: list[int] = []
    pos = 0
    for ln in text.splitlines(keepends=True):
        line_starts.append(pos)
        pos += len(ln)
    sender_at_line: list[str | None] = []
    current: str | None = None
    for _idx, ln in enumerate(text.splitlines()):
        sm = sender_re.match(ln)
        if sm:
            current = sm.group("sender").strip()
        sender_at_line.append(current)

    def _sender_for(offset: int) -> str | None:
        # Binary-search-lite: walk until the next line_start exceeds.
        for i, _start in enumerate(line_starts):
            if i + 1 == len(line_starts) or line_starts[i + 1] > offset:
                return sender_at_line[i] if i < len(sender_at_line) else None
        return None

    candidates: list[tuple[int, int, dict[str, str | None]]] = []

    # Bracket shape -- run FIRST so emoji-prefixed bracketed
    # variants ([📷 Image]) don't double-tag.
    for m in _BRACKET_ATTACH_RE.finditer(text):
        label = m.group("label").strip()
        kind = _kind_for(label)
        if kind is None:
            continue
        duration = (m.group("duration") or "").strip() or None
        name = (m.group("name") or "").strip() or None
        # If the label captured a multi-word like "Voice note" and
        # the duration was actually inside the same label slot
        # (e.g. "[Voice note 0:23]"), the regex's duration group
        # already pulled it out -- nothing more to do.
        entry: dict[str, str | None] = {"kind": kind}
        if duration:
            entry["duration"] = duration
        if name:
            entry["name"] = name
        sender = _sender_for(m.start())
        if sender:
            entry["sender"] = sender
        candidates.append((m.start(), m.end(), entry))

    # Emoji-prefixed shape -- run SECOND so a bracketed match's
    # span is preserved.
    for m in _EMOJI_ATTACH_RE.finditer(text):
        label = m.group("label").strip()
        kind = _kind_for(label)
        if kind is None:
            continue
        # Skip if this emoji-prefix match overlaps any bracketed
        # match already recorded (bracket wins, no double-tag).
        overlap = any(s <= m.start() < e for s, e, _ in candidates)
        if overlap:
            continue
        duration = (m.group("duration") or "").strip() or None
        name = (m.group("name") or "").strip() or None
        entry = {"kind": kind}
        if duration:
            entry["duration"] = duration
        if name:
            entry["name"] = name
        sender = _sender_for(m.start())
        if sender:
            entry["sender"] = sender
        candidates.append((m.start(), m.end(), entry))

    # Generic English shape -- per-line scan because the regex is
    # line-anchored. We strip any leading ``Sender: `` transcript
    # prefix before matching so a transcript-attached attachment
    # line still tags.
    for idx, ln in enumerate(text.splitlines()):
        # Strip a leading "Sender: " prefix so the English regex's
        # ^ anchor still triggers on transcript-attached lines.
        stripped_offset = 0
        scan_ln = ln
        smp = sender_re.match(ln)
        if smp:
            scan_ln = ln[smp.end() - 1:].lstrip()
            stripped_offset = len(ln) - len(scan_ln)
        m = _ENGLISH_ATTACH_RE.match(scan_ln)
        if not m:
            continue
        label = m.group("label").strip()
        kind = _kind_for(label)
        if kind is None:
            continue
        offset = line_starts[idx] + stripped_offset
        end_offset = offset + (m.end() - m.start())
        # Skip if this English-shape match overlaps with an
        # already-recorded match span.
        overlap = any(
            s <= offset < e or s < end_offset <= e
            for s, e, _ in candidates
        )
        if overlap:
            continue
        duration = (
            (m.group("duration") or "").strip()
            or (m.group("duration2") or "").strip()
            or None
        )
        name = (m.group("name") or "").strip() or None
        entry = {"kind": kind}
        if duration:
            entry["duration"] = duration
        if name:
            entry["name"] = name
        sender = _sender_for(offset)
        if sender:
            entry["sender"] = sender
        candidates.append((offset, end_offset, entry))

    # Sort by source-text offset so the order matches what a human
    # reading the screenshot top-to-bottom would see.
    candidates.sort(key=lambda x: x[0])

    out: list[dict[str, str | None]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for _, _, entry in candidates:
        key = (
            entry.get("sender") or "",
            entry.get("kind") or "",
            entry.get("duration") or "",
            entry.get("name") or "",
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
        if len(out) >= _MAX_ATTACHMENTS:
            break
    return out


def _is_reaction_line(line: str) -> bool:
    """Return True when ``line`` looks like a reaction footer.

    A reaction footer is a line where the bulk of the content is
    emoji + count pairs (Slack shortcodes, Discord inline) -- not a
    regular message body that happens to contain an emoji.

    Heuristic: the line yields at least one (emoji, count) match AND
    the matches collectively account for the majority of the line's
    non-whitespace content (>50%).
    """
    if not line.strip():
        return False
    matches = list(_SLACK_REACTION_RE.finditer(line)) + list(_REACTION_EMOJI_RE.finditer(line))
    if not matches:
        return False
    matched_chars = sum(m.end() - m.start() for m in matches)
    total_nonspace = sum(1 for ch in line if not ch.isspace())
    if total_nonspace == 0:
        return False
    return matched_chars / max(total_nonspace, 1) >= 0.3


def _extract_reactions(text: str) -> list[dict]:
    """Return per-message reaction footers found in ``text``.

    Each entry is a ``{"sender", "reactions": [{emoji, count}, ...]}``
    dict; ``sender`` is the most-recent ``Sender:`` speaker
    preceding the reaction line in OCR order (or ``None`` when no
    transcript speaker is set).

    De-dupes on the (sender, emoji) pair within a message group --
    a Slack post that lists ``:eyes: 3 :eyes: 3`` (rare but possible)
    collapses to one entry. Preserves first-seen-in-OCR order.
    Capped at 30 entries with at most 20 reactions per message.
    """
    if not text:
        return []
    sender_re = re.compile(r"^(?P<sender>[A-Z][A-Za-z0-9 _\-]{1,24}):\s+\S")
    out: list[dict] = []
    current_sender: str | None = None
    for line in text.splitlines():
        sm = sender_re.match(line)
        if sm:
            current_sender = sm.group("sender").strip()
            # The body may still contain reactions if a single line
            # combines sender + body + reactions; for simplicity we
            # do NOT scan the body here -- only standalone reaction
            # lines count as a reaction footer.
            continue
        # iMessage-style "❤️ by Alice" reaction-by line is treated
        # as a one-reaction entry attributed to Alice (the reactor),
        # not the current_sender.
        by_matches = list(_REACTION_BY_RE.finditer(line))
        if by_matches:
            reactions: list[dict] = []
            seen_emoji: set[str] = set()
            who_for_entry: str | None = None
            for bm in by_matches:
                emoji = bm.group("emoji")
                if emoji in seen_emoji:
                    continue
                seen_emoji.add(emoji)
                if who_for_entry is None:
                    who_for_entry = bm.group("who").strip()
                reactions.append({"emoji": emoji, "count": 1})
                if len(reactions) >= _MAX_REACTIONS_PER_MSG:
                    break
            entry: dict = {"reactions": reactions}
            entry["sender"] = who_for_entry
            out.append(entry)
            if len(out) >= _MAX_REACTION_ENTRIES:
                break
            continue
        # Regular emoji + count reaction footer.
        if not _is_reaction_line(line):
            continue
        reactions = []
        seen_emoji = set()
        # Slack-style shortcodes first.
        for sm2 in _SLACK_REACTION_RE.finditer(line):
            emoji = sm2.group("emoji")
            if emoji in seen_emoji:
                continue
            seen_emoji.add(emoji)
            try:
                count = int(sm2.group("count"))
            except (TypeError, ValueError):
                continue
            reactions.append({"emoji": emoji, "count": count})
            if len(reactions) >= _MAX_REACTIONS_PER_MSG:
                break
        for em in _REACTION_EMOJI_RE.finditer(line):
            emoji = em.group("emoji")
            if emoji in seen_emoji:
                continue
            seen_emoji.add(emoji)
            try:
                count = int(em.group("count"))
            except (TypeError, ValueError):
                continue
            reactions.append({"emoji": emoji, "count": count})
            if len(reactions) >= _MAX_REACTIONS_PER_MSG:
                break
        if not reactions:
            continue
        entry = {"reactions": reactions}
        entry["sender"] = current_sender
        out.append(entry)
        if len(out) >= _MAX_REACTION_ENTRIES:
            break
    return out


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


# Poll / survey block detection. Modern chat platforms (Telegram,
# Slack, Discord, Teams, WhatsApp) render an inline poll as a
# header line introducing the poll question followed by per-option
# vote-count rows. The exact format varies:
#
#   Telegram (most common shape):
#     📊 Poll: What's for lunch?
#     Option 1: Pizza - 5 votes
#     Option 2: Sushi - 3 votes
#
#   Slack (with bar chart):
#     :bar_chart: Poll: Friday demo time?
#     1. 10am  ▓▓▓▓▓ 5
#     2. 2pm   ▓▓▓ 3
#
#   Discord (bullets):
#     📊 What's the best deploy strategy?
#     • Rolling: 12 votes
#     • Blue/green: 8 votes
#
# Output is a list of {"question", "options": [{label, votes}, ...]}
# dicts. We surface the QUESTION header text and the per-option
# label + vote count.

# Header regex: matches a line that introduces a poll. Accepts
# emoji-prefixed (📊 / 📈 / 📉 / 📋), Slack shortcode (:bar_chart: /
# :chart_with_upwards_trend: / :poll:), or keyword-prefixed
# (Poll: / Survey: / Vote: / Question:) variants. The question
# text follows; for the keyword form a trailing ``?`` is optional
# (Telegram's poll prompts always end in ``?`` but other platforms
# allow declarative prompts).
_POLL_HEADER_RE = re.compile(
    r"^\s*"
    # Optional emoji or shortcode prefix
    r"(?:"
    r"(?P<emoji>[\U0001F300-\U0001F9FF]|:bar_chart:|:chart_with_upwards_trend:"
    r"|:chart_with_downwards_trend:|:poll:|:question:|:clipboard:)"
    r"\s*"
    r")?"
    # Optional keyword prefix (one of: Poll, Survey, Vote, Question, Quiz)
    r"(?:(?P<keyword>Poll|Survey|Vote|Question|Quiz)\s*:\s*)?"
    # The actual question text. We require either:
    # (a) a keyword OR emoji prefix was matched, AND there's at
    #     least one word of question text, OR
    # (b) bare prose ending in ``?`` after the emoji prefix.
    r"(?P<question>\S.*\S|\S)\s*$",
)


# Option line regex: numbered / bulleted / progress-bar shape with
# vote count. The vote count is the LAST integer on the line OR
# the integer immediately before/after a ``vote(s)`` keyword.
#
# Recognised shapes:
#   1. Pizza - 5 votes
#   1) Pizza 5
#   Option 1: Pizza - 5 votes
#   • Pizza: 5 votes
#   - Pizza - 5 votes
#   * Pizza (5)
#   Pizza ▓▓▓▓▓ 5
#   Pizza: 5 votes
#   Pizza - 5 votes (50%)
#
# We split into two patterns:
#  (1) explicit "N votes" / "N vote" trailing form
#  (2) any structured prefix (number/bullet) with a trailing integer
_POLL_OPTION_WITH_KEYWORD_RE = re.compile(
    r"^\s*"
    # Optional bullet / number prefix
    r"(?:"
    r"(?:[\u2022\u25CF\u25E6*\-+])\s+"   # bullet
    r"|(?:Option\s+\d+|\d+)[.):\s]\s*"   # "Option 1:" or "1." or "1)"
    r")?"
    # Label: anything reasonable up to the vote count.
    # We grab a non-greedy chunk, then require an integer + ``vote(s)``.
    r"(?P<label>\S.{0,80}?)"
    r"\s*(?:[\-:\u2014\u2013\u2192]|(?:\s+))\s*"
    r"(?:\u25b3\u25b3\u25b3|[\u2588\u2589\u258A\u258B\u258C\u258D\u258E\u258F\u2592\u2593]*\s*)?"
    r"(?P<votes>\d{1,5})\s*"
    r"(?:votes?)\b"
    r".*$",
    re.IGNORECASE,
)

_POLL_OPTION_BARE_NUMBER_RE = re.compile(
    r"^\s*"
    # Required structured prefix: bullet, number-with-separator, or "Option N:"
    r"(?:"
    r"(?:[\u2022\u25CF\u25E6*])\s+"
    r"|(?:Option\s+\d+)\s*[:.\)]\s*"
    r"|\d+\s*[.\)]\s+"
    r"|[\-+]\s+"
    r")"
    # Label
    r"(?P<label>\S.{0,80}?)"
    r"\s*[\-:\u2014\u2013\u2192]?\s*"
    # Optional progress-bar visual
    r"(?:[\u2588\u2589\u258A\u258B\u258C\u258D\u258E\u258F\u2592\u2593]+\s*)?"
    # Trailing integer (the vote count)
    r"(?P<votes>\d{1,5})\s*"
    # Optional percent suffix
    r"(?:\(\s*\d{1,3}%?\s*\))?"
    r"\s*$"
)


_MAX_POLLS = 10
_MAX_POLL_OPTIONS = 20


def _clean_poll_question(raw: str, keyword: str | None) -> str:
    """Strip trailing punctuation noise and normalise whitespace."""
    text = re.sub(r"\s+", " ", raw.strip())
    # If a keyword was already matched, the regex stripped it. Otherwise
    # the question may still carry a leading "Poll:" / "Survey:" that
    # our emoji-only branch left in.
    if not keyword:
        for kw in ("Poll:", "Survey:", "Vote:", "Question:", "Quiz:"):
            if text.lower().startswith(kw.lower()):
                text = text[len(kw):].strip()
                break
    return text


def _clean_option_label(raw: str) -> str:
    """Strip trailing dash/colon/whitespace from an option label."""
    text = re.sub(r"\s+", " ", raw.strip())
    # Strip trailing punctuation that belongs to the separator, not the label.
    text = text.rstrip(":-\u2014\u2013\u2192 ")
    return text


def _extract_polls(text: str) -> list[dict]:
    """Return poll / survey blocks found in ``text``.

    Each entry is a ``{"question": str, "options": list[dict]}`` dict
    where each option is a ``{"label": str, "votes": int}`` dict.

    Detection requires BOTH a recognised header (emoji-prefixed or
    keyword-prefixed) AND at least 2 option lines that include vote
    counts. A header with no following options is rejected as just
    a regular message; a numbered list with no header is rejected
    as a regular list.

    Order preserves first-seen-in-OCR-text order. Capped at 10
    polls per screenshot; each poll capped at 20 options.
    """
    if not text:
        return []
    lines = text.splitlines()
    n = len(lines)
    out: list[dict] = []
    i = 0
    while i < n and len(out) < _MAX_POLLS:
        ln = lines[i]
        hm = _POLL_HEADER_RE.match(ln)
        # Header requires either an emoji prefix OR a keyword prefix
        # to qualify -- bare prose lines shouldn't false-positive.
        if not hm or (not hm.group("emoji") and not hm.group("keyword")):
            i += 1
            continue
        question = _clean_poll_question(hm.group("question"), hm.group("keyword"))
        if not question:
            i += 1
            continue
        # Walk forward collecting option lines. We stop at the first
        # blank line, the first line that doesn't look like an option,
        # or after we've collected 20 options.
        options: list[dict] = []
        j = i + 1
        while j < n and len(options) < _MAX_POLL_OPTIONS:
            opt_line = lines[j]
            stripped = opt_line.strip()
            if not stripped:
                # Allow one blank line inside the poll; bail if two in a row.
                if j + 1 < n and not lines[j + 1].strip():
                    break
                j += 1
                continue
            # Skip footer lines like "16 voters" / "Final results" etc.
            if re.match(
                r"^\s*(?:\d+\s+voters?|Final\s+results?|Total\s+votes?\s*:|"
                r"Anonymous\s+poll|Poll\s+closed)\b",
                stripped,
                re.IGNORECASE,
            ):
                j += 1
                continue
            # Try keyword form first (more reliable when "votes" is present).
            om = _POLL_OPTION_WITH_KEYWORD_RE.match(stripped)
            if not om:
                # Try bare-number form (requires structured prefix).
                om = _POLL_OPTION_BARE_NUMBER_RE.match(stripped)
            if not om:
                # Not an option line -- end of this poll's options.
                break
            label = _clean_option_label(om.group("label"))
            try:
                votes = int(om.group("votes"))
            except (ValueError, TypeError):
                break
            if not label:
                break
            options.append({"label": label, "votes": votes})
            j += 1
        # Require at least 2 options to register as a real poll;
        # a single option is just a regular message about voting.
        if len(options) >= 2:
            out.append({"question": question, "options": options})
            i = j  # Skip past the options we consumed.
        else:
            i += 1
    return out


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

    # Edited-message markers ((edited) / (edited 2m) / etc.) merged
    # with any caller-supplied edits. De-dupes on the (sender, text,
    # tail) triple so an LLM-supplied edit plus the OCR-parsed
    # identical edit collapses to one entry. Caller order preserved
    # first.
    edits: list[dict[str, str]] = list(existing.edits) if existing else []
    seen_edits: set[tuple[str, str, str]] = set()
    for e in edits:
        seen_edits.add((e.get("sender", ""), e.get("text", ""), e.get("tail", "")))
    for e in _extract_edits(text):
        key2 = (e.get("sender", ""), e.get("text", ""), e.get("tail", ""))
        if key2 in seen_edits:
            continue
        seen_edits.add(key2)
        edits.append(e)

    # Per-message emoji reaction footers merged with any caller-
    # supplied reactions. De-dupes on the (sender, tuple-of-(emoji,
    # count)) key so an LLM-supplied reaction footer plus the OCR-
    # parsed identical footer collapses to one entry. Caller order
    # preserved first.
    reactions: list[dict] = list(existing.reactions) if existing else []
    seen_reactions: set[tuple[str, tuple]] = set()
    for r in reactions:
        rkey = (
            r.get("sender", "") or "",
            tuple((x.get("emoji", ""), x.get("count", 0)) for x in r.get("reactions", [])),
        )
        seen_reactions.add(rkey)
    for r in _extract_reactions(text):
        rkey = (
            r.get("sender", "") or "",
            tuple((x.get("emoji", ""), x.get("count", 0)) for x in r.get("reactions", [])),
        )
        if rkey in seen_reactions:
            continue
        seen_reactions.add(rkey)
        reactions.append(r)

    # Replied-to / quoted-message blocks merged with any caller-
    # supplied quotes. De-dupes on the (sender, quoted_sender,
    # quoted_text, reply_text) quadruple so an LLM-supplied quote
    # plus the OCR-parsed identical quote collapses to one entry.
    # Caller order preserved first.
    quotes: list[dict[str, str]] = list(existing.quotes) if existing else []
    seen_quotes: set[tuple[str, str, str, str]] = set()
    for q in quotes:
        qk = (
            q.get("sender", "") or "",
            q.get("quoted_sender", "") or "",
            q.get("quoted_text", "") or "",
            q.get("reply_text", "") or "",
        )
        seen_quotes.add(qk)
    for q in _extract_quotes(text):
        qk = (
            q.get("sender", "") or "",
            q.get("quoted_sender", "") or "",
            q.get("quoted_text", "") or "",
            q.get("reply_text", "") or "",
        )
        if qk in seen_quotes:
            continue
        seen_quotes.add(qk)
        quotes.append(q)

    # Attachment markers ([Image] / 📷 Photo / Voice message (0:42))
    # merged with any caller-supplied attachments. De-dupes on the
    # (sender, kind, duration, name) tuple so the same WhatsApp
    # ``[Image]`` printed twice collapses to one entry. Caller
    # order preserved first.
    attachments: list[dict[str, str | None]] = (
        list(existing.attachments) if existing else []
    )
    seen_attach: set[tuple[str, str, str, str]] = set()
    for a in attachments:
        ak = (
            a.get("sender") or "",
            a.get("kind") or "",
            a.get("duration") or "",
            a.get("name") or "",
        )
        seen_attach.add(ak)
    for a in _extract_attachments(text):
        ak = (
            a.get("sender") or "",
            a.get("kind") or "",
            a.get("duration") or "",
            a.get("name") or "",
        )
        if ak in seen_attach:
            continue
        seen_attach.add(ak)
        attachments.append(a)

    # Poll / survey blocks merged with any caller-supplied polls.
    # De-dupes on the (question, tuple-of-(label, votes)) key so an
    # LLM-supplied poll plus the OCR-parsed identical poll collapses
    # to one entry. Caller order preserved first.
    polls: list[dict] = list(existing.polls) if existing else []
    seen_polls: set[tuple[str, tuple]] = set()
    for p in polls:
        pk = (
            p.get("question", "") or "",
            tuple(
                (o.get("label", ""), o.get("votes", 0))
                for o in p.get("options", [])
            ),
        )
        seen_polls.add(pk)
    for p in _extract_polls(text):
        pk = (
            p.get("question", "") or "",
            tuple(
                (o.get("label", ""), o.get("votes", 0))
                for o in p.get("options", [])
            ),
        )
        if pk in seen_polls:
            continue
        seen_polls.add(pk)
        polls.append(p)

    return ChatFields(
        platform=platform,
        participants=participants,
        messages=messages,
        hashtags=hashtags,
        mentions=mentions,
        statuses=statuses,
        edits=edits,
        reactions=reactions,
        quotes=quotes,
        attachments=attachments,
        polls=polls,
    )
