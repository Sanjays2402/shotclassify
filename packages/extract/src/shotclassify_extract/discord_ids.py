"""Cross-category Discord ID (snowflake) extractor.

Discord assigns every user, channel, guild (server), role, message,
and webhook a 64-bit Snowflake ID that surfaces in code snippets that
use the discord.py / discord.js SDKs, error logs from those clients,
chat captures of Discord conversations (the ``<@123456789012345678>``
mention syntax), and document captures of Discord API responses.
Rather than teach each per-category extractor to find them, we run
:func:`extract_discord_ids` once on the OCR text and stash unique
entries under ``ExtractedFields.raw["discord_ids"]``.

Output shape: a list of ``{"kind", "id"}`` dicts where:

* ``kind``  -- one of ``user``, ``channel``, ``role``,
               ``mentionable`` (the catch-all ``<@!id>`` legacy
               nickname-mention form), ``guild``, ``message``,
               ``webhook``, ``raw`` (Discord snowflake found in
               context that mentions Discord but without a typed
               wrapper).
* ``id``    -- the 17..19 decimal-digit snowflake itself.

Output preserves first-seen order, dedupes on ``id`` value (so the
same user mentioned multiple ways collapses to one entry, and the
first-seen kind wins), capped at 50.

Recognised forms (per Discord's developer docs):

* ``<@123456789012345678>``     -- user mention
* ``<@!123456789012345678>``    -- legacy nickname mention (same
                                    user as above; we tag as
                                    ``user`` for consistency)
* ``<#123456789012345678>``     -- channel mention
* ``<@&123456789012345678>``    -- role mention
* ``https://discord.com/channels/<GUILD>/<CHANNEL>/<MESSAGE>``
                                 -- jump URL (we capture GUILD as
                                    ``guild``, CHANNEL as
                                    ``channel``, MESSAGE as
                                    ``message``)
* ``https://discord.com/api/webhooks/<ID>/<TOKEN>``
                                 -- webhook URL (we capture ID as
                                    ``webhook`` and intentionally
                                    DO NOT capture the token, ever)
* Bare 17..19 digit snowflake with a Discord-context anchor (the
  word ``discord`` / ``snowflake`` / ``guild`` / ``channel_id`` /
  ``user_id`` on the same or previous line). Tagged ``raw``.

Distinct from raw["slack_ids"] (Slack workspace IDs are
letter-prefixed alphanumeric) and raw["stripe_ids"] (Stripe IDs
are typed-prefix lowercase + underscore). Discord IDs are pure
decimal digits and so need the typed-wrapper or context anchor to
land safely.
"""
from __future__ import annotations

import re

# Snowflake = 17..19 decimal digits. The lower bound (17) is the
# shortest snowflake ever issued (very early users circa 2015);
# the upper bound (19) covers the worst-case 64-bit unsigned max.
# Word-boundary required at both ends so a longer digit blob
# (a UUID's digit-only fragment, a phone number, a Stripe-style
# 18-digit ID) doesn't misfire.
_SNOWFLAKE = r"(?P<id>\d{17,19})"

# Typed mention forms.
_USER_MENTION_RE = re.compile(r"<@!?" + _SNOWFLAKE + r">")
_CHANNEL_MENTION_RE = re.compile(r"<#" + _SNOWFLAKE + r">")
_ROLE_MENTION_RE = re.compile(r"<@&" + _SNOWFLAKE + r">")

# Jump URL: discord.com/channels/<guild>/<channel>/<message>.
# We accept both ``discord.com`` and ``discordapp.com`` (the
# legacy domain). The ``http(s)://`` prefix is optional because
# OCR captures often miss the scheme. We capture all three IDs.
_JUMP_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord|discordapp)\.com/channels/"
    r"(?P<guild>\d{17,19})/"
    r"(?P<channel>\d{17,19})/"
    r"(?P<message>\d{17,19})"
)

# Webhook URL: discord.com/api/webhooks/<id>/<token>.
# We capture only the ID and intentionally DROP the token from
# our output (it's a secret). The token segment is matched but
# not captured.
_WEBHOOK_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord|discordapp)\.com/api/webhooks/"
    r"(?P<id>\d{17,19})/[A-Za-z0-9_\-]+"
)

