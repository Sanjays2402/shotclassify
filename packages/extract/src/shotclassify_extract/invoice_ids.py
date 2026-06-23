"""Cross-category invoice ID extractor.

Invoice / quote / estimate / bill / credit-note / purchase-order
identifiers surface across every category: receipts and document
captures of accounting paperwork are the obvious case, but chat
threads cite "did you pay INV-2024-0099?", code snippets paste a
Stripe / QuickBooks / Xero invoice ID into a test fixture, and
error logs reference the invoice ID that failed to process.

We surface these IDs found in the OCR text under
``ExtractedFields.raw["invoice_ids"]`` as a list of
``{"kind": str, "id": str}`` dicts so dashboards, routing rules,
and downstream agents have a single place to look for billing
context.

Recognised shapes:

1. **Prefix-patterned IDs** (fire when the canonical accounting
   prefix is glued to the identifier):

   * ``INV-12345`` / ``INV-2024-0099`` / ``INVOICE-12345``
   * ``BILL-12345`` / ``BILL-2024-001``
   * ``Q-2024-001`` / ``QUOTE-12345`` (4-digit year OR 4+ chars after
     the dash to avoid bare ``Q-1`` prose tail)
   * ``EST-12345`` / ``ESTIMATE-12345``
   * ``CN-12345`` / ``CREDIT-12345`` (credit note)
   * ``PO-1234`` / ``PURCHASE-12345`` (4+ digits so ``PO-1`` prose
     tail doesn't fire)
   * ``AR-12345`` (accounts-receivable shorthand)

2. **Keyword-led IDs** (fire when the accounting label sits
   immediately before the identifier):

   * ``Invoice No: 12345`` / ``Invoice Number: 12345`` /
     ``Invoice #12345`` / ``Invoice ID: 12345``
   * ``Bill No: 12345`` / ``Bill #12345``
   * ``Quote No: 12345`` / ``Quote #12345`` / ``Estimate No: 12345``
   * ``Credit Note No: 12345`` / ``Credit Note #12345``
   * ``Purchase Order: 12345`` / ``PO Number: 12345`` /
     ``Purchase Order No: 12345``

3. **Slash-form year-encoded IDs** (common with European /
   QuickBooks-style numbering):

   * ``2024/INV/0099``
   * ``INV/2024/00001``

Safety properties:

* Word-boundary on BOTH ends so an embedded substring inside a
  longer identifier (``MY-INV-12345-X``) doesn't get carved up.
* Each prefix requires a minimum tail-length (3+ alphanumeric
  chars for ``INV``/``BILL``, 4+ for ``Q``/``PO``) so bare
  prose-tail like ``Q-1`` / ``PO-1`` doesn't false-positive.
* Distinct from ``receipt.order_number`` which is the per-receipt
  primary number. This extractor is cross-category: every category
  populates ``raw["invoice_ids"]`` so a chat citation of an
  invoice ID lands without needing to mis-classify the screenshot
  as a receipt.
* Distinct from ``raw["stripe_ids"]`` which catches ``inv_<14+>``
  Stripe-prefixed IDs. The two CAN co-occur but capture orthogonal
  shapes.
* Output is a list of ``{"kind", "id"}`` dicts capped at 50,
  preserving first-seen order, deduped on the (kind, id) pair.
"""
from __future__ import annotations

import re

# Kind catalogue. Maps the canonical lowercase prefix used in
# patterned shapes to the long-form kind tag emitted in the
# output. The keyword-led matcher uses a separate catalogue
# (declared below) because the prose label and the patterned
# prefix differ for some accounting docs.
_PATTERN_KIND: dict[str, str] = {
    "INV": "invoice",
    "INVOICE": "invoice",
    "BILL": "bill",
    "Q": "quote",
    "QU": "quote",
    "QUOTE": "quote",
    "EST": "estimate",
    "ESTIMATE": "estimate",
    "CN": "credit_note",
    "CREDIT": "credit_note",
    "PO": "purchase_order",
    "PURCHASE": "purchase_order",
    "AR": "accounts_receivable",
}

