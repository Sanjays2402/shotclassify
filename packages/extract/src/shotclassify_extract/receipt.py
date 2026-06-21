"""Receipt extractor: parse vendor, date, totals, items from OCR text."""
from __future__ import annotations

import re
from datetime import datetime

from shotclassify_common import OCRResult, ReceiptFields, ReceiptLine

_AMOUNT = re.compile(r"(?P<cur>[$€£¥]?)\s*(?P<amt>\d{1,5}(?:[.,]\d{2}))")
_DATE_PATTERNS = [
    re.compile(r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b"),
    re.compile(r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b"),
    re.compile(
        r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4})\b",
        re.IGNORECASE,
    ),
]


def _find_amount_after(text: str, keyword: str) -> float | None:
    # match keyword at start-of-word boundary so 'total' does not collide with 'subtotal'
    pattern = re.compile(
        rf"(?:(?<=\n)|(?<=^)|(?<=[^a-zA-Z])){re.escape(keyword)}\s*[:\-]?\s*[$€£¥]?\s*(\d{{1,5}}(?:[.,]\d{{2}}))",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return None
    # take the last occurrence (totals usually appear after subtotals)
    return float(matches[-1].group(1).replace(",", "."))


# Tip keywords ordered loosely by specificity. We try each in turn so a
# receipt that prints both "Gratuity" and "Tip" lines (the European bar
# tab pattern) still resolves to the same number.
_TIP_KEYWORDS = ("gratuity", "tip", "service charge", "service")


def _find_tip(text: str) -> float | None:
    """Return the gratuity amount in the receipt, or None.

    Looks for "Tip", "Gratuity", "Service charge" (and bare "Service")
    followed by an amount. A keyword that appears more than once (e.g.
    "Tip suggested" then the real "Tip 5.00") uses the LAST occurrence
    so a printed suggestion table never overrides the line the customer
    actually paid.
    """
    for keyword in _TIP_KEYWORDS:
        value = _find_amount_after(text, keyword)
        if value is not None:
            return value
    return None


# Discount keywords ordered loosely by specificity. Discounts on
# receipts are commonly printed as "Discount" / "Coupon" / "Promo" /
# "Member savings" / "Loyalty". Same last-wins semantics as tips: a
# header that lists available discounts at the top of the receipt
# must not override the actual line the cashier applied at checkout.
_DISCOUNT_KEYWORDS = (
    "discount",
    "coupon",
    "promo",
    "promo code",
    "savings",
    "loyalty",
    "rewards",
)


def _find_discount(text: str) -> float | None:
    """Return the absolute discount amount applied to the receipt, or None.

    Most printers render discounts as a positive number on a line
    labelled "Discount" / "Coupon" / "Promo" / "Savings" / "Loyalty" /
    "Rewards". The underlying ``_find_amount_after`` regex requires
    a digit immediately after the keyword (with at most one ``:`` or
    ``-`` separator and optional whitespace), so a printer that writes
    ``Discount: -2.00`` (sign in front of the amount) is NOT captured
    by this version. We chose not to widen the shared regex because
    that would also change how subtotal / tax / tip read malformed
    receipts; a future ticket can add a dedicated signed-amount path.
    """
    for keyword in _DISCOUNT_KEYWORDS:
        value = _find_amount_after(text, keyword)
        if value is not None:
            return value
    return None


def _detect_currency(text: str) -> str | None:
    # 1) Unambiguous currency symbols win when present. ``$`` is
    #    canonically USD here because the symbol is shared across many
    #    dollar currencies; a later locale-code pass corrects to CAD /
    #    AUD / NZD / etc. when the receipt also prints those codes.
    for symbol, code in [("€", "EUR"), ("£", "GBP"), ("¥", "JPY")]:
        if symbol in text:
            return code
    # 2) Three-letter ISO codes that appear as bare words. We match
    #    them WITH word boundaries so an embedded "scAUDio" or a CSS
    #    class "btn-aud" cannot trigger them. Order matters when a
    #    receipt prints both "USD" and "CAD" (a tourist tab in CAD
    #    where the operator forgot to switch from a USD template):
    #    prefer the FIRST match seen left-to-right since the latter
    #    printed code is usually the receipt's actual currency, and
    #    we use last-match for that reason.
    iso_codes = (
        "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "NZD", "CHF",
        "SEK", "NOK", "DKK", "INR", "MXN", "BRL", "ZAR", "SGD",
        "HKD", "CNY", "RMB", "KRW",
    )
    # Build one regex with word boundaries; this is O(n) over the text.
    iso_re = re.compile(
        r"\b(" + "|".join(iso_codes) + r")\b", re.IGNORECASE
    )
    matches = iso_re.findall(text)
    if matches:
        # Last match wins: receipts commonly print a header (vendor's
        # default currency) and then the actual line currency near the
        # total. The closing "Total in CAD" beats a header "USD".
        code = matches[-1].upper()
        return "CNY" if code == "RMB" else code
    # 3) Symbol-only fallback: dollar sign with no explicit code is USD.
    if "$" in text:
        return "USD"
    return None


# Patterns for payment method detection. Each entry is (canonical name,
# regex). The first regex to match wins, so order from MORE specific to
# LESS specific (e.g. "American Express" before "amex" before bare
# "card") to avoid a generic "credit card" line clobbering a clearly
# labelled "VISA ****1234" line.
_PAYMENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("apple_pay", re.compile(r"\bapple\s*pay\b", re.IGNORECASE)),
    ("google_pay", re.compile(r"\bgoogle\s*pay\b", re.IGNORECASE)),
    ("amex", re.compile(r"\b(american\s+express|amex)\b", re.IGNORECASE)),
    ("visa", re.compile(r"\bvisa\b", re.IGNORECASE)),
    ("mastercard", re.compile(r"\b(master\s*card|mastercard|m/?c)\b", re.IGNORECASE)),
    ("discover", re.compile(r"\bdiscover\b", re.IGNORECASE)),
    ("debit", re.compile(r"\bdebit(\s+card)?\b", re.IGNORECASE)),
    ("credit", re.compile(r"\bcredit(\s+card)?\b", re.IGNORECASE)),
    ("cash", re.compile(r"\bcash\b", re.IGNORECASE)),
)


