"""Cross-category academic / publishing identifier extractor.

Document captures and code snippets routinely reference identifiers
that point at external sources -- ISBNs on book photos, DOIs in
academic paper screenshots, arXiv IDs in research notes, ISSNs on
journal mastheads. Rather than teach each per-category extractor
(or the LLM) to find them, we run :func:`extract_identifiers` once
on the OCR text and stash the typed list under
``ExtractedFields.raw["identifiers"]`` so dashboards and routing
rules can group by ``ISBN`` / ``DOI`` / ``arXiv`` / ``ISSN``
without per-category coupling.

Output shape: a list of ``{"type": str, "value": str}`` dicts.
The list is JSON-serialisable (it's what the storage layer persists
as a JSON column) and preserves first-seen order across all matchers.

Recognised identifier types:

* **ISBN-13**: ``978-3-16-148410-0`` / ``9783161484100``. Validated
  via the EAN-13 check digit so a random 13-digit number doesn't
  pass.
* **ISBN-10**: ``0-306-40615-2`` / ``0306406152``. Validated via the
  mod-11 check digit (final digit may be ``X``).
* **DOI**: ``10.<reg>/<suffix>`` per the Crossref pattern. The prefix
  is always ``10.`` followed by 4-9 digits, slash, then a printable
  identifier. We strip a trailing ``).,;`` since DOIs sit at the end
  of sentences a lot.
* **arXiv**: both legacy (``arXiv:hep-th/9901002``) and new
  (``arXiv:2306.12345``) forms. The leading ``arXiv:`` is required;
  bare ``2306.12345`` patterns are too easy to confuse with version
  strings.
* **ISSN**: ``1234-5678`` (8 digits, dash in the middle, mod-11
  check digit, final may be ``X``). Often printed on journal
  mastheads alongside a DOI.

Each identifier type is checked in order most-specific-first so a
DOI that contains digits cannot be re-extracted as an ISBN. Spans
already consumed by an earlier matcher are masked before the next
one runs.
"""
from __future__ import annotations

import re

_MAX_IDENTIFIERS = 50

# ---- ISBN-13 -----------------------------------------------------------

# Allow the canonical hyphen / space separators commonly printed on
# book backs. We capture both raw forms and normalise to the
# digits-only form for storage so dashboards de-dupe cleanly.
_ISBN13_RE = re.compile(
    r"(?<![\d-])(?:97[89])(?:[-\s]?\d){10}(?![\d-])"
)
# ISBN-10: 9 digits + check (which may be ``X``). Same separator rules.
_ISBN10_RE = re.compile(
    r"(?<![\d-])\d(?:[-\s]?\d){8}[-\s]?[\dXx](?![\d\w-])"
)


def _isbn13_valid(digits: str) -> bool:
    """EAN-13 check digit: alternating 1/3 weights summed to a multiple of 10."""
    if len(digits) != 13 or not digits.isdigit():
        return False
    total = sum(
        int(d) * (3 if i % 2 else 1) for i, d in enumerate(digits[:-1])
    )
    check = (10 - (total % 10)) % 10
    return check == int(digits[-1])


def _isbn10_valid(digits: str) -> bool:
    """ISBN-10 mod-11 check, with ``X`` representing 10 in the final slot."""
    if len(digits) != 10:
        return False
    body = digits[:-1]
    last = digits[-1].upper()
    if not body.isdigit() or (not last.isdigit() and last != "X"):
        return False
    total = sum(int(d) * (10 - i) for i, d in enumerate(body))
    total += 10 if last == "X" else int(last)
    return total % 11 == 0


def _normalise_isbn(raw: str) -> str:
    """Drop separators; preserve a trailing ``X`` for ISBN-10."""
    return re.sub(r"[\s-]", "", raw).upper()


# ---- DOI ---------------------------------------------------------------

# DOI: ``10.<4-9 digits>/<suffix>``. The suffix is a non-whitespace,
# non-quote, non-bracket blob. We grab greedily and then trim trailing
# sentence punctuation at extraction time because DOI suffixes
# legitimately contain dots (``10.1145/3372297.3417883``) so we
# cannot stop the regex at the first ``.``.
_DOI_RE = re.compile(
    r"(?<![\w/])(10\.\d{4,9}/[^\s\"'<>()\[\]{}]+)",
    re.IGNORECASE,
)


# ---- arXiv -------------------------------------------------------------

