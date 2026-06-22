"""Cross-category postal-code extractor.

Postal codes show up across every category of screenshot --
addresses on receipts, customer info in code snippets, error pages
that cite a billing address, chat captures of shipping discussions,
and document captures of letters / invoices / forms. Rather than
teach each per-category extractor (or the LLM) to find postal
codes, we run :func:`extract_postal_codes` once on the OCR text and
stash the typed list under ``ExtractedFields.raw["postal_codes"]``
so dashboards and routing rules can group by country without
per-category coupling.

Output shape: a list of ``{"country", "code"}`` dicts. The
``country`` is the ISO 3166-1 alpha-2 country code (``US`` / ``CA``
/ ``GB`` / ``DE`` / ``FR`` etc.). The ``code`` is the postal code
in its canonical printed form for that country.

Recognised shapes (10 countries covering the most-printed formats):

* **US**: 5-digit (``94103``) or 5+4 ZIP (``94103-1234``). Requires
  a same-line state anchor (``CA`` / ``NY`` / etc.) because a bare
  5-digit run is too easy to confuse with other identifiers.
* **UK**: outward + inward postcode (``SW1A 1AA``, ``M1 1AE``,
  ``B33 8TH``, ``CR2 6XH``, ``DN55 1PT``, ``EC1A 1BB``).
  Self-anchored by the format -- no need for an extra anchor.
* **Canada**: ANA NAN (``K1A 0B1``, ``M5V 3L9``). Letters
  D/F/I/O/Q/U not used in first position; W/Z not used at all.
  Self-anchored.
* **Germany**: 5-digit (``10115``, ``80331``). Requires a same-line
  country/city anchor or a label (``PLZ:``, ``Deutschland``,
  ``Germany``, or one of the major-city names) because a 5-digit
  run alone matches US ZIPs.
* **France**: 5-digit (``75001``, ``13001``). Anchor required for
  the same reason.
* **Netherlands**: 4-digit + 2-letter (``1011 AB``).
* **Australia**: 4-digit (``2000`` / ``3000``). Anchor required
  because 4-digit codes are highly ambiguous; we accept an
  Australian state abbreviation on the same line (NSW / VIC / QLD
  / WA / SA / TAS / ACT / NT) or the country anchor.
* **Japan**: 7-digit with hyphen (``100-0001``).
* **India**: 6-digit (``110001``). Requires anchor (``India`` /
  ``IN`` / state name).
* **Brazil**: 5-digit + dash + 3-digit (``01310-100``).

Output entries are de-duped on the (country, code) pair. First-seen
order preserved. Capped at 50 entries.

The anchored shapes (US ZIP, German PLZ, French CP, Australian
postcode, Indian PIN) need a per-line anchor because bare digit
runs of those lengths false-positive too easily; the anchor list
for each country is documented in the module-level constants.

Deliberately NOT matched:

* Russian postal codes (6-digit, indistinguishable from Indian PIN
  without a strong anchor).
* Chinese postal codes (6-digit, same problem).
* Postal codes from countries that don't print them in standardised
  shapes (UAE, parts of Africa).
"""
from __future__ import annotations

import re

_MAX_POSTAL = 50

# ---- per-country regexes -------------------------------------------

# US ZIP: 5 digits, optionally followed by ``-`` + 4 digits.
_US_ZIP_RE = re.compile(r"(?<![\d.-])(?P<z>\d{5}(?:-\d{4})?)(?![\d-])")

# US state abbreviations (50 + DC + 5 territories). Used as the
# same-line anchor for the US ZIP matcher.
_US_STATES: frozenset[str] = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI",
    "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
    "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
    "VT", "VA", "WA", "WV", "WI", "WY", "DC", "PR", "VI", "GU", "AS",
    "MP",
})

# US-state anchor pattern: a 2-letter run, isolated by word boundaries,
# that sits BEFORE the ZIP on the same line.
_US_STATE_ANCHOR_RE = re.compile(r"\b([A-Z]{2})\b")

# UK postcode: outward + inward. The shapes:
#   * A9 9AA / A9A 9AA / AA9 9AA / AA9A 9AA / AA99 9AA / A99 9AA
# All collapsed into one tolerant pattern with the canonical
# inward part ``\d[A-Z]{2}`` and an outward part of 2..4 chars
# starting with 1..2 letters.
_UK_POSTCODE_RE = re.compile(
    r"\b"
    r"(?P<code>"
    r"[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}"
    r")"
    r"\b"
)

# Canadian: ANA NAN with the first-letter restriction. We accept the
# space variant and the unspaced variant; canonical output keeps the
# space.
_CA_POSTAL_RE = re.compile(
    r"(?<![\w-])"
    r"(?P<code>[A-CEGHJ-NPRSTVXY]\d[A-CEGHJ-NPRSTV-Z][ -]?\d[A-CEGHJ-NPRSTV-Z]\d)"
    r"(?![\w-])",
    re.IGNORECASE,
)