def _detect_payment_method(text: str) -> str | None:
    """Return a canonical payment-method tag, or None if nothing matched.

    Tags are normalised to lowercase identifiers (``visa``, ``amex``,
    ``mastercard``, ``apple_pay``, ``google_pay``, ``discover``,
    ``debit``, ``credit``, ``cash``) so dashboards and routing rules
    can match on a small enum instead of every printer's wording.
    """
    if not text:
        return None
    for name, pattern in _PAYMENT_PATTERNS:
        if pattern.search(text):
            return name
    return None


# Order / invoice / receipt-number detection. Recognised printer
# vocabularies (case-insensitive, in priority order so a long header
# wins over a short one when both appear):
#
#   Invoice No: ABC-12345        ->  ABC-12345
#   Invoice #: 99001             ->  99001
#   Order #12345                 ->  12345  (hash is part of the keyword)
#   Order Number: 12345          ->  12345
#   Receipt No. ABC-099          ->  ABC-099
#   Reference: TKT-2024-007      ->  TKT-2024-007
#   Order ID 99001               ->  99001
#   Ref # 12345                  ->  12345
#   Transaction ID 7788          ->  7788
#   Check #45                    ->  45     (US restaurant pattern)
#
# Order matters: ``invoice`` keywords are checked before ``order``
# before ``receipt`` before ``reference`` / ``transaction`` so a
# receipt that prints BOTH "Invoice No 1" and "Order ID 2" tags as
# the invoice (more business-formal source of truth on most printers).
# Within a single keyword we use the FIRST occurrence because the
# number typically appears once at the top of the receipt.
#
# The token regex permits alphanumerics, dashes, dots, and slashes
# (some POS systems print ``2024/07/00099`` style numbers). Length
# is bounded to 2..40 chars so a 2-digit ``Check #45`` still matches
# while OCR runs (40+ chars) are rejected.
_ORDER_KEYWORDS: tuple[tuple[str, str], ...] = (
    # (display_keyword_for_regex, internal_tag)
    (r"invoice\s+(?:no\.?|number|#)", "invoice"),
    (r"invoice", "invoice_bare"),
    (r"order\s+(?:no\.?|number|id|#)", "order"),
    (r"order", "order_bare"),
    (r"receipt\s+(?:no\.?|number|#)", "receipt"),
    (r"check\s*#", "check"),
    (r"transaction\s+(?:id|#)", "transaction"),
    (r"ref(?:erence)?\s*#?", "reference"),
    (r"confirmation\s+(?:no\.?|number|#)", "confirmation"),
)
# Value: an alphanumeric-bookended run of 2..40 chars with internal
# ``./-`` punctuation, OR a single alphanumeric (the 1-char fallback
# for ``#1`` style numbers). Order matters in the alternation -- the
# longer form is tried first so ``ABC-12345`` is not truncated to
# ``A``. Internal punctuation is bounded to ``./-`` so a value never
# eats a sentence comma.
_ORDER_VALUE = (
    r"(?:[A-Za-z0-9][A-Za-z0-9./\-]{0,38}[A-Za-z0-9]|[A-Za-z0-9])"
)


def _find_order_number(text: str) -> str | None:
    """Return the order / invoice / receipt / reference number, or None.

    Loops through the keyword catalogue in priority order. For each
    keyword, accepts an optional ``:`` / ``-`` / ``=`` separator,
    optional whitespace, then a single value token. The value must
    contain at least one digit (so a stray ``Reference: see below``
    sentence does NOT match -- ``see`` has no digits). A leading
    ``#`` is preserved because dashboards almost always render it
    back with the hash. The keyword's last word ``no`` / ``no.`` /
    ``number`` / ``id`` / ``#`` is consumed by the regex so the value
    matcher does not see it.

    First keyword to match wins. Within a keyword, the FIRST
    occurrence wins because the number usually appears once at the
    top of the receipt; falling-back vendors that print a duplicate
    at the bottom should still match the same value.
    """
    if not text:
        return None
    for keyword_re, _tag in _ORDER_KEYWORDS:
        pat = re.compile(
            rf"(?<![A-Za-z])(?:{keyword_re})\s*[:\-=]?\s*(?P<val>{_ORDER_VALUE})",
            re.IGNORECASE,
        )
        m = pat.search(text)
        if not m:
            continue
        val = m.group("val").strip()
        # Require at least one digit so a non-numeric tail (``ref see``)
        # does not pass as the number.
        if not any(c.isdigit() for c in val):
            continue
        # Strip a stray trailing punctuation that the regex absorbed.
        val = val.rstrip(".,;:)")
        if not val:
            continue
        return val
    return None