# arXiv legacy: subject-class/identifier (``hep-th/9901002``).
# arXiv new: ``YYMM.NNNNN`` (4-5 digit identifier post 2007). The
# leading ``arXiv:`` is required to avoid false positives on bare
# version-like patterns.
_ARXIV_NEW_RE = re.compile(
    r"\barXiv:\s*(?P<id>\d{4}\.\d{4,5}(?:v\d+)?)\b",
    re.IGNORECASE,
)
_ARXIV_OLD_RE = re.compile(
    r"\barXiv:\s*(?P<id>[a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)\b",
    re.IGNORECASE,
)


# ---- ISSN --------------------------------------------------------------

_ISSN_RE = re.compile(r"(?<![\d-])\d{4}-\d{3}[\dXx](?![\d-])")


def _issn_valid(text: str) -> bool:
    """ISSN check digit: weighted sum mod 11; final may be ``X`` = 10."""
    body = text.replace("-", "")
    if len(body) != 8:
        return False
    digits = body[:-1]
    last = body[-1].upper()
    if not digits.isdigit() or (not last.isdigit() and last != "X"):
        return False
    total = sum(int(d) * (8 - i) for i, d in enumerate(digits))
    total += 10 if last == "X" else int(last)
    return total % 11 == 0


# ---- public API --------------------------------------------------------


def extract_identifiers(text: str) -> list[dict[str, str]]:
    """Return a list of ``{"type", "value"}`` identifiers found in text.

    Iterates matchers in priority order (arXiv > DOI > ISBN-13 >
    ISBN-10 > ISSN), masking each consumed span before the next
    matcher runs so a DOI body cannot also tag as an ISBN. Validates
    check digits for ISBN / ISSN. Preserves first-seen order. Caps
    the output at 50 entries.

    Each entry uses the canonical type tag (``ISBN``, ``DOI``,
    ``arXiv``, ``ISSN``) so dashboards can group with a stable
    enum. The value field carries the normalised form -- ISBN
    digits-only (with X preserved), DOI as printed, arXiv with the
    ``arXiv:`` prefix stripped, ISSN with the dash kept (canonical).
    """
    if not text or not isinstance(text, str):
        return []
    work = text
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(type_: str, value: str, start: int, end: int) -> None:
        nonlocal work
        key = (type_, value)
        if key in seen:
            return
        if len(out) >= _MAX_IDENTIFIERS:
            return
        seen.add(key)
        out.append({"type": type_, "value": value})
        work = work[:start] + (" " * (end - start)) + work[end:]

    # 1) arXiv first -- the ``arXiv:`` prefix is unique enough that no
    #    other matcher would steal it, but masking guarantees no
    #    overlap with downstream DOI / ISBN matches.
    for m in list(_ARXIV_NEW_RE.finditer(work)):
        _add("arXiv", m.group("id"), m.start(), m.end())
    for m in list(_ARXIV_OLD_RE.finditer(work)):
        _add("arXiv", m.group("id"), m.start(), m.end())

    # 2) DOI -- second so the ``10.<digits>/`` shape never tags as an
    #    ISBN (a DOI body can contain 10+ digits).
    for m in list(_DOI_RE.finditer(work)):
        doi = m.group(1)
        # Strip a final trailing ``).,;`` punctuation that the
        # lookahead skipped because the lookahead's character class
        # is checked WITHOUT consuming the char. DOIs almost always
        # end mid-sentence with a period or close-paren.
        while doi and doi[-1] in ".,;)":
            doi = doi[:-1]
        if doi:
            _add("DOI", doi, m.start(), m.start() + len(doi))

    # 3) ISBN-13 -- check the EAN-13 check digit; reject otherwise so
    #    a barcode-looking 13-digit run doesn't false-positive.
    for m in list(_ISBN13_RE.finditer(work)):
        normalised = _normalise_isbn(m.group(0))
        if _isbn13_valid(normalised):
            _add("ISBN", normalised, m.start(), m.end())

    # 4) ISBN-10 -- mod-11 check with X-as-10 allowed in the final
    #    slot. Run AFTER ISBN-13 so a 13-digit run is not partially
    #    consumed as a 10-digit ISBN.
    for m in list(_ISBN10_RE.finditer(work)):
        normalised = _normalise_isbn(m.group(0))
        if _isbn10_valid(normalised):
            _add("ISBN", normalised, m.start(), m.end())

    # 5) ISSN -- 4-3-1 digit groups with a mod-11 check; last may be X.
    for m in list(_ISSN_RE.finditer(work)):
        canonical = m.group(0).upper()
        if _issn_valid(canonical):
            _add("ISSN", canonical, m.start(), m.end())

    return out


__all__ = ["extract_identifiers"]