# German PLZ: 5 digits.
_DE_PLZ_RE = re.compile(r"(?<![\d.-])(?P<z>\d{5})(?![\d-])")
# German anchor: ``PLZ`` label, the words ``Deutschland`` / ``Germany``,
# or any of the 25 largest cities printed on a same-line address.
_DE_ANCHOR_RE = re.compile(
    r"\b(?:PLZ|Deutschland|Germany|Berlin|Hamburg|M[uü]nchen|Munich|"
    r"K[oö]ln|Cologne|Frankfurt|Stuttgart|D[uü]sseldorf|Dortmund|Essen|"
    r"Leipzig|Bremen|Dresden|Hannover|N[uü]rnberg|Nuremberg|Bonn|"
    r"M[uü]nster|Karlsruhe|Mannheim|Augsburg|Wiesbaden|Bielefeld)\b",
    re.IGNORECASE,
)

# French CP: 5 digits, but first 2 are the d[eé]partement (01..98 +
# 2A / 2B for Corsica). The naive regex still accepts 00xxx so we
# trim those in code.
_FR_CP_RE = re.compile(r"(?<![\d.-])(?P<z>\d{5})(?![\d-])")
# French anchor: ``France`` / ``CP`` / one of the major cities or
# regions.
_FR_ANCHOR_RE = re.compile(
    r"\b(?:France|CP|Paris|Lyon|Marseille|Toulouse|Nice|Nantes|"
    r"Strasbourg|Montpellier|Bordeaux|Lille|Rennes|Reims|Le Havre|"
    r"Saint[- ]Etienne|Toulon|Grenoble)\b",
    re.IGNORECASE,
)

# Netherlands: 4 digits + space + 2 uppercase letters.
_NL_POSTCODE_RE = re.compile(
    r"(?<![\w-])"
    r"(?P<code>\d{4}\s?[A-Z]{2})"
    r"(?![\w-])"
)

# Australia: 4 digits. Highly ambiguous so we require a same-line
# state anchor or the country anchor.
_AU_POSTCODE_RE = re.compile(r"(?<![\d.-])(?P<z>\d{4})(?![\d-])")
_AU_ANCHOR_RE = re.compile(
    r"\b(?:NSW|VIC|QLD|WA|SA|TAS|ACT|NT|Australia)\b",
    re.IGNORECASE,
)

# Japan: 7-digit with hyphen (``100-0001``). Self-anchored by the
# 3-4 split.
_JP_POSTCODE_RE = re.compile(
    r"(?<![\d-])"
    r"(?P<code>\d{3}-\d{4})"
    r"(?![\d-])"
)

# Indian PIN: 6 digits. Anchor required because Russian / Chinese /
# other-country 6-digit codes overlap.
_IN_PIN_RE = re.compile(r"(?<![\d.-])(?P<z>\d{6})(?![\d-])")
_IN_ANCHOR_RE = re.compile(
    r"\b(?:India|Mumbai|Delhi|Bangalore|Bengaluru|Chennai|Kolkata|"
    r"Hyderabad|Pune|Ahmedabad|Jaipur|Lucknow|Kanpur|Nagpur|Indore|"
    r"Surat|PIN|Pincode)\b",
    re.IGNORECASE,
)

# Brazilian CEP: 5 digits + dash + 3 digits.
_BR_CEP_RE = re.compile(
    r"(?<![\d-])"
    r"(?P<code>\d{5}-\d{3})"
    r"(?![\d-])"
)


def _line_for(text: str, pos: int) -> str:
    """Return the line in ``text`` that contains the character at ``pos``."""
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end == -1:
        end = len(text)
    return text[start:end]


def _has_us_state_anchor(line: str, zip_match: re.Match) -> bool:
    """True when an uppercase 2-letter state code sits on the same line."""
    # The state typically sits IMMEDIATELY before the ZIP (``San
    # Francisco, CA 94103``). We accept anywhere on the line for
    # robustness against OCR noise, but only count uppercase
    # two-letter runs that are real state codes.
    for m in _US_STATE_ANCHOR_RE.finditer(line):
        if m.group(1) in _US_STATES and m.start() < zip_match.start() - line_start_for(line, zip_match):
            # Conservative bound -- the state must sit BEFORE the ZIP
            # on the line, which is the printed convention.
            return True
        elif m.group(1) in _US_STATES:
            # Some lines flip the order (``94103 CA``); accept that too.
            return True
    return False


def line_start_for(line: str, m: re.Match) -> int:
    """Return the offset of ``m`` inside ``line`` based on the full match."""
    # This helper exists so the anchor check can compare positions
    # within the line, not within the full text. The match's
    # absolute position minus the line's start gives the in-line
    # offset; we approximate by re-finding the matched text in the
    # line (which is unambiguous because the ZIP regex requires
    # word boundaries).
    needle = m.group(0)
    idx = line.find(needle)
    return idx if idx >= 0 else 0


def _add(out: list[dict], seen: set, country: str, code: str) -> bool:
    """Append a (country, code) pair if not already present. Return True
    when the cap is reached."""
    key = (country, code)
    if key in seen:
        return False
    seen.add(key)
    out.append({"country": country, "code": code})
    return len(out) >= _MAX_POSTAL