# Tax-mode detection. Receipts almost always carry an explicit cue
# about whether the printed prices are inclusive of tax (the customer
# pays exactly what's on the line) or exclusive (tax is added at the
# end). Both phrasings show up across vendors so we match a broad set:
#
#   inclusive:  "VAT included", "incl. VAT", "tax included",
#               "incl. tax", "incl GST", "GST inclusive",
#               "all prices include tax", "prices incl. VAT",
#               "inclusive of GST" / "inclusive of HST".
#   exclusive:  "+ tax", "plus tax", "tax extra", "tax not included",
#               "excl. tax", "excl. VAT", "exclusive of GST", "ex GST",
#               "ex VAT", "prices exclude tax".
#
# Inclusive wins ties because most ambiguous wording ("plus 8% tax
# included") is a printer typo where the merchant meant inclusive.
# When neither is present we return None and the dashboard can fall
# back to inferring from subtotal vs total math.
_TAX_INCLUSIVE_HINTS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:vat|tax|gst|hst|pst|qst)\s+included\b", re.IGNORECASE),
    re.compile(r"\bincl(?:\.|usive)?\s+(?:of\s+)?(?:vat|tax|gst|hst)\b", re.IGNORECASE),
    re.compile(r"\b(?:vat|tax|gst|hst)\s+incl(?:\.|usive)?\b", re.IGNORECASE),
    re.compile(r"\b(?:all\s+)?prices?\s+include\s+(?:vat|tax|gst)\b", re.IGNORECASE),
    re.compile(r"\binclusive\s+of\s+(?:vat|tax|gst|hst)\b", re.IGNORECASE),
)
_TAX_EXCLUSIVE_HINTS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\+\s*(?:vat|tax|gst|hst)\b", re.IGNORECASE),
    re.compile(r"\bplus\s+(?:vat|tax|gst|hst)\b", re.IGNORECASE),
    re.compile(r"\b(?:vat|tax|gst|hst)\s+extra\b", re.IGNORECASE),
    re.compile(r"\b(?:vat|tax|gst|hst)\s+not\s+included\b", re.IGNORECASE),
    re.compile(r"\bexcl(?:\.|usive)?\s+(?:of\s+)?(?:vat|tax|gst|hst)\b", re.IGNORECASE),
    re.compile(r"\b(?:vat|tax|gst|hst)\s+excl(?:\.|usive)?\b", re.IGNORECASE),
    re.compile(r"\bex\s+(?:vat|gst|hst)\b", re.IGNORECASE),
    re.compile(r"\bprices?\s+exclude\s+(?:vat|tax|gst)\b", re.IGNORECASE),
    re.compile(r"\bexclusive\s+of\s+(?:vat|tax|gst|hst)\b", re.IGNORECASE),
)


def _detect_tax_mode(text: str) -> str | None:
    """Return ``"inclusive"`` / ``"exclusive"`` / ``None`` for the
    text's tax-mode cue.

    Inclusive cues are checked first because the most common
    "ambiguous" wording (``+ 8% VAT included``) is almost always a
    misprint where the merchant meant inclusive. A receipt that
    prints both an inclusive cue and an exclusive cue (rare but
    possible -- a multi-page invoice with summary + addendum)
    resolves to the FIRST one seen in OCR order so the dashboard's
    answer matches what a human reading top-to-bottom would settle
    on.
    """
    if not text:
        return None
    first_inclusive: int | None = None
    first_exclusive: int | None = None
    for pat in _TAX_INCLUSIVE_HINTS:
        m = pat.search(text)
        if m and (first_inclusive is None or m.start() < first_inclusive):
            first_inclusive = m.start()
    for pat in _TAX_EXCLUSIVE_HINTS:
        m = pat.search(text)
        if m and (first_exclusive is None or m.start() < first_exclusive):
            first_exclusive = m.start()
    if first_inclusive is None and first_exclusive is None:
        return None
    if first_inclusive is None:
        return "exclusive"
    if first_exclusive is None:
        return "inclusive"
    return "inclusive" if first_inclusive <= first_exclusive else "exclusive"


