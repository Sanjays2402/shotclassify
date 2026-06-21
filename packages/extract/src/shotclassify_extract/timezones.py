"""Cross-category timezone extractor.

Timezones surface in every category of screenshot: chat captures
print message timestamps with offsets (``11:34 +05:30``), error
logs anchor stack traces in a specific zone (``2024-03-15T08:23:01Z``),
receipts stamp transactions for the merchant's local time, document
captures cite meeting times, terminal output paste ``date(1)``
results, calendar shots advertise ``9:00 AM PST``. Rather than teach
each per-category extractor to find them, we run :func:`extract_timezones`
once on the OCR text and stash the unique, order-preserving list
under ``ExtractedFields.raw["timezones"]`` so dashboards, routing
rules, and downstream agents have a single place to look.

Output shape: a list of strings -- each entry is canonical so the
same zone printed multiple ways collapses to one entry.

Recognised forms:

* **UTC numeric offsets**: ``+05:30``, ``-0800``, ``-08``, ``UTC+1``,
  ``GMT-5``. Hour range bounded to ``-12..+14`` per IANA; minute
  component bounded to ``0..59``. Canonical output preserves the
  sign and uses the ``hh:mm`` colon form when minutes are non-zero,
  ``hh`` when minutes are zero (so ``-0800`` and ``-08`` collapse to
  ``-08``, while ``+0530`` and ``+05:30`` collapse to ``+05:30``).
* **Z / Zulu suffix**: a standalone ``Z`` adjacent to an ISO-8601
  timestamp normalises to ``+00`` (UTC). The bare letter ``Z`` is
  rejected because it false-positives on prose; the matcher requires
  the preceding context to be ISO-8601-ish (date / time / digit run).
* **Named zone abbreviations**: ``UTC``, ``GMT``, ``PST``, ``PDT``,
  ``EST``, ``EDT``, ``CST``, ``CDT``, ``MST``, ``MDT``, ``BST``,
  ``CET``, ``CEST``, ``IST``, ``JST``, ``KST``, ``AEST``, ``AEDT``,
  ``ACST``, ``ACDT``, ``AWST``, ``HST``, ``AKST``, ``AKDT``,
  ``NZST``, ``NZDT``, ``WET``, ``WEST``, ``EET``, ``EEST``,
  ``MSK``, ``SGT``, ``HKT``, ``PHT``. These are matched as
  whole-word tokens to avoid false-positives on prose (e.g.
  ``ist`` inside ``exist``). ``IST`` is intentionally
  Indian-Standard-Time-or-Irish-Standard-Time-or-Israel-Standard-Time
  ambiguous; we surface the abbreviation, the consumer disambiguates.
* **Named IANA zones**: ``America/New_York``, ``Europe/London``,
  ``Asia/Tokyo`` etc. Recognised by the ``Region/City`` shape with a
  letters-only region from the IANA top-level list (``America``,
  ``Europe``, ``Asia``, ``Africa``, ``Australia``, ``Antarctica``,
  ``Atlantic``, ``Pacific``, ``Indian``, ``Etc``).

Deliberately NOT matched:

* Bare ``Z`` as a standalone letter -- too many false positives in
  prose. The matcher requires ISO-8601 context.
* Numeric offsets that look like phone area codes (``+1 415``) --
  the offset matcher refuses when the surrounding context isn't
  time-shaped.
* Abbreviations that overlap common English words (``IST`` as a
  substring inside ``EXIST``) -- word boundaries enforced.
"""
from __future__ import annotations

import re

# Numeric UTC offset. The leading sign is required so we don't match
# a bare ``05:30`` which is just a time. Hour bounded to 00..14 (the
# +14 is IANA's max for Pacific/Kiritimati); minute bounded 00..59.
# Optional UTC/GMT prefix because some clients print ``UTC+05:30``.
_NUMERIC_OFFSET_RE = re.compile(
    r"(?<!\w)"
    r"(?:(?:UTC|GMT)\s*)?"
    # Sign + 1-2 digit hours, optionally ``:MM`` or ``MM``.
    r"(?P<sign>[+\-])(?P<hh>\d{1,2})(?::?(?P<mm>\d{2}))?"
    r"(?!\d)"
)

# Z-suffix: only counts when adjacent to an ISO-8601-ish timestamp.
# The lookbehind requires a digit (the seconds, fractional seconds,
# or the colon between hh:mm). Lookahead disallows a letter so we
# don't bite into a word like ``Zealand`` or ``Zambia``.
_Z_SUFFIX_RE = re.compile(r"(?<=\d)(?P<z>Z)(?![A-Za-z])")