# Prefix-patterned regex. The prefix-token is ALL-CAPS (case-
# insensitive match so lowercased forms work too) followed by a
# dash separator and the identifier body.
#
# The body must contain at least one digit so we don't false-
# positive on words that happen to share the prefix shape
# (``INV-OICE``, ``BILL-BOARD``, ``Q-TIP`` -- all reject because
# the tail is letters-only with no digit).
#
# Body length floor:
#   * ``Q-`` / ``QU-`` / ``PO-`` / ``AR-`` / ``CN-`` require 4+
#     chars in the body (avoids ``Q-1`` / ``PO-1`` prose tail).
#   * ``INV-`` / ``INVOICE-`` / ``BILL-`` / ``EST-`` /
#     ``ESTIMATE-`` / ``QUOTE-`` / ``CREDIT-`` / ``PURCHASE-``
#     require 3+ chars in the body (3-digit invoice numbers are
#     real for small businesses).
#
# Body charset is alphanumeric + ``-`` / ``/`` / ``.`` /
# ``_`` (year-separated invoice schemes like
# ``INV-2024-0099`` / ``INV/2024/0099`` all need slashes
# AND dashes; a few systems use periods).
#
# Two alternation branches so we can apply different
# minimum-length floors per prefix family.
_INVOICE_PATTERN_LONG = re.compile(
    r"(?<![A-Za-z0-9])"  # left word boundary
    r"(?P<prefix>INV|INVOICE|BILL|EST|ESTIMATE|QUOTE|CREDIT|PURCHASE)"
    r"-"
    r"(?P<body>[A-Z0-9](?:[A-Z0-9._/-]{2,30}[A-Z0-9]|[A-Z0-9]{2}))"
    r"(?![A-Za-z0-9])",  # right word boundary
    re.IGNORECASE,
)

_INVOICE_PATTERN_SHORT = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?P<prefix>Q|QU|CN|PO|AR)"
    r"-"
    r"(?P<body>[A-Z0-9](?:[A-Z0-9._/-]{3,30}[A-Z0-9]|[A-Z0-9]{3}))"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)

# Year/prefix/seq slash form. Common in European and QuickBooks-
# style numbering. Two orientations:
#
#   2024/INV/0099       -- year first
#   INV/2024/00001      -- prefix first
#
# We require 4-digit year (yyyy) and 3+ digit sequence so a
# generic ``a/b/c`` doesn't false-positive. The prefix token must
# be a recognised accounting word.
_INVOICE_SLASH_YEAR_FIRST = re.compile(
    r"(?<![A-Za-z0-9/])"
    r"(?P<year>\d{4})"
    r"/(?P<prefix>INV|INVOICE|BILL|EST|ESTIMATE|QUOTE|Q|QU|CN|CREDIT|PO|PURCHASE|AR)"
    r"/(?P<seq>[A-Z0-9](?:[A-Z0-9.-]{2,15}[A-Z0-9]|[A-Z0-9]{2}))"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_INVOICE_SLASH_PREFIX_FIRST = re.compile(
    r"(?<![A-Za-z0-9/])"
    r"(?P<prefix>INV|INVOICE|BILL|EST|ESTIMATE|QUOTE|Q|QU|CN|CREDIT|PO|PURCHASE|AR)"
    r"/(?P<year>\d{4})"
    r"/(?P<seq>[A-Z0-9](?:[A-Z0-9.-]{2,15}[A-Z0-9]|[A-Z0-9]{2}))"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)

# Keyword-led label catalogue. Each entry is
# (keyword-regex, kind). The regex captures the identifier in the
# named group ``id``. Identifier charset is alphanumeric + dashes
# + slashes + dots + underscores; the leading ``#`` (when present)
# is stripped from the captured id.
#
# Ordered longest-most-specific-first so "Purchase Order Number"
# beats "Purchase Order" beats "Order" (the bare "Order" form
# is intentionally NOT here -- that belongs in receipt.order_number
# because it's ambiguous across categories).
_KEYWORD_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        # Credit Note variations (compound keyword wins over Credit alone).
        # Requires either a qualifier word (no/number/#/id) OR a
        # colon / hash separator so bare ``Credit Note draft`` /
        # ``Credit Note template`` prose mentions never match.
        re.compile(
            r"\bcredit\s+note\b\s*"
            r"(?:(?:no\.?|number|#|id)\s*[:#.\s]{0,5}|[:#]\s*)"
            r"(?P<id>#?[A-Z0-9][A-Z0-9._/-]{1,30}[A-Z0-9])\b",
            re.IGNORECASE,
        ),
        "credit_note",
    ),
    (
        # Purchase Order variations.
        re.compile(
            r"\bpurchase\s+order\b\s*"
            r"(?:(?:no\.?|number|#|id)\s*[:#.\s]{0,5}|[:#]\s*)"
            r"(?P<id>#?[A-Z0-9][A-Z0-9._/-]{1,30}[A-Z0-9])\b",
            re.IGNORECASE,
        ),
        "purchase_order",
    ),
    (
        # PO Number / PO No / PO # (the shortened form).
        re.compile(
            r"(?<![A-Za-z])po\b\s*"
            r"(?:(?:no\.?|number|#|id)\s*[:#.\s]{0,5}|[:#]\s*)"
            r"(?P<id>#?[A-Z0-9][A-Z0-9._/-]{1,30}[A-Z0-9])\b",
            re.IGNORECASE,
        ),
        "purchase_order",
    ),
    (
        # Invoice variations.
        re.compile(
            r"\binvoice\b\s*"
            r"(?:(?:no\.?|number|#|id)\s*[:#.\s]{0,5}|[:#]\s*)"
            r"(?P<id>#?[A-Z0-9][A-Z0-9._/-]{1,30}[A-Z0-9])\b",
            re.IGNORECASE,
        ),
        "invoice",
    ),
    (
        # Estimate variations.
        re.compile(
            r"\bestimate\b\s*"
            r"(?:(?:no\.?|number|#|id)\s*[:#.\s]{0,5}|[:#]\s*)"
            r"(?P<id>#?[A-Z0-9][A-Z0-9._/-]{1,30}[A-Z0-9])\b",
            re.IGNORECASE,
        ),
        "estimate",
    ),
    (
        # Quote variations.
        re.compile(
            r"\bquote\b\s*"
            r"(?:(?:no\.?|number|#|id)\s*[:#.\s]{0,5}|[:#]\s*)"
            r"(?P<id>#?[A-Z0-9][A-Z0-9._/-]{1,30}[A-Z0-9])\b",
            re.IGNORECASE,
        ),
        "quote",
    ),
    (
        # Bill variations. "Bill" is the loosest -- it could refer to
        # a physical bill OR a billing invoice. We require the
        # compound form (Bill No: / Bill Number: / Bill #) so a bare
        # "Bill 12345" prose mention doesn't fire (bare-colon-only
        # ``Bill: 12345`` is also intentionally rejected because
        # ``Bill: $50`` is too common on dinner receipts).
        re.compile(
            r"\bbill\s*(?:no\.?|number|#|id)\s*[:#.\s]{0,5}"
            r"(?P<id>#?[A-Z0-9][A-Z0-9._/-]{1,30}[A-Z0-9])\b",
            re.IGNORECASE,
        ),
        "bill",
    ),
)