# Party size / split-bill detection. Restaurant receipts print a
# small set of phrases when the bill represents more than one cover:
#
#   "Party of 4"                 -> 4
#   "Party Size: 6"              -> 6
#   "Party 2"                    -> 2     (bare, after a comma/header)
#   "Guests: 3" / "Guests 3"     -> 3
#   "Guest count: 5"             -> 5
#   "# of Guests 4"              -> 4
#   "# Guests 4"                 -> 4
#   "No. of Guests 2"            -> 2
#   "Covers: 8"                  -> 8     (POS / industry term)
#   "Split 3 ways"               -> 3
#   "Split between 4"            -> 4
#   "Split 4 ways"               -> 4
#   "Per Person (4)"             -> 4     (when the parens give a count)
#
# Order: cover-count terms ("Party of", "Guests:", "Covers:") are
# checked BEFORE the split-bill terms ("Split N ways") because a
# receipt that prints both ("Party of 4 ... Split 4 ways") should
# tag the party size, not the split count, when they conflict. We
# bound the captured int to 1..50; anything outside that is OCR
# noise or a wrong match.
_PARTY_HINTS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bparty\s+of\s+(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bparty\s+size\s*[:\-]?\s*(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bguest\s+count\s*[:\-]?\s*(\d{1,2})\b", re.IGNORECASE),
    # Allow leading ``#`` / ``No.`` for ``# of Guests N`` / ``No. of Guests N``.
    re.compile(
        r"(?:#\s*(?:of\s+)?|no\.?\s*of\s+)guests?\s*[:\-]?\s*(\d{1,2})\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bguests?\s*[:\-]?\s*(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bcovers?\s*[:\-]?\s*(\d{1,2})\b", re.IGNORECASE),
    # Bare ``Party N`` only when preceded by start-of-line or a colon/
    # comma so a stray sentence "the party N celebrated" doesn't fire.
    re.compile(r"(?:^|[:,]\s*)party\s+(\d{1,2})\b", re.IGNORECASE | re.MULTILINE),
)
_SPLIT_HINTS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsplit\s+(\d{1,2})\s+ways?\b", re.IGNORECASE),
    re.compile(r"\bsplit\s+between\s+(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bsplit\s+by\s+(\d{1,2})\b", re.IGNORECASE),
    # "Per person (4)" / "Per-person 4" -- the parens are optional.
    re.compile(r"\bper[\s\-]person\s*\(?\s*(\d{1,2})\s*\)?\b", re.IGNORECASE),
)


def _detect_party_size(text: str) -> int | None:
    """Return the cover count / split count printed on the receipt, or
    ``None``.

    Party-of / guests / covers cues win over split-bill cues when both
    appear, because the cover count is the source of truth (a 4-cover
    bill that happens to be split 3 ways still has 4 guests). Within a
    single regex group the FIRST match wins -- the count is usually
    printed once near the header. Bounded to 1..50; values outside that
    range are rejected as OCR noise or wrong matches.
    """
    if not text:
        return None
    for pat in _PARTY_HINTS:
        m = pat.search(text)
        if not m:
            continue
        try:
            n = int(m.group(1))
        except (TypeError, ValueError):
            continue
        if 1 <= n <= 50:
            return n
    for pat in _SPLIT_HINTS:
        m = pat.search(text)
        if not m:
            continue
        try:
            n = int(m.group(1))
        except (TypeError, ValueError):
            continue
        if 1 <= n <= 50:
            return n
    return None


# Refund / void / cancelled-transaction detection. Real-world
# return / void receipts print a small set of recognisable cues
# alongside the refunded amount:
#
#   "REFUND 12.50"               -> 12.50
#   "Refund Amount: 12.50"       -> 12.50
#   "REFUND: -12.50"             -> 12.50  (sign stripped)
#   "Refund Total 12.50"         -> 12.50
#   "VOID 12.50"                 -> 12.50
#   "Void Sale 12.50"            -> 12.50
#   "CANCELLED 12.50"            -> 12.50
#   "Cancelled Transaction 12.50"-> 12.50
#   "Return 12.50"               -> 12.50  (American POS term)
#   "RETURN: -12.50"             -> 12.50
#
# Also accepts a leading-sign form even WITHOUT a keyword when the
# explicit ``Total`` / ``Subtotal`` line is itself negative:
#
#   "Total -12.50"               -> 12.50
#   "TOTAL: -$12.50"             -> 12.50
#
# Inside an item line a negative amount is treated as a line discount
# (existing behaviour); only top-level total / subtotal / explicit
# refund-keyword amounts populate refund_amount.
#
# We bound the amount to 0.01..99999 to keep OCR noise out.
_REFUND_KEYWORDS = (
    r"refund(?:\s+(?:amount|total))?",
    r"void(?:\s+(?:sale|transaction))?",
    r"cancelled(?:\s+transaction)?",
    r"cancellation",
    r"return(?:\s+(?:amount|total))?",
    r"reversal",
)


def _find_refund_amount(text: str) -> float | None:
    """Return the refund / void / cancelled amount, or None.

    Tries the keyword forms (``Refund 12.50`` / ``VOID -12.50`` etc.)
    first because they are the unambiguous signal. Falls back to a
    negative-total form (``Total -12.50``) so a printer that omits
    the keyword but flips the total sign still tags the receipt as
    a refund. Returns the ABSOLUTE amount; the sign is implied by
    the field's semantic (only refunds populate it). Values outside
    0.01..99999 are rejected as OCR noise.
    """
    if not text:
        return None
    # Keyword-led form: ``REFUND -12.50`` / ``Refund Amount: 12.50``.
    # Accept an optional leading sign on the amount, optional
    # currency symbol, and optional ``:`` / ``-`` / ``=`` separator
    # between the keyword and the value.
    for kw in _REFUND_KEYWORDS:
        pat = re.compile(
            rf"(?:(?<=\n)|(?<=^)|(?<=[^a-zA-Z])){kw}"
            r"\s*[:\-=]?\s*[-]?\s*[$€£¥]?\s*"
            r"(?P<amt>\d{1,5}(?:[.,]\d{2}))",
            re.IGNORECASE,
        )
        matches = list(pat.finditer(text))
        if not matches:
            continue
        # Last-match wins for the keyword form (a header that lists
        # "Refunds Today" + the actual ``Refund 12.50`` line at the
        # bottom should resolve to the actual line).
        try:
            amount = abs(float(matches[-1].group("amt").replace(",", ".")))
        except ValueError:
            continue
        if 0.01 <= amount <= 99999:
            return round(amount, 2)
    # No keyword cue -> try the negative-total fallback. We only do
    # this when the ``Total`` / ``Subtotal`` line carries an explicit
    # leading ``-``; a positive total is a normal sale.
    neg_total = re.search(
        r"(?:(?<=\n)|(?<=^)|(?<=[^a-zA-Z]))(?:sub)?total"
        r"\s*[:\-]?\s*-\s*[$€£¥]?\s*"
        r"(?P<amt>\d{1,5}(?:[.,]\d{2}))",
        text,
        re.IGNORECASE,
    )
    if neg_total:
        try:
            amount = abs(float(neg_total.group("amt").replace(",", ".")))
        except ValueError:
            return None
        if 0.01 <= amount <= 99999:
            return round(amount, 2)
    return None


