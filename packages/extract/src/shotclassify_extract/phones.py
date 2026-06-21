"""Cross-category phone-number extractor.

Phone numbers show up in every category of screenshot -- receipts
print the merchant's contact, chat captures share contact cards,
documents and signatures include direct lines, error pages cite the
on-call number, code snippets carry test fixtures
(``+15551234567``). Rather than teach each per-category extractor to
find phone numbers, we run :func:`extract_phones` once on the OCR
text and stash the unique, order-preserving list under
``ExtractedFields.raw["phones"]`` so dashboards, routing rules, and
downstream agents have a single place to look.

Recognised shapes (matched in priority order so an E.164 number does
not also count as a NANP number):

* **E.164** (international): ``+1 (415) 555-1234``,
  ``+442079460958``, ``+91-98765-43210``. The leading ``+`` is
  required so we never confuse an internal extension or order number
  for an international phone. Digits-only length is bounded to
  8..15 per the ITU E.164 spec; values outside that range are
  rejected.
* **NANP formatted** (North American Numbering Plan):
  ``(415) 555-1234``, ``415-555-1234``, ``415.555.1234``,
  ``415 555 1234``. The area code (first three digits) must start
  with ``2..9`` because a real NANP area code never starts with 0
  or 1; the exchange (next three) must start with ``2..9`` too.
  This is the same validation the FCC publishes for NANP allocations
  and it eliminates the most common false positives (line-number
  refs like ``123-456-7890`` which look phone-shaped but cannot be
  one).
* **Keyword-prefixed bare NANP**: ``Phone: 4155551234``,
  ``Tel 415 555 1234``, ``Mobile: 4155551234``, ``Fax 4155551234``.
  Only matches when an explicit phone-class keyword precedes the
  number, because a bare 10-digit run in OCR text is far too easy
  to false-positive on account numbers, IDs, and prices.

Output canonical form: digits-only, with a leading ``+`` preserved
for E.164 matches. This makes dashboard de-dup trivial -- the same
number printed as ``+1 (415) 555-1234`` and ``+14155551234``
collapses to a single entry.

Deliberately NOT matched:

* Bare 10-digit runs without a phone-class keyword nearby (too many
  false positives on order numbers, transaction IDs, prices).
* Numbers shorter than 8 digits (extension numbers, short codes).
* Numbers longer than 15 digits (E.164 maximum).
* Numbers with non-NANP-valid area or exchange codes (start with 0
  or 1) -- those are not real phone numbers.
"""
from __future__ import annotations

import re

# E.164: ``+`` then a leading non-zero country-code digit, then
# 7..14 more digits with optional separators between them
# (totalling 8..15 digits per the ITU spec). The separator class is
# intentionally wide so common stylistic forms work:
# ``+141****1234`` (compact), ``+1 415 555 1234`` (spaces),
# ``+1-415-555-1234`` (dashes), ``+1.415.555.1234`` (dots), and
# ``+1 (415) 555-1234`` (parens around the NANP area code). The
# canonical output is digits-only so the captured separators do not
# affect de-dup. The lookahead/lookbehind rejects runs that touch
# other digits so an internal serial like ``+12345678901234567890``
# (too long) does not match.
_E164_RE = re.compile(
    r"(?<![\d+])\+(?P<num>\d(?:[ .\-()]*\d){7,14})(?!\d)"
)

# NANP formatted: requires explicit formatting (parens, dash, dot,
# or space between the three groups) AND a valid 2-9 leading digit
# on both the area code and the exchange code. The ``(?<![\d.+\-])``
# left-boundary keeps the match from biting into a longer digit run.
_NANP_FORMATTED_RE = re.compile(
    r"(?<![\d.+\-])"
    r"(?:"
    # ``(NXX) NXX-XXXX`` and ``(NXX) NXX XXXX``
    r"\((?P<area_p>[2-9]\d{2})\)\s*(?P<exch_p>[2-9]\d{2})[\.\-\s](?P<sub_p>\d{4})"
    r"|"
    # ``NXX-NXX-XXXX``, ``NXX.NXX.XXXX``, ``NXX NXX XXXX`` with
    # MATCHED separator (dash with dash, dot with dot, space with
    # space) so a ``123.456-7890`` mix-and-match does not pass.
    r"(?P<area_d>[2-9]\d{2})-(?P<exch_d>[2-9]\d{2})-(?P<sub_d>\d{4})"
    r"|"
    r"(?P<area_dot>[2-9]\d{2})\.(?P<exch_dot>[2-9]\d{2})\.(?P<sub_dot>\d{4})"
    r"|"
    r"(?P<area_s>[2-9]\d{2})\s(?P<exch_s>[2-9]\d{2})\s(?P<sub_s>\d{4})"
    r")"
    r"(?!\d)"
)

