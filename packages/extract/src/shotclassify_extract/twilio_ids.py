"""Cross-category Twilio SID extractor.

Twilio assigns each object (account, message, call, recording,
WhatsApp message, conference, conversation, ...) a typed
"SID" (String Identifier) of the form ``<PREFIX><32-hex>``. The
prefix is two ALL-CAPS letters identifying the object type; the
tail is exactly 32 lowercase hex chars (md5-sized). SIDs surface
on Twilio Console URLs, API responses pasted into code snippets,
webhook payloads quoted in error logs, and developer chat
captures.

We surface these SIDs found in the OCR text under
``ExtractedFields.raw["twilio_ids"]`` so dashboards, routing
rules, and downstream agents have a single place to look for
Twilio context.

Output shape: a list of ``{"kind": str, "id": str}`` dicts. The
``kind`` tag is the long-form name of the prefix (``account`` /
``sms`` / ``mms`` / ``call`` / ``recording`` / ``whatsapp`` /
...) so downstream consumers don't need to maintain their own
prefix-to-name table.

Recognised prefixes (per Twilio's typed-SID convention):

* ``AC`` -- Account
* ``SM`` -- SMS Message
* ``MM`` -- MMS Message
* ``CA`` -- Call
* ``RE`` -- Recording
* ``WA`` -- WhatsApp Message
* ``CF`` -- Conference
* ``CH`` -- Conversation / Channel
* ``MG`` -- Messaging Service
* ``PN`` -- Phone Number
* ``AP`` -- Application (TwiML App)
* ``NO`` -- Notification
* ``RC`` -- Workflow Reservation (TaskRouter)
* ``QU`` -- TaskRouter Queue
* ``WK`` -- Worker (TaskRouter)
* ``WF`` -- Workflow (TaskRouter)
* ``WS`` -- Workspace (TaskRouter)
* ``DE`` -- Deployment / Device (Sync / IoT)
* ``IS`` -- Identity (Conversations)
* ``KE`` -- API Key
* ``IP`` -- IP Access Control List
* ``FN`` -- Function (Twilio Functions)
* ``GZ`` -- Asset (Twilio Assets)
* ``ZS`` -- Service (Sync / Chat / Verify)
* ``EV`` -- Event Subscription
* ``ZN`` -- Notification
* ``LI`` -- Local Insights (Voice Insights)

Shape rules:

* Two ALL-CAPS letters from the catalogue, followed by exactly
  32 LOWERCASE hex chars. Twilio's SIDs are strictly lowercase
  hex in the tail; upper-case hex in the tail is a sign of
  noise or fabricated examples and we deliberately do NOT
  match those (the canonical Twilio response payloads are
  always lowercase).
* Word-boundary on both ends so a code-fenced ``XXACabcd...``
  hex blob does not misfire.
* The full SID is therefore 34 chars long.
"""
from __future__ import annotations

import re

# Map two-letter prefix to the long-form kind tag emitted in the
# output. Order does not matter for the regex (the alternation
# branches are length-matched: 2 chars each) but we list them
# alphabetically for readability.
_KIND_NAMES: dict[str, str] = {
    "AC": "account",
    "AP": "application",
    "CA": "call",
    "CF": "conference",
    "CH": "conversation",
    "DE": "deployment",
    "EV": "event_subscription",
    "FN": "function",
    "GZ": "asset",
    "IP": "ip_access_control",
    "IS": "identity",
    "KE": "api_key",
    "LI": "local_insight",
    "MG": "messaging_service",
    "MM": "mms",
    "NO": "notification",
    "PN": "phone_number",
    "QU": "task_queue",
    "RC": "task_reservation",
    "RE": "recording",
    "SM": "sms",
    "WA": "whatsapp",
    "WF": "workflow",
    "WK": "worker",
    "WS": "workspace",
    "ZN": "sync_notification",
    "ZS": "service",
}

# Build the prefix alternation. Since every prefix is exactly two
# letters there's no longest-first ordering concern; we just join
# them in alphabetical order.
_PREFIX_ALT = "|".join(sorted(_KIND_NAMES.keys()))

# Two ALL-CAPS letters from the catalogue + exactly 32 lowercase
# hex chars. Word-boundary isolation on both ends so a code-fenced
# substring inside a longer hash doesn't misfire.
#
# Why lowercase-only on the hex tail? Real Twilio API responses
# always emit the tail in lowercase. Allowing uppercase would
# false-positive on uppercase MD5/SHA digests with a leading
# 2-letter run that happens to be in our catalogue (any random
# 34-char uppercase hex hash starting with one of 27 prefixes
# would steal). Lowercase-only is a tight, useful constraint.
_TWILIO_SID_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?P<kind>" + _PREFIX_ALT + r")"
    r"(?P<rest>[a-f0-9]{32})"
    r"(?![A-Za-z0-9_])"
)


_MAX_TWILIO_IDS = 50


def extract_twilio_ids(text: str) -> list[dict[str, str]]:
    """Return unique Twilio SIDs found in ``text``.

    Output is a list of ``{"kind", "id"}`` dicts, preserving
    first-seen order across the OCR text. De-duplicates on the
    ``id`` value so the same call SID printed multiple times in
    the same screenshot collapses to one entry. Caps the output
    at 50 entries.

    The matcher is intentionally tight: it requires a two-letter
    ALL-CAPS prefix from the recognised catalogue followed by
    exactly 32 LOWERCASE hex chars, with word-boundary isolation
    on both ends. The lowercase-tail rule keeps random uppercase
    MD5/SHA hashes that happen to start with one of our prefixes
    from misfiring.
    """
    if not text or not isinstance(text, str):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _TWILIO_SID_RE.finditer(text):
        prefix = m.group("kind")
        rest = m.group("rest")
        ident = f"{prefix}{rest}"
        if ident in seen:
            continue
        seen.add(ident)
        out.append({"kind": _KIND_NAMES[prefix], "id": ident})
        if len(out) >= _MAX_TWILIO_IDS:
            break
    return out


__all__ = ["extract_twilio_ids"]