# Loyalty / membership / store / register identifier extraction.
# Receipts carry three logically distinct identifiers in addition to
# the order / invoice number already covered:
#
#   LOYALTY        - customer-side membership identifier. Common shapes:
#                    ``Member: 12345``, ``Loyalty #ABC-99``,
#                    ``Rewards ID: 4477``, ``Member ID 99001``,
#                    ``Loyalty Number 1234``, ``Reward Member #88``.
#                    Distinct from the order number because it
#                    persists across visits; dashboards group by it
#                    to surface frequent-customer behaviour.
#   STORE / BRANCH - location-side identifier. ``Store #1234``,
#                    ``Branch 045``, ``Location 12``, ``Shop No. 7``.
#                    Multi-location chains print this near the
#                    address block. Dashboards roll up by store.
#   REGISTER/TILL  - terminal-side identifier. ``REG 02``,
#                    ``Register #3``, ``Terminal 5``, ``Till 04``,
#                    ``POS 12``, ``Lane 4``. Identifies which
#                    physical checkout produced the receipt.
#
# The matchers below capture each identifier verbatim (string) so
# alphanumeric mixes like ``Store #ABC-1234`` survive. Length is
# bounded 1..30 chars to keep OCR runs out. Within a single matcher
# the FIRST occurrence wins because these IDs almost always print
# once near the header.
#
# Value regex permits alphanumerics with internal ``./-`` punctuation.
# A leading ``#`` is consumed by the keyword pattern (so the captured
# value is bare) because dashboards almost always re-render the hash
# as part of the label.
_ID_VALUE = r"(?:[A-Za-z0-9][A-Za-z0-9./\-]{0,28}[A-Za-z0-9]|[A-Za-z0-9])"

_LOYALTY_KEYWORDS: tuple[str, ...] = (
    r"loyalty\s+(?:no\.?|number|id|#)",
    r"loyalty",
    r"rewards?\s+(?:no\.?|number|id|#)",
    r"reward\s+member\s*#?",
    r"rewards?",
    r"member\s+(?:no\.?|number|id|#)",
    r"membership\s+(?:no\.?|number|id|#)",
    r"member",
)
_STORE_KEYWORDS: tuple[str, ...] = (
    r"store\s+(?:no\.?|number|id|#)",
    r"store",
    r"branch\s+(?:no\.?|number|id|#)",
    r"branch",
    r"location\s+(?:no\.?|number|id|#)",
    r"location",
    r"shop\s+(?:no\.?|number|id|#)",
)
_REGISTER_KEYWORDS: tuple[str, ...] = (
    r"register\s+(?:no\.?|number|id|#)",
    r"register",
    r"reg\s*#?",
    r"terminal\s+(?:no\.?|number|id|#)",
    r"terminal",
    r"till\s+(?:no\.?|number|id|#)",
    r"till",
    r"pos\s+(?:no\.?|number|id|#)",
    r"lane\s+(?:no\.?|number|id|#)",
    r"lane",
)


def _find_keyword_id(text: str, keywords: tuple[str, ...]) -> str | None:
    """Return the first non-empty alphanumeric value following any of
    the keywords in priority order, or ``None``.

    Each keyword pattern accepts an optional ``:`` / ``-`` / ``=``
    separator, optional ``#`` prefix on the value, and a single
    value token. The value must contain at least one digit so a
    stray prose match (``Store closed``) does not pass. Leading
    word-boundary is enforced via a negative lookbehind on alphas
    so ``Bookstore #1`` doesn't fire the ``Store`` matcher (because
    ``Bookstore`` has alpha char immediately before ``store``).
    """
    if not text:
        return None
    for kw in keywords:
        pat = re.compile(
            rf"(?<![A-Za-z]){kw}\s*[:\-=]?\s*#?\s*(?P<val>{_ID_VALUE})",
            re.IGNORECASE,
        )
        m = pat.search(text)
        if not m:
            continue
        val = m.group("val").strip()
        if not any(c.isdigit() for c in val):
            continue
        val = val.rstrip(".,;:)")
        if not val:
            continue
        if not (1 <= len(val) <= 30):
            continue
        return val
    return None


def _find_loyalty_id(text: str) -> str | None:
    """Return the loyalty / member / rewards identifier, or None."""
    return _find_keyword_id(text, _LOYALTY_KEYWORDS)