# Keyword-prefixed bare NANP: matches a 10-digit run when an
# explicit phone-class keyword precedes it. We allow the bare run
# to also have NANP-style formatting; the keyword is the discriminator.
_KEYWORD_PHONE_RE = re.compile(
    r"\b(?:phone|tel(?:ephone)?|mobile|cell(?:phone)?|fax)\b"
    r"[:#\s.\-]*"
    r"(?P<num>[2-9]\d{2}[\.\-\s]?[2-9]\d{2}[\.\-\s]?\d{4})"
    r"(?!\d)",
    re.IGNORECASE,
)


_MAX_PHONES = 50


def _digits_only(s: str) -> str:
    """Strip every non-digit char from ``s``."""
    return re.sub(r"\D", "", s)


def extract_phones(text: str) -> list[str]:
    """Return unique phone numbers found in ``text``.

    Output entries are in canonical form: digits-only, with a leading
    ``+`` preserved for E.164 matches. Preserves first-seen order
    across all matchers (E.164 first, then NANP-formatted, then
    keyword-prefixed bare). De-dupes case-/format-insensitively
    (``+1 (415) 555-1234`` and ``+14155551234`` collapse to one entry,
    so do ``(415) 555-1234`` and ``415-555-1234``). Caps the output
    at 50 entries.
    """
    if not text or not isinstance(text, str):
        return []
    seen: set[str] = set()
    out: list[str] = []
    work = text

    def _consume(start: int, end: int) -> None:
        nonlocal work
        work = work[:start] + (" " * (end - start)) + work[end:]

    def _add(canonical: str, start: int, end: int) -> None:
        if canonical in seen or len(out) >= _MAX_PHONES:
            return
        seen.add(canonical)
        out.append(canonical)
        _consume(start, end)

    # 1) E.164 first -- the ``+`` prefix is unique enough that no
    #    other matcher would steal it, but consuming the span
    #    prevents a NANP-shaped tail (``+1-415-555-1234``) from
    #    re-matching as a bare NANP number.
    for m in list(_E164_RE.finditer(work)):
        digits = _digits_only(m.group("num"))
        if not (8 <= len(digits) <= 15):
            continue
        canonical = f"+{digits}"
        # Also pre-register the digits-only form so a follow-up
        # NANP match on the tail of the same number does not produce
        # a duplicate entry.
        if canonical not in seen:
            seen.add(canonical)
            # Register the trailing 10-digit form too so a follow-up
            # bare ``4155551234`` match cannot land as a separate
            # entry pointing at the same number.
            if len(digits) >= 10:
                seen.add(digits[-10:])
            out.append(canonical)
            if len(out) >= _MAX_PHONES:
                return out
        _consume(m.start(), m.end())

    # 2) NANP-formatted (parens, dashes, dots, spaces between groups).
    for m in list(_NANP_FORMATTED_RE.finditer(work)):
        digits = _digits_only(m.group(0))
        if len(digits) != 10:
            continue
        _add(digits, m.start(), m.end())

    # 3) Keyword-prefixed bare. The keyword itself is consumed so a
    #    subsequent regex run on the same text does not re-extract.
    for m in list(_KEYWORD_PHONE_RE.finditer(work)):
        digits = _digits_only(m.group("num"))
        if len(digits) != 10:
            continue
        # Validate NANP rules even when the keyword fronts the number,
        # so an ``ID: 1234567890`` style nonsense after a stray
        # ``phone`` word doesn't slip through. (The regex already
        # enforces ``[2-9]`` on the area / exchange, but a future
        # regex change shouldn't be allowed to silently weaken this.)
        if digits[0] in {"0", "1"} or digits[3] in {"0", "1"}:
            continue
        _add(digits, m.start("num"), m.end("num"))

    return out


__all__ = ["extract_phones"]