# Bare snowflake with a Discord-context anchor. We accept any
# 17..19 digit snowflake on a line whose contents OR whose
# previous line's contents mention Discord. Context anchors are
# matched case-insensitively on a whole-word basis.
_BARE_SNOWFLAKE_RE = re.compile(
    r"(?<![0-9])" + _SNOWFLAKE + r"(?![0-9])"
)
_DISCORD_CONTEXT_RE = re.compile(
    r"\b(?:discord|snowflake|guild|guild_id|channel_id|user_id|"
    r"role_id|webhook_id|message_id|author_id|server_id|"
    r"discord\.py|discord\.js)\b",
    re.IGNORECASE,
)


_MAX_DISCORD_IDS = 50


def _add(seen: set[str], out: list[dict[str, str]], kind: str, ident: str) -> bool:
    """Add the entry if it's not already seen. Return True when we
    appended; False when the entry was a duplicate or the output
    cap was reached. The "first-seen kind wins" semantics fall out
    naturally because we don't update an existing entry on a
    repeat ID."""
    if ident in seen:
        return False
    if len(out) >= _MAX_DISCORD_IDS:
        return False
    seen.add(ident)
    out.append({"kind": kind, "id": ident})
    return True


def _line_index_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset)


def extract_discord_ids(text: str) -> list[dict[str, str]]:
    """Return unique Discord snowflake IDs found in ``text``.

    Output is a list of ``{"kind", "id"}`` dicts. Kind tags:
    ``user``, ``channel``, ``role``, ``guild``, ``message``,
    ``webhook``, ``raw``.

    Recognises Discord's standard mention syntax (``<@id>`` for
    users, ``<#id>`` for channels, ``<@&id>`` for roles), jump
    URLs (``discord.com/channels/G/C/M``), webhook URLs (we
    intentionally DROP the token), and bare 17..19 digit
    snowflakes that have a Discord-context anchor (``discord`` /
    ``snowflake`` / ``guild`` / ``channel_id`` / ``user_id`` etc.)
    on the same or previous line.

    The bare-snowflake matcher REQUIRES the context anchor because
    a 17..19 digit decimal blob is too common (UNIX nanosecond
    timestamps, sequence numbers, opaque IDs from other systems)
    to land safely without an anchor.

    Webhook tokens are NEVER emitted (security guarantee enforced
    by test).

    Preserves first-seen order across all matchers. De-dupes on
    the ``id`` value so the same user mentioned three ways
    collapses to one entry; the first-seen kind wins. Capped at 50
    entries.
    """
    if not text or not isinstance(text, str):
        return []
    seen: set[str] = set()
    out: list[dict[str, str]] = []

    # Pass 1: typed mentions (highest confidence).
    for m in _USER_MENTION_RE.finditer(text):
        _add(seen, out, "user", m.group("id"))
    for m in _CHANNEL_MENTION_RE.finditer(text):
        _add(seen, out, "channel", m.group("id"))
    for m in _ROLE_MENTION_RE.finditer(text):
        _add(seen, out, "role", m.group("id"))

    # Pass 2: jump URLs and webhook URLs. Jump URLs surface the
    # guild + channel + message triple.
    for m in _JUMP_URL_RE.finditer(text):
        _add(seen, out, "guild", m.group("guild"))
        _add(seen, out, "channel", m.group("channel"))
        _add(seen, out, "message", m.group("message"))
    for m in _WEBHOOK_URL_RE.finditer(text):
        _add(seen, out, "webhook", m.group("id"))

    # Pass 3: bare snowflakes with a Discord-context anchor on the
    # same or previous line. Pre-compute the anchor-line set in
    # O(N) so we can check "current or previous line" in O(1).
    lines = text.splitlines()
    anchor_lines = {
        i for i, line in enumerate(lines) if _DISCORD_CONTEXT_RE.search(line)
    }
    if anchor_lines:
        for m in _BARE_SNOWFLAKE_RE.finditer(text):
            ident = m.group("id")
            if ident in seen:
                continue
            line_idx = _line_index_for_offset(text, m.start())
            if line_idx in anchor_lines or (line_idx - 1) in anchor_lines:
                if not _add(seen, out, "raw", ident):
                    if len(out) >= _MAX_DISCORD_IDS:
                        break

    return out


__all__ = ["extract_discord_ids"]