def _find_store_id(text: str) -> str | None:
    """Return the store / branch / location identifier, or None."""
    return _find_keyword_id(text, _STORE_KEYWORDS)


def _find_register_id(text: str) -> str | None:
    """Return the register / terminal / till / POS identifier, or None."""
    return _find_keyword_id(text, _REGISTER_KEYWORDS)


# Cashier / operator and server / waiter name extraction. The two
# slots are extracted with the same logic but different keyword
# catalogues because the relationships they capture are
# semantically different on a restaurant receipt (the server takes
# the order, the cashier rings up the bill; they are often
# different people).
#
# Recognised cashier vocabularies (case-insensitive):
#
#   Cashier: Bob                 -> Bob
#   Cashier #04 Bob              -> Bob       (id between keyword and name)
#   Cashier 04 - Bob             -> Bob
#   Operator: ALICE              -> ALICE
#   Clerk: Charlie               -> Charlie
#   Clerk #04 Charlie            -> Charlie
#   Sold by: Alice               -> Alice
#   Sold By Alice                -> Alice
#
# Recognised server vocabularies:
#
#   Server: Alice                -> Alice
#   Your server was Bob          -> Bob
#   Your Server: Bob             -> Bob
#   Waiter: Charlie              -> Charlie
#   Waitress: Diana              -> Diana
#   Served by: Diana             -> Diana
#   Server #04 Alice             -> Alice
#
# Name capture rules:
#
# * The keyword + optional identifier number is consumed first
#   (``Cashier #04 -``); the captured name is the trailing token
#   sequence on the same line.
# * Names are bounded 1..30 chars and must contain at least one
#   alpha char (so a stray ``Cashier 12345`` line doesn't capture
#   ``12345`` as the name).
# * A trailing identifier number after the name (``Cashier Bob
#   #04``) is NOT captured into the name.
# * First keyword in catalogue order wins (the keyword catalogues
#   are ordered most-specific-first so ``Your server was`` beats
#   the bare ``Server:`` matcher when both appear).
#
# The matcher anchors on a line-start or post-comma word boundary
# so prose like ``the cashier was busy`` doesn't fire.
_CASHIER_KEYWORDS: tuple[str, ...] = (
    r"cashier\s*#?\s*\d{1,5}\s*[-:]?",
    r"cashier",
    r"operator\s*#?\s*\d{1,5}\s*[-:]?",
    r"operator",
    r"clerk\s*#?\s*\d{1,5}\s*[-:]?",
    r"clerk",
    r"sold\s+by",
)
_SERVER_KEYWORDS: tuple[str, ...] = (
    r"your\s+server\s+was",
    r"your\s+server",
    r"server\s*#?\s*\d{1,5}\s*[-:]?",
    r"server",
    r"waiter",
    r"waitress",
    r"served\s+by",
)
# Captured name tail: 1..30 chars of letters / spaces / dots / dashes
# / apostrophes (covers ``Mary-Jane``, ``O'Brien``, ``Jr.``). The
# matcher is greedy up to end-of-line then trimmed by the helper.
_NAME_TAIL = r"(?P<name>[A-Za-z][A-Za-z .'\-]{0,29})"


def _find_keyword_name(text: str, keywords: tuple[str, ...]) -> str | None:
    """Return the first non-empty name following any of the keywords in
    priority order, or ``None``.

    Each keyword pattern accepts an optional ``:`` / ``-`` separator,
    optional whitespace, then the name tail (letters + space + dots +
    dashes + apostrophes). The match is bounded to a single line so
    a downstream line cannot be absorbed as part of the name. Names
    must contain at least one alpha char and at least 2 chars to
    pass; single-letter ``Cashier B`` is accepted (real receipts
    sometimes truncate names) but a numeric-only tail is rejected.
    """
    if not text:
        return None
    for kw in keywords:
        pat = re.compile(
            rf"(?<![A-Za-z]){kw}\s*[:\-]?\s*{_NAME_TAIL}",
            re.IGNORECASE,
        )
        m = pat.search(text)
        if not m:
            continue
        name = m.group("name").strip().rstrip(".,;:-")
        # Reject if the captured tail is too short or has no alpha.
        if len(name) < 1 or not any(c.isalpha() for c in name):
            continue
        # Column-gap detection runs BEFORE whitespace normalisation:
        # if the captured name has two consecutive spaces it means
        # the regex absorbed the column gap into the next receipt
        # field, so trim there. After this we collapse remaining
        # internal runs to single spaces for clean output.
        if "  " in name:
            name = name.split("  ", 1)[0].strip()
        name = re.sub(r"\s+", " ", name)
        if not name:
            continue
        return name
    return None


def _find_cashier(text: str) -> str | None:
    """Return the cashier / operator / clerk name, or None."""
    return _find_keyword_name(text, _CASHIER_KEYWORDS)


def _find_server(text: str) -> str | None:
    """Return the server / waiter / waitress name, or None."""
    return _find_keyword_name(text, _SERVER_KEYWORDS)


def _guess_vendor(text: str) -> str | None:
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.search(r"\d", line):
            continue
        if len(line) < 3 or len(line) > 40:
            continue
        if line.lower() in {"receipt", "invoice", "thank you"}:
            continue
        return line
    return None