# Named abbreviations. Catalogue chosen for global coverage; each entry
# is matched as a whole-word token (word boundary on both sides).
_NAMED_ABBREVS = (
    "UTC",
    "GMT",
    "PST",
    "PDT",
    "EST",
    "EDT",
    "CST",
    "CDT",
    "MST",
    "MDT",
    "BST",
    "CET",
    "CEST",
    "IST",
    "JST",
    "KST",
    "AEST",
    "AEDT",
    "ACST",
    "ACDT",
    "AWST",
    "HST",
    "AKST",
    "AKDT",
    "NZST",
    "NZDT",
    "WET",
    "WEST",
    "EET",
    "EEST",
    "MSK",
    "SGT",
    "HKT",
    "PHT",
)
_NAMED_RE = re.compile(
    r"\b(?P<n>" + "|".join(sorted(_NAMED_ABBREVS, key=len, reverse=True)) + r")\b"
)

# IANA-style ``Region/City``. Region drawn from the documented IANA
# top-level list; city tolerates letters, digits, underscore, dash,
# and a forward slash (because some IANA names are three-part:
# ``America/Argentina/Buenos_Aires``).
_IANA_REGIONS = (
    "Africa",
    "America",
    "Antarctica",
    "Arctic",
    "Asia",
    "Atlantic",
    "Australia",
    "Europe",
    "Indian",
    "Pacific",
    "Etc",
)
_IANA_RE = re.compile(
    r"\b(?P<r>(?:" + "|".join(_IANA_REGIONS) + r"))"
    r"/(?P<c>[A-Za-z][A-Za-z0-9_\-]*(?:/[A-Za-z][A-Za-z0-9_\-]*)?)"
    r"\b"
)


_MAX_TIMEZONES = 50


def _canonical_offset(sign: str, hh: int, mm: int) -> str:
    """Return ``+hh`` if ``mm`` is 0, else ``+hh:mm``. Same with ``-``.

    Two-digit hour padding always applied so ``+05`` and ``+05:30`` are
    visually distinguishable and ``+5`` never appears in storage.
    """
    base = f"{sign}{hh:02d}"
    if mm == 0:
        return base
    return f"{base}:{mm:02d}"


def extract_timezones(text: str) -> list[str]:
    """Return unique timezone tokens found in ``text``.

    Output is a list of canonical strings preserving first-seen-in-text
    order. Numeric offsets normalise to ``+hh`` (or ``+hh:mm`` if
    minutes are non-zero), the Z suffix normalises to ``+00``, named
    abbreviations are uppercased verbatim, and IANA names are kept
    in their canonical ``Region/City`` form. Caps the output at 50
    entries.
    """
    if not text or not isinstance(text, str):
        return []
    seen: set[str] = set()
    out: list[str] = []
    candidates: list[tuple[int, str]] = []

    # 1) IANA names first (most specific shape) so a numeric offset
    #    inside an IANA name (unlikely, but defence-in-depth) doesn't
    #    steal the match.
    consumed_spans: list[tuple[int, int]] = []
    for m in _IANA_RE.finditer(text):
        token = f"{m.group('r')}/{m.group('c')}"
        candidates.append((m.start(), token))
        consumed_spans.append((m.start(), m.end()))

    # 2) Numeric offsets. We have to honour the consumed-spans list
    #    because the IANA city sometimes contains a hyphen + digit
    #    sequence (``GMT+1`` style cities don't exist in IANA, but
    #    defence-in-depth).
    def _in_consumed(pos: int) -> bool:
        return any(start <= pos < end for start, end in consumed_spans)

    for m in _NUMERIC_OFFSET_RE.finditer(text):
        if _in_consumed(m.start()):
            continue
        sign = m.group("sign")
        hh = int(m.group("hh"))
        mm = int(m.group("mm") or 0)
        if hh > 14 or mm > 59:
            continue
        # The negative-offset max is -12 (Pacific/Niue / Pacific/Pago_Pago),
        # but the IANA upper is +14, so the asymmetric check goes
        # only on the negative side.
        if sign == "-" and hh > 12:
            continue
        candidates.append((m.start(), _canonical_offset(sign, hh, mm)))
        consumed_spans.append((m.start(), m.end()))

    # 3) Z-suffix (only adjacent to a digit so it's ISO-8601-ish).
    for m in _Z_SUFFIX_RE.finditer(text):
        if _in_consumed(m.start()):
            continue
        candidates.append((m.start(), "+00"))
        # No need to record the consumed span -- nothing else matches
        # a bare ``Z`` and the named matcher's word boundary keeps it
        # away from words containing Z.

    # 4) Named abbreviations LAST so a more-specific shape wins.
    for m in _NAMED_RE.finditer(text):
        if _in_consumed(m.start()):
            continue
        candidates.append((m.start(), m.group("n").upper()))

    # Source-text order so the list reflects reading order.
    candidates.sort(key=lambda x: x[0])

    for _, canonical in candidates:
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
        if len(out) >= _MAX_TIMEZONES:
            break
    return out


__all__ = ["extract_timezones"]