def extract_postal_codes(text: str) -> list[dict]:
    """Return postal codes found in ``text``.

    Each entry is a ``{"country", "code"}`` dict. Preserves
    first-seen order. De-dupes on the (country, code) pair. Capped
    at 50 entries.

    Recognised countries: US, UK, CA, DE, FR, NL, AU, JP, IN, BR.
    Anchored shapes (US, DE, FR, AU, IN) require a same-line country
    / state / city anchor because their bare digit-runs are too
    common to land safely without one.
    """
    if not text or not isinstance(text, str):
        return []
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    candidates: list[tuple[int, str, str]] = []
    # Order matters here only for de-dupe priority; we collect all
    # candidates and then sort by source-text offset.

    # UK -- self-anchored (shape is unique).
    for m in _UK_POSTCODE_RE.finditer(text):
        code = m.group("code").upper()
        # Normalise spacing: outward + space + inward.
        if " " not in code:
            split_pt = len(code) - 3
            code = code[:split_pt] + " " + code[split_pt:]
        else:
            code = re.sub(r"\s+", " ", code)
        candidates.append((m.start(), "GB", code))

    # Canada -- self-anchored.
    for m in _CA_POSTAL_RE.finditer(text):
        code = m.group("code").upper()
        if " " not in code and "-" not in code:
            code = code[:3] + " " + code[3:]
        elif "-" in code:
            code = code.replace("-", " ")
        else:
            code = re.sub(r"\s+", " ", code)
        candidates.append((m.start(), "CA", code))

    # Japan -- self-anchored by the 3-4 hyphenated shape.
    for m in _JP_POSTCODE_RE.finditer(text):
        candidates.append((m.start(), "JP", m.group("code")))

    # Brazil -- self-anchored by the 5-3 hyphenated shape.
    for m in _BR_CEP_RE.finditer(text):
        candidates.append((m.start(), "BR", m.group("code")))

    # Netherlands -- self-anchored (4-digit + space + 2-letter is
    # unique enough). We normalise to a single space.
    for m in _NL_POSTCODE_RE.finditer(text):
        code = m.group("code").upper()
        if " " not in code:
            code = code[:4] + " " + code[4:]
        else:
            code = re.sub(r"\s+", " ", code)
        candidates.append((m.start(), "NL", code))

    # US ZIP -- requires a same-line state anchor.
    for m in _US_ZIP_RE.finditer(text):
        line = _line_for(text, m.start())
        # Only count 2-letter uppercase tokens that match a real US
        # state. Position relative to ZIP is permissive (state
        # printed before OR after).
        ok = False
        for sm in _US_STATE_ANCHOR_RE.finditer(line):
            if sm.group(1) in _US_STATES:
                ok = True
                break
        if not ok:
            continue
        candidates.append((m.start(), "US", m.group("z")))

    # Germany -- 5-digit + anchor on same line.
    for m in _DE_PLZ_RE.finditer(text):
        line = _line_for(text, m.start())
        if not _DE_ANCHOR_RE.search(line):
            continue
        # Guard against double-counting US 5-digit ZIPs that ALSO
        # have a US state anchor on the line.
        if _US_STATE_ANCHOR_RE.search(line):
            for sm in _US_STATE_ANCHOR_RE.finditer(line):
                if sm.group(1) in _US_STATES:
                    # US wins because the state anchor is more specific.
                    break
            else:
                candidates.append((m.start(), "DE", m.group("z")))
            continue
        candidates.append((m.start(), "DE", m.group("z")))

    # France -- 5-digit + anchor. Same disambiguation against US.
    for m in _FR_CP_RE.finditer(text):
        line = _line_for(text, m.start())
        if not _FR_ANCHOR_RE.search(line):
            continue
        if _US_STATE_ANCHOR_RE.search(line):
            for sm in _US_STATE_ANCHOR_RE.finditer(line):
                if sm.group(1) in _US_STATES:
                    break
            else:
                candidates.append((m.start(), "FR", m.group("z")))
            continue
        # Reject ``00xxx`` (departement 0 doesn't exist).
        if m.group("z").startswith("00"):
            continue
        candidates.append((m.start(), "FR", m.group("z")))

    # Australia -- 4-digit + anchor.
    for m in _AU_POSTCODE_RE.finditer(text):
        line = _line_for(text, m.start())
        if not _AU_ANCHOR_RE.search(line):
            continue
        candidates.append((m.start(), "AU", m.group("z")))

    # India -- 6-digit + anchor.
    for m in _IN_PIN_RE.finditer(text):
        line = _line_for(text, m.start())
        if not _IN_ANCHOR_RE.search(line):
            continue
        candidates.append((m.start(), "IN", m.group("z")))

    candidates.sort(key=lambda x: x[0])
    for _off, country, code in candidates:
        if _add(out, seen, country, code):
            break
    return out


__all__ = ["extract_postal_codes"]