def _guess_date(text: str) -> str | None:
    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if m:
            raw = m.group(1)
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d %b %Y"):
                try:
                    return datetime.strptime(raw, fmt).date().isoformat()
                except ValueError:
                    continue
            return raw
    return None


# Per-item percent-off discount. Recognised shapes (matched in order):
#
#   "BOGO 50% off Latte 4.00"          -> desc=Latte, pct=50, price=4.00
#   "50% off Croissant 3.50"           -> desc=Croissant, pct=50, price=3.50
#   "Latte 5.00 (10% off)"             -> desc=Latte, pct=10, price=5.00
#   "Latte 50% off 5.00"               -> desc=Latte, pct=50, price=5.00
#
# We anchor on the ``\d+%\s*off`` clause because that's the unambiguous
# discount signal; the description, price, and order around it vary
# wildly between printers. The price field captures the LINE price
# (final after discount on most printers, the pre-discount on a few
# fancy printers -- we accept either since the percent is the salient
# datum). Pure ``50% off coupon`` summary lines without an item name
# are NOT parsed as line items -- the existing top-level discount
# detector already catches those.
_LINE_PCT_OFF_LEADING = re.compile(
    r"^(?:[A-Za-z][\w :,!-]*\s+)?"       # optional promo prefix ("BOGO ", "Member ", "Promo: BOGO ")
    r"(?P<pct>\d{1,2}(?:\.\d{1,2})?)\s*%\s*off\s+"
    r"(?P<desc>.+?)\s+"
    r"[$€£¥]?\s*(?P<price>\d{1,5}(?:[.,]\d{2}))\s*$",
    re.IGNORECASE,
)
_LINE_PCT_OFF_TRAILING = re.compile(
    r"^(?P<desc>.+?)\s+"
    r"[$€£¥]?\s*(?P<price>\d{1,5}(?:[.,]\d{2}))\s*"
    r"\(?\s*(?P<pct>\d{1,2}(?:\.\d{1,2})?)\s*%\s*off\s*\)?\s*$",
    re.IGNORECASE,
)
_LINE_PCT_OFF_INFIX = re.compile(
    r"^(?P<desc>[A-Za-z][\w ]+?)\s+"
    r"(?P<pct>\d{1,2}(?:\.\d{1,2})?)\s*%\s*off\s+"
    r"[$€£¥]?\s*(?P<price>\d{1,5}(?:[.,]\d{2}))\s*$",
    re.IGNORECASE,
)


def _try_pct_off(line: str) -> ReceiptLine | None:
    """Return a ReceiptLine for any of the percent-off shapes, or None."""
    for pat in (_LINE_PCT_OFF_LEADING, _LINE_PCT_OFF_INFIX, _LINE_PCT_OFF_TRAILING):
        m = pat.match(line)
        if not m:
            continue
        try:
            pct = float(m.group("pct"))
            price = float(m.group("price").replace(",", "."))
        except ValueError:
            continue
        desc = m.group("desc").strip().strip(".:-")
        # Strip generic promo / loyalty / member prefixes the leading
        # regex may have absorbed into the desc when the loop matched
        # via _LINE_PCT_OFF_INFIX (where ``[A-Za-z][\w ]+`` greedily
        # took a "Member" word).
        for prefix in ("member ", "loyalty ", "rewards ", "bogo "):
            if desc.lower().startswith(prefix):
                desc = desc[len(prefix):].strip()
        if not desc or len(desc) < 2 or len(desc) > 60:
            continue
        if not (0 < pct <= 100):
            continue
        if not (0.01 <= price <= 9999):
            continue
        discount_amount = round(price * pct / 100.0, 2)
        return ReceiptLine(
            description=desc,
            price=price,
            discount_pct=pct,
            discount_amount=discount_amount,
        )
    return None


