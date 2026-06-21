"""Cross-category UUID extractor.

UUIDs (Universally Unique Identifiers) appear in every category of
screenshot -- error stacktraces print correlation IDs, code snippets
declare them as test fixtures, document captures reference resource
IDs in URLs, chat captures share invite-link UUIDs, terminal output
shows process / session IDs. Rather than teach each per-category
extractor to find UUIDs, we run :func:`extract_uuids` once on the
OCR text and stash the unique, order-preserving list under
``ExtractedFields.raw["uuids"]`` so dashboards, routing rules, and
downstream agents have a single place to look.

Recognised shapes:

* **Dashed** (canonical RFC 4122 form): ``8-4-4-4-12`` hex with
  hyphens, e.g. ``550e8400-e29b-41d4-a716-446655440000``. Matches
  v1..v5 (the version is the first digit of the third group;
  ``1`` / ``2`` / ``3`` / ``4`` / ``5``). The variant nibble (first
  digit of the fourth group) must be in ``8..b`` for a strict RFC
  4122 UUID, but we deliberately accept anything in ``[0-9a-f]``
  for the variant slot because real-world dashboards encounter
  Microsoft GUIDs and other UUID-shaped IDs whose variant doesn't
  conform to RFC 4122. The version nibble IS enforced so we never
  fold a random 32-hex string of the wrong shape into the list.
* **Compact** (no hyphens, 32 hex chars). Same version-nibble
  enforcement: position 12 (0-indexed) must be ``1..5``. Surrounded
  by non-hex boundaries so we never bite into a longer SHA hash
  (40 / 64 chars) that happens to contain a UUID-looking substring.

Output canonical form: lowercase + hyphenated (canonical RFC form),
regardless of which shape was matched. ``550E8400E29B41D4A716446655440000``,
``550E8400-E29B-41D4-A716-446655440000``, and
``550e8400-e29b-41d4-a716-446655440000`` all collapse to one entry.

Deliberately NOT matched:

* "Nil" UUID (all zeros) -- it's a real RFC 4122 UUID but it's
  almost always a placeholder / default value rather than a real
  identifier; including it bloats the list with noise.
* Random 32 / 36-hex strings whose version nibble is 0 or 6..f --
  not UUIDs in any of the v1..v5 schemes we care about.
"""
from __future__ import annotations

import re

# Dashed RFC 4122 UUID: 8-4-4-4-12 hex with hyphens. The third group's
# first char enforces the version (``1`` / ``2`` / ``3`` / ``4`` /
# ``5``). The fourth group's first char is unconstrained (we accept
# Microsoft GUIDs whose variant doesn't conform to RFC 4122 either).
_UUID_DASHED_RE = re.compile(
    r"(?<![0-9a-fA-F])"
    r"(?P<u>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r"(?![0-9a-fA-F])"
)

# Compact form: 32 hex chars with no hyphens. Same version-nibble
# enforcement at position 12. The non-hex boundary on both sides
# stops us from biting into a longer SHA-1 / SHA-256 string.
_UUID_COMPACT_RE = re.compile(
    r"(?<![0-9a-fA-F])"
    r"(?P<u>[0-9a-fA-F]{12}[1-5][0-9a-fA-F]{19})"
    r"(?![0-9a-fA-F])"
)


_MAX_UUIDS = 50


def _dashed_canonical(compact: str) -> str:
    """Insert RFC 4122 hyphens into a 32-char compact UUID."""
    return (
        f"{compact[0:8]}-{compact[8:12]}-{compact[12:16]}-"
        f"{compact[16:20]}-{compact[20:32]}"
    )


# All-zero UUID -- valid by RFC but almost always a placeholder.
_NIL_UUID = "00000000-0000-0000-0000-000000000000"


def extract_uuids(text: str) -> list[str]:
    """Return unique UUIDs found in ``text``.

    Output is lowercase + hyphenated (canonical RFC 4122 form)
    regardless of which input shape was matched. Preserves first-seen
    order; dashed and compact representations of the same UUID
    collapse to one entry, with the FIRST-seen-in-text shape's
    position determining the order. Caps the output at 50 entries.
    The "nil" UUID (all zeros) is rejected because it's almost
    always a placeholder rather than a real identifier.
    """
    if not text or not isinstance(text, str):
        return []
    seen: set[str] = set()
    out: list[str] = []
    candidates: list[tuple[int, str]] = []

    # Dashed shape -- canonical form, no normalisation needed beyond
    # lowercasing.
    for m in _UUID_DASHED_RE.finditer(text):
        candidates.append((m.start(), m.group("u").lower()))
    # Compact shape -- insert the hyphens into the canonical
    # 8-4-4-4-12 layout before storing.
    for m in _UUID_COMPACT_RE.finditer(text):
        canonical = _dashed_canonical(m.group("u").lower())
        candidates.append((m.start(), canonical))

    # Sort by source-text offset so the order matches what a human
    # reading the screenshot top-to-bottom would see, not the matcher
    # iteration order.
    candidates.sort(key=lambda x: x[0])

    for _, canonical in candidates:
        if canonical == _NIL_UUID:
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
        if len(out) >= _MAX_UUIDS:
            break
    return out


__all__ = ["extract_uuids"]