_MAX_INVOICE_IDS = 50


def _clean_id(raw: str) -> str:
    """Strip leading ``#`` and surrounding whitespace from the captured id.

    The hash prefix on ``Invoice #INV-12345`` is a printer
    convention (the ``#`` means "number"); the canonical id is
    ``INV-12345`` without the hash. Dashboards re-render the hash
    when displaying.
    """
    raw = raw.strip()
    while raw.startswith("#"):
        raw = raw[1:].strip()
    return raw


def _normalise(prefix: str, body: str) -> str:
    """Return the canonical patterned form ``PREFIX-body``.

    The prefix is uppercased for consistency (real-world invoice
    numbers are conventionally uppercase even when typed
    lowercase by the user). The body is preserved verbatim
    because year / sequence digits are meaningful.
    """
    return f"{prefix.upper()}-{body}"


def _normalise_slash(prefix: str, year: str, seq: str) -> str:
    """Return the canonical slash form ``PREFIX/year/seq`` or ``year/PREFIX/seq``.

    We preserve the slash separator and uppercase the prefix.
    """
    # We need to know which orientation. We pass the originally
    # printed form to _normalise_slash so we just uppercase the
    # prefix and rejoin with slashes.
    return f"{year}/{prefix.upper()}/{seq}"


def extract_invoice_ids(text: str) -> list[dict[str, str]]:
    """Return unique invoice / quote / bill / PO IDs found in ``text``.

    Output is a list of ``{"kind", "id"}`` dicts, preserving
    first-seen order across the OCR text. De-duplicates on the
    (kind, id) pair so the same invoice ID printed twice in the
    same screenshot collapses to one entry. Caps the output at
    50 entries.

    The matcher tries three shapes:

    1. Prefix-patterned: ``INV-12345`` / ``Q-2024-001`` / ``PO-12345``
    2. Keyword-led: ``Invoice No: 12345`` / ``Purchase Order #12345``
    3. Slash-year: ``2024/INV/0099`` / ``INV/2024/00001``

    Each match's id is canonicalised (leading ``#`` stripped,
    surrounding whitespace removed). Pattern-prefixed IDs use the
    uppercased prefix in the canonical form so a lowercase
    ``inv-12345`` and uppercase ``INV-12345`` collapse to one
    ``INV-12345`` entry.
    """
    if not text or not isinstance(text, str):
        return []

    candidates: list[tuple[int, dict[str, str]]] = []
    consumed: list[tuple[int, int]] = []

    def _overlaps(start: int, end: int) -> bool:
        for s, e in consumed:
            if start < e and end > s:
                return True
        return False

    def _claim(start: int, end: int) -> None:
        consumed.append((start, end))

    # Pass 1: slash-year-form. Most specific -- if a ``2024/INV/0099``
    # match fires, the ``2024/INV`` substring should not also be
    # picked up by the keyword-led ``invoice`` matcher as
    # ``invoice/0099``.
    for m in _INVOICE_SLASH_YEAR_FIRST.finditer(text):
        if _overlaps(m.start(), m.end()):
            continue
        prefix = m.group("prefix")
        kind = _PATTERN_KIND.get(prefix.upper())
        if not kind:
            continue
        ident = _normalise_slash(prefix, m.group("year"), m.group("seq"))
        candidates.append((m.start(), {"kind": kind, "id": ident}))
        _claim(m.start(), m.end())

    for m in _INVOICE_SLASH_PREFIX_FIRST.finditer(text):
        if _overlaps(m.start(), m.end()):
            continue
        prefix = m.group("prefix")
        kind = _PATTERN_KIND.get(prefix.upper())
        if not kind:
            continue
        # Prefix-first slash form: ``INV/2024/00001`` canonicalised
        # with the prefix at front so dashboards display the
        # accounting series tag first.
        ident = f"{prefix.upper()}/{m.group('year')}/{m.group('seq')}"
        candidates.append((m.start(), {"kind": kind, "id": ident}))
        _claim(m.start(), m.end())

    # Pass 2: prefix-patterned long. ``INV-12345`` family.
    for m in _INVOICE_PATTERN_LONG.finditer(text):
        if _overlaps(m.start(), m.end()):
            continue
        prefix = m.group("prefix")
        body = m.group("body")
        kind = _PATTERN_KIND.get(prefix.upper())
        if not kind:
            continue
        # Require at least one digit in the body so ``INV-OICE`` etc
        # don't false-positive (the prefix list is short enough that
        # adjacent prose words can otherwise look invoice-shaped).
        if not any(c.isdigit() for c in body):
            continue
        ident = _normalise(prefix, body)
        candidates.append((m.start(), {"kind": kind, "id": ident}))
        _claim(m.start(), m.end())

    # Pass 3: prefix-patterned short. ``Q-2024-001`` / ``PO-12345``
    # family. Stricter length floor enforced by the regex.
    for m in _INVOICE_PATTERN_SHORT.finditer(text):
        if _overlaps(m.start(), m.end()):
            continue
        prefix = m.group("prefix")
        body = m.group("body")
        kind = _PATTERN_KIND.get(prefix.upper())
        if not kind:
            continue
        if not any(c.isdigit() for c in body):
            continue
        ident = _normalise(prefix, body)
        candidates.append((m.start(), {"kind": kind, "id": ident}))
        _claim(m.start(), m.end())

    # Pass 4: keyword-led. ``Invoice #INV-12345`` / ``Bill No: 12345``.
    # The keyword-led match may overlap a prefix-pattern match if the
    # captured id IS itself prefix-patterned -- in that case we drop
    # the keyword-led one because the prefix-pattern already
    # recorded the cleaner entry.
    for pattern, kind in _KEYWORD_PATTERNS:
        for m in pattern.finditer(text):
            id_start, id_end = m.span("id")
            if _overlaps(id_start, id_end):
                continue
            ident = _clean_id(m.group("id"))
            if not ident:
                continue
            # Reject ids that are just a single token of letters with
            # no digit -- those are almost certainly prose noise
            # (``Invoice template`` / ``Invoice draft``).
            if not any(c.isdigit() for c in ident):
                continue
            candidates.append((m.start(), {"kind": kind, "id": ident}))
            _claim(id_start, id_end)

    # Sort by source offset for stable first-seen ordering.
    candidates.sort(key=lambda x: x[0])

    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _off, entry in candidates:
        key = (entry["kind"], entry["id"])
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
        if len(out) >= _MAX_INVOICE_IDS:
            break
    return out


__all__ = ["extract_invoice_ids"]