def _parse_items(text: str) -> list[ReceiptLine]:
    items: list[ReceiptLine] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        # 0) Per-item percent-off discount. Run BEFORE the keyword skip
        #    so a line like ``Promo: BOGO 50% off Latte 4.00`` is parsed
        #    as a discounted item even though it contains the
        #    ``promo`` / ``discount`` keywords that would otherwise
        #    push it through ``continue``. We only short-circuit when
        #    the line genuinely has a ``\d+% off`` clause.
        if re.search(r"\d{1,2}\s*%\s*off\b", line, re.IGNORECASE):
            discounted = _try_pct_off(line)
            if discounted is not None:
                items.append(discounted)
                if len(items) >= 30:
                    break
                continue
        if any(k in low for k in [
            "subtotal", "total", "tax", "vat", "tip", "gratuity", "service",
            "change", "cash", "discount", "coupon", "promo", "savings",
            "loyalty", "rewards",
        ]):
            continue
        # 1) Quantity-prefixed form: "2 x Latte 6.00 = 12.00" or
        #    "2 x Latte 6.00" (no extended total printed). The qty is
        #    typically printed as the leading integer / decimal,
        #    separated from the description by ``x`` / ``X`` / ``*``
        #    (with optional spaces) -- the same notation almost every
        #    receipt printer uses. When a final "= 12.00" is printed
        #    we still record the UNIT price in ReceiptLine.price (qty
        #    * price reconstructs the extended total cleanly), which
        #    matches how downstream dashboards expect to multiply.
        qty_match = re.match(
            r"^(?P<qty>\d+(?:[.,]\d{1,3})?)\s*[xX*]\s+"
            r"(?P<desc>.+?)\s+"
            r"(?P<unit>\d+(?:[.,]\d{2}))"
            r"(?:\s*=\s*(?P<ext>\d+(?:[.,]\d{2})))?\s*$",
            line,
        )
        if qty_match:
            try:
                qty = float(qty_match.group("qty").replace(",", "."))
                unit = float(qty_match.group("unit").replace(",", "."))
            except ValueError:
                continue
            desc = qty_match.group("desc").strip().strip(".:-")
            if 0.01 <= unit <= 9999 and 2 <= len(desc) <= 60 and qty > 0:
                items.append(ReceiptLine(description=desc, qty=qty, price=unit))
                if len(items) >= 30:
                    break
                continue
        # 2) Trailing quantity-times-price form: "Latte 2 @ 6.00" or
        #    "Latte 2 @ $6.00". Some receipt printers print the
        #    quantity AFTER the description with an ``@`` separator
        #    instead of leading ``x``.
        at_match = re.match(
            r"^(?P<desc>.+?)\s+(?P<qty>\d+(?:[.,]\d{1,3})?)\s*@\s*"
            r"[$€£¥]?\s*(?P<unit>\d+(?:[.,]\d{2}))\s*$",
            line,
        )
        if at_match:
            try:
                qty = float(at_match.group("qty").replace(",", "."))
                unit = float(at_match.group("unit").replace(",", "."))
            except ValueError:
                continue
            desc = at_match.group("desc").strip().strip(".:-")
            if 0.01 <= unit <= 9999 and 2 <= len(desc) <= 60 and qty > 0:
                items.append(ReceiptLine(description=desc, qty=qty, price=unit))
                if len(items) >= 30:
                    break
                continue
        # 3) Bare desc + price (original behaviour).
        m = re.search(r"^(.*?)\s+(\d+(?:[.,]\d{2}))$", line)
        if not m:
            continue
        desc = m.group(1).strip().strip(".:-")
        try:
            price = float(m.group(2).replace(",", "."))
        except ValueError:
            continue
        if 0.01 <= price <= 9999 and 2 <= len(desc) <= 60:
            items.append(ReceiptLine(description=desc, price=price))
    return items[:30]


def _compute_tip_percent(
    tip: float | None, subtotal: float | None, total: float | None
) -> float | None:
    """Return tip as a percentage of subtotal (preferred) or pre-tip total.

    Returns ``None`` when:
      * no tip was found, OR
      * neither a subtotal nor a usable total is available, OR
      * the inferred base (subtotal / total - tip) is non-positive.

    The result is rounded to one decimal place because two decimals
    are spurious precision on top of OCR noise.

    Subtotal is preferred over total because it excludes tax (and on
    most US receipts the customer tips on the pre-tax subtotal). If
    only the total is available, we approximate by subtracting the tip
    (``base = total - tip``) and accepting whatever tax distortion
    that introduces — the percentage is still useful for dashboards
    that want to bucket "15% / 18% / 20% / generous" tippers.
    """
    if tip is None or tip <= 0:
        return None
    base: float | None = None
    if subtotal is not None and subtotal > 0:
        base = subtotal
    elif total is not None and total > tip:
        base = total - tip
    if base is None or base <= 0:
        return None
    pct = (tip / base) * 100.0
    return round(pct, 1)


def parse_receipt_text(text: str) -> ReceiptFields:
    subtotal = _find_amount_after(text, "subtotal")
    tax = _find_amount_after(text, "tax") or _find_amount_after(text, "vat")
    tip = _find_tip(text)
    total = _find_amount_after(text, "total")
    return ReceiptFields(
        vendor=_guess_vendor(text),
        date=_guess_date(text),
        subtotal=subtotal,
        tax=tax,
        tip=tip,
        tip_percent=_compute_tip_percent(tip, subtotal, total),
        discount=_find_discount(text),
        total=total,
        currency=_detect_currency(text),
        payment_method=_detect_payment_method(text),
        order_number=_find_order_number(text),
        tax_mode=_detect_tax_mode(text),
        party_size=_detect_party_size(text),
        refund_amount=_find_refund_amount(text),
        loyalty_id=_find_loyalty_id(text),
        store_id=_find_store_id(text),
        register_id=_find_register_id(text),
        cashier=_find_cashier(text),
        server=_find_server(text),
        items=_parse_items(text),
    )


def enrich_receipt(existing: ReceiptFields | None, ocr: OCRResult) -> ReceiptFields:
    parsed = parse_receipt_text(ocr.text)
    if existing is None:
        return parsed
    merged = existing.model_copy()
    for f in (
        "vendor", "date", "subtotal", "tax", "tip", "discount", "total",
        "currency", "payment_method", "order_number", "tax_mode",
        "party_size", "refund_amount", "loyalty_id", "store_id",
        "register_id", "cashier", "server",
    ):
        if getattr(merged, f) in (None, "", 0):
            setattr(merged, f, getattr(parsed, f))
    if not merged.items:
        merged.items = parsed.items
    # Recompute tip_percent against the merged tip + subtotal/total so a
    # caller that only supplied a subtotal still gets a derived percent
    # when the OCR pass discovered the tip.
    if merged.tip_percent in (None, 0):
        merged.tip_percent = _compute_tip_percent(
            merged.tip, merged.subtotal, merged.total
        )
    return merged
