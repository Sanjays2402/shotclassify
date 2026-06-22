"""Cross-category Slack ID extractor.

Slack assigns each channel, DM, user, group, and workspace a short
opaque ID that surfaces on URL fragments, API payloads, error logs,
chat captures, and code snippets that integrate with Slack. We
surface these IDs found in the OCR text under
``ExtractedFields.raw["slack_ids"]`` so dashboards, routing rules,
and downstream agents have a single place to look for Slack context.

Output shape: a list of ``{"kind": str, "id": str}`` dicts. The
list preserves first-seen order and is capped at 50 entries.

Recognised ID prefixes (per Slack's API documentation):

* ``C`` -- public channel  (``C012345ABCD``)
* ``D`` -- direct message  (``D012345ABCD``)
* ``G`` -- private channel / multi-party DM  (``G012345ABCD``)
* ``U`` -- user            (``U012345ABCD``)
* ``W`` -- enterprise user (``W012345ABCD``)
* ``B`` -- bot user        (``B012345ABCD``)
* ``T`` -- team / workspace (``T012345ABCD``)
* ``E`` -- enterprise grid (``E012345ABCD``)
* ``F`` -- file            (``F012345ABCD``)
* ``S`` -- usergroup       (``S012345ABCD``)

The kind tag emitted is the long-form name of the prefix
(``channel`` / ``dm`` / ``private_channel`` / ``user`` /
``enterprise_user`` / ``bot`` / ``team`` / ``enterprise`` /
``file`` / ``usergroup``) so downstream consumers don't need to
maintain their own letter-to-name table.

Shape rules:

* Single uppercase prefix letter from the recognised set, followed
  by 8..10 uppercase-alphanumeric chars (Slack IDs are case-
  sensitive and always uppercase in real-world payloads).
* Word-boundary anchored on BOTH sides so a "C012345ABCD" inside a
  longer hex / hash string ("AC012345ABCDEF") does not misfire.
* The total length range (9..11 chars) lines up with the IDs Slack
  has issued over the lifetime of the platform.
"""
from __future__ import annotations

import re

# Single uppercase letter from the recognised prefix set, then
# 8..10 uppercase-alphanumeric chars. Word-boundary anchored on
# both ends so a code-fenced "AC0123456789ABC" hex blob does NOT
# misfire as a Slack ID. The first letter is captured into the
# ``kind`` group so we can emit the long-form name.
#
# Tail must contain at least ONE digit to keep all-letter prose
# words ("CHEAPCODE", "DESPAIRED") from misfiring -- real Slack
# IDs are random base32-ish strings that empirically always carry
# a digit somewhere. We enforce this with a forward assertion that
# the tail (immediately after the prefix letter) contains
# `[A-Z]*\d[A-Z0-9]*` matching the 8..10-char tail.
_SLACK_ID_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?P<kind>[CDGUWBTEFS])"
    r"(?=[A-Z0-9]{8,10}(?![A-Za-z0-9_]))"
    r"(?P<rest>[A-Z0-9]*\d[A-Z0-9]*)"
)


# Map prefix letter to the long-form kind tag emitted in the output.
_KIND_NAMES: dict[str, str] = {
    "C": "channel",
    "D": "dm",
    "G": "private_channel",
    "U": "user",
    "W": "enterprise_user",
    "B": "bot",
    "T": "team",
    "E": "enterprise",
    "F": "file",
    "S": "usergroup",
}


_MAX_SLACK_IDS = 50


def extract_slack_ids(text: str) -> list[dict[str, str]]:
    """Return unique Slack IDs found in ``text``.

    Output is a list of ``{"kind", "id"}`` dicts, preserving
    first-seen order across the OCR text. De-duplicates on the
    ``id`` value so the same channel ID printed multiple times in
    the same screenshot collapses to one entry. Caps the output at
    50 entries.

    The matcher is intentionally conservative: it requires the
    canonical Slack length range (9..11 chars total -- 1-letter
    prefix + 8..10-char tail) and word-boundary isolation on both
    sides so:

    * A code-fenced hex hash like ``C0DEC0FFEEBAD1234`` does not
      misfire as a channel ID (length exceeds the 11-char cap).
    * A UUID fragment ``ABCDEF12-345A-...`` does not misfire
      (the leading ``A`` is not in our prefix set, and the
      word-boundary defence wouldn't accept it anyway because the
      ``-`` is alpha-numeric-adjacent).
    * A bare ``CHEAPCODE`` 9-letter all-cap word in prose does not
      match because Slack IDs have a digit somewhere in their
      tail -- but we deliberately do NOT enforce that here because
      old IDs are letter-only too. The trade-off: a 9-letter
      uppercase prose word starting with C/D/G/U/W/B/T/E/F/S WILL
      match. We accept that as the cost of recall; the
      letter-set constraint already filters out the vast majority
      of false positives.
    """
    if not text or not isinstance(text, str):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _SLACK_ID_RE.finditer(text):
        kind_letter = m.group("kind")
        ident = kind_letter + m.group("rest")
        if ident in seen:
            continue
        seen.add(ident)
        out.append({"kind": _KIND_NAMES[kind_letter], "id": ident})
        if len(out) >= _MAX_SLACK_IDS:
            break
    return out


__all__ = ["extract_slack_ids"]
