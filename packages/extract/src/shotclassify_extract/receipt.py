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


# Suggested-tip table detection. Restaurants often print a small
# reference table at the bottom of the receipt showing what the tip
# would be for common percentages:
#
#   Suggested Tips:
#   15% = 1.80
#   18% = 2.16
#   20% = 2.40
#
# or as a horizontal row:
#
#   15% $1.80    18% $2.16    20% $2.40
#
# or inline-after-label:
#
#   Tip Suggestions: 15% 1.80 | 18% 2.16 | 20% 2.40
#
# Each entry is captured as a (percent, amount) dict. We require
# AT LEAST 2 distinct percent-amount pairs to surface the list --
# a lone "Tip 20% 5.00" is the customer's chosen tip (already
# handled by _find_tip + _compute_tip_percent) and shouldn't be
# duplicated here.
#
# The matcher catches the percent + amount pair in either order:
# percent-then-amount (15% 1.80) and amount-then-percent (1.80 15%)
# are both real-world shapes. Currency symbol on the amount is
# optional ($, €, £, ¥ accepted). Separator between percent and
# amount can be space, ``=``, tab, ``:``, ``|``, ``->``, or nothing
# when the table uses column alignment.

# A "percent + amount" pair matcher. The percent is 5..50 (bounded
# at the low end because <5% would be a typo and at the high end
# because >50% would be an outlier). The amount is the standard
# two-decimal currency form.
#
# We match both orientations:
#   15% 1.80 / 15% $1.80 / 15% = 1.80 / 15%: 1.80 / 15%-1.80
#   1.80 15% / $1.80 15%
_SUGGESTED_TIP_PCT_AMT = re.compile(
    r"(?P<pct>\d{1,2}(?:\.\d{1,2})?)\s*%"
    r"\s*[=:\-|>\s]*\s*"
    r"[$€£¥]?\s*(?P<amt>\d{1,4}(?:[.,]\d{2}))"
)
_SUGGESTED_TIP_AMT_PCT = re.compile(
    r"[$€£¥]?\s*(?P<amt>\d{1,4}(?:[.,]\d{2}))"
    r"\s*[=:\-|>\s]*\s*"
    r"(?P<pct>\d{1,2}(?:\.\d{1,2})?)\s*%"
)

_SUGGESTED_TIP_PCT_MIN = 5.0
_SUGGESTED_TIP_PCT_MAX = 50.0
_SUGGESTED_TIP_AMT_MIN = 0.01
_SUGGESTED_TIP_AMT_MAX = 9999.99
_SUGGESTED_TIP_MAX_ENTRIES = 6


def _find_suggested_tips(text: str) -> list[dict[str, float]]:
    """Return the printed suggested-tip table, or empty list.

    Walks every percent-amount pair in the text (both orientations:
    ``15% 1.80`` AND ``1.80 15%``) and collects them. Returns an
    empty list when fewer than 2 distinct (percent, amount) pairs
    are found because a lone pair is almost always the customer's
    actual tip (captured by ``_find_tip`` + ``_compute_tip_percent``),
    not a printed suggestion table.

    Output is a list of ``{"percent": float, "amount": float}`` dicts
    sorted by percent ASC so dashboards render the table in the
    natural reading order. Capped at 6 entries because real-world
    tables rarely exceed 5 rows; a screenshot returning more is
    almost certainly OCR noise pulling in unrelated percentages
    (a 25% discount line, a 5% tax rate, etc.).

    Boundaries enforced:

    * percent: 5..50 (lower-bound rejects typos / fractional
      percentages from prose, upper-bound rejects outliers)
    * amount: 0.01..9999.99 (a positive currency value within the
      printer's two-decimal format)

    Defence against false positives:

    * The same (percent, amount) pair captured twice (because the
      table was OCR-doubled) deduplicates to one entry.
    * The pct->amt and amt->pct matchers are tried per-LINE in
      that priority order; whichever matcher fires first on a line
      claims its spans and the other orientation only runs over
      the unclaimed regions. This prevents cross-pair captures on
      a line like ``15% 1.80   18% 2.16`` where a naive
      amt->pct pass would also stitch ``1.80 18%`` as a phantom
      pair.
    * Discount / refund / tax percentages on UNRELATED lines bleed
      in less often because we require BOTH a percent AND an
      adjacent currency-shaped amount on the same line.
    """
    if not text:
        return []
    seen: dict[tuple[float, float], tuple[int, float, float]] = {}
    # Walk every line; for each line, look for pct-then-amt first
    # (the more common orientation), then re-scan with amt-then-pct
    # only over the LINE REGIONS not already claimed by a pct-then-amt
    # match. This prevents the amt-then-pct matcher from stitching
    # a phantom pair out of an earlier amount and a later percent on
    # the same horizontal table row (``15% 1.80   18% 2.16`` would
    # otherwise also yield ``1.80 18%`` etc).
    for idx, raw in enumerate(text.splitlines()):
        if not raw.strip():
            continue
        # Pass 1: pct-then-amt. Walks left to right; finditer advances
        # past each match's end so non-overlapping per-pass already.
        claimed: list[tuple[int, int]] = []
        for match in _SUGGESTED_TIP_PCT_AMT.finditer(raw):
            _consider_suggested_tip(match, idx, seen)
            claimed.append((match.start(), match.end()))
        # Pass 2: amt-then-pct only on the segments NOT covered by
        # any pass-1 match. We extract each unclaimed slice and run
        # the matcher on it.
        if claimed:
            cursor = 0
            for c_start, c_end in sorted(claimed):
                if c_start > cursor:
                    chunk = raw[cursor:c_start]
                    for match in _SUGGESTED_TIP_AMT_PCT.finditer(chunk):
                        _consider_suggested_tip(match, idx, seen)
                cursor = max(cursor, c_end)
            if cursor < len(raw):
                chunk = raw[cursor:]
                for match in _SUGGESTED_TIP_AMT_PCT.finditer(chunk):
                    _consider_suggested_tip(match, idx, seen)
        else:
            for match in _SUGGESTED_TIP_AMT_PCT.finditer(raw):
                _consider_suggested_tip(match, idx, seen)
    if len(seen) < 2:
        return []
    # Sort by percent ASC. Where the percent is identical (rare; can
    # happen on a doubled row) the lower amount wins to keep dedupe
    # deterministic.
    ordered = sorted(seen.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    result = [{"percent": pct, "amount": amt} for (pct, amt), _ in ordered]
    return result[:_SUGGESTED_TIP_MAX_ENTRIES]


def _consider_suggested_tip(
    match: re.Match[str],
    line_idx: int,
    seen: dict[tuple[float, float], tuple[int, float, float]],
) -> None:
    """Validate and record a suggested-tip match if it passes bounds."""
    try:
        pct = float(match.group("pct"))
        amt = float(match.group("amt").replace(",", "."))
    except (ValueError, IndexError):
        return
    if not (_SUGGESTED_TIP_PCT_MIN <= pct <= _SUGGESTED_TIP_PCT_MAX):
        return
    if not (_SUGGESTED_TIP_AMT_MIN <= amt <= _SUGGESTED_TIP_AMT_MAX):
        return
    key = (pct, amt)
    # First-seen wins on the line index (deterministic dedupe).
    if key not in seen:
        seen[key] = (line_idx, pct, amt)


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


# Service-charge keywords. Service charges are distinct from tips on
# many restaurant / delivery receipts: a mandatory auto-gratuity for
# large parties, a platform-fee surcharge by UberEats / DoorDash, or
# a hotel-style "service" line. Keywords are ordered MOST SPECIFIC
# first so ``Service Charge`` wins over a bare ``Service`` keyword
# that already exists in the tip catalogue. The bare ``Service``
# alias intentionally lives in ``_TIP_KEYWORDS`` rather than here
# because the legacy ``tip`` field already treats a bare "Service N"
# line as gratuity-equivalent on a UK-style bar tab -- changing that
# would break callers. The service_charge field captures the EXPLICIT
# service-charge / service-fee phrasing that is unambiguous.
_SERVICE_CHARGE_KEYWORDS = (
    "service charge",
    "service fee",
    "svc charge",
    "svc fee",
)


def _find_service_charge(text: str) -> float | None:
    """Return the service-charge amount on the receipt, or None.

    Matches explicit "Service Charge" / "Service Fee" / "Svc Charge" /
    "Svc Fee" phrasings (case-insensitive). Returns the LAST occurrence
    so a "Service Fee suggested" header above a real "Service Fee 5.00"
    line resolves to the line the customer paid -- mirrors the tip
    semantics. ``None`` when the receipt prints no explicit
    service-charge line.
    """
    for keyword in _SERVICE_CHARGE_KEYWORDS:
        value = _find_amount_after(text, keyword)
        if value is not None:
            return value
    return None


# Delivery / shipping fee keywords. Recognised across food-delivery
# (UberEats / DoorDash / Deliveroo / Grubhub), e-commerce (Amazon /
# Shopify / general), and grocery-delivery (Instacart) receipts.
# Ordered most-specific first so the multi-word forms beat the bare
# "Delivery" / "Shipping" aliases. The bare aliases are kept as the
# last fallbacks because retail receipts often print just
# ``Shipping  4.99`` with no qualifier.
_DELIVERY_FEE_KEYWORDS = (
    "delivery fee",
    "delivery charge",
    "shipping fee",
    "shipping & handling",
    "shipping and handling",
    "shipping charge",
    "shipping cost",
    "delivery",
    "shipping",
)


def _find_delivery_fee(text: str) -> float | None:
    """Return the delivery / shipping fee on the receipt, or None.

    Matches "Delivery Fee" / "Delivery Charge" / "Delivery" /
    "Shipping" / "Shipping Fee" / "Shipping & Handling" / "Shipping
    and Handling" / "Shipping Charge" / "Shipping Cost" (case-
    insensitive). LAST-occurrence semantics for consistency with tip /
    discount / service-charge. ``None`` when the receipt prints no
    delivery line (typical for dine-in restaurant and in-person retail
    receipts).
    """
    for keyword in _DELIVERY_FEE_KEYWORDS:
        value = _find_amount_after(text, keyword)
        if value is not None:
            return value
    return None


# Tender / change keywords for cash-handling receipts. Recognised
# wording across US / UK / EU printers:
#
#   Tendered 20.00
#   Cash Tendered 20.00
#   Cash 20.00
#   Paid 20.00
#   Payment 20.00
#
#   Change 7.50
#   Change Due 7.50
#   Change Given 7.50
#   Cash Change 7.50
#
# The tender catalogue intentionally puts the more-specific
# "Tendered" / "Cash Tendered" first so a bare "Cash 20.00" alias
# only fires when the more-explicit wording is absent. "Paid" /
# "Payment" sit at the tail because they overlap with merchant-
# language on invoices ("Paid in full") -- the specific amount-
# bearing form still works but the precedence keeps the unambiguous
# wording in front.
_TENDERED_KEYWORDS = (
    "cash tendered",
    "tendered",
    "tender",
    "amount tendered",
    "amount paid",
    "paid",
    "payment",
    "cash",
)

_CHANGE_KEYWORDS = (
    "change due",
    "change given",
    "cash change",
    "change",
)


def _find_tendered(text: str) -> float | None:
    """Return the cash tendered by the customer, or None.

    Recognises "Tendered 20.00", "Cash Tendered 20.00", "Cash 20.00",
    "Paid 20.00", "Payment 20.00", "Amount Tendered 20.00", "Amount
    Paid 20.00", "Tender 20.00" (case-insensitive). LAST-occurrence
    semantics for consistency with the other ``_find_amount_after``
    callers. ``None`` for card-only receipts that do not break out a
    tender amount.

    NOTE: The "Cash" alias is the loosest -- if a receipt prints
    "Cashier #04" the underlying ``_find_amount_after`` regex won't
    match because it requires a digit-amount IMMEDIATELY after the
    keyword (with at most ``:`` / ``-`` separators), and "Cashier #04"
    has the ``ier #`` between "Cash" and "04". A future tightening
    could anchor the keyword on a word-boundary, but the regex layer
    already handles it.
    """
    for keyword in _TENDERED_KEYWORDS:
        value = _find_amount_after(text, keyword)
        if value is not None:
            return value
    return None


def _find_change(text: str) -> float | None:
    """Return the change handed back to the customer, or None.

    Recognises "Change 7.50", "Change Due 7.50", "Change Given 7.50",
    "Cash Change 7.50" (case-insensitive). LAST-occurrence semantics.
    ``None`` when no change line is printed (card-only receipts, or
    cash receipts that paid the exact amount). The bare "Change"
    alias is the catch-all so receipts that print just "CHANGE 0.00"
    still register as a tendered/change pair for till-discrepancy
    dashboards.
    """
    for keyword in _CHANGE_KEYWORDS:
        value = _find_amount_after(text, keyword)
        if value is not None:
            return value
    return None


# Split-payment / multi-tender detection. Restaurant and retail
# receipts that accept more than one payment method print one
# explicit line per tender component:
#
#   Visa: 25.00
#   Cash: 10.00
#
# or with masked PANs:
#
#   Visa **** 1234       25.00
#   Mastercard ** 5678   18.00
#
# or modern split-payment via gift-card + card:
#
#   Gift Card: 15.00
#   Apple Pay: 10.00
#
# Each detected line becomes a {kind, amount} entry. The list is
# returned ONLY when 2+ distinct tender lines are present so
# dashboards can rely on len(tenders) > 0 meaning a real
# split-tender breakdown.
#
# Catalogue ordered most-specific-first so multi-word forms win:
# "American Express" beats "amex", "Master Card" beats "card",
# "Gift Card" beats "Card" / "Credit", "Apple Pay" beats "Apple".
# Generic "Card" / "Credit" / "Debit" / "Other" sit at the tail
# as catch-all fallbacks.
_TENDER_CATALOGUE: tuple[tuple[str, str], ...] = (
    # (keyword regex fragment -- case-insensitive whole-word, kind tag)
    (r"american\s+express", "amex"),
    (r"master\s*card", "mastercard"),
    (r"apple\s*pay", "apple_pay"),
    (r"google\s*pay", "google_pay"),
    (r"samsung\s*pay", "samsung_pay"),
    (r"gift\s+card", "gift_card"),
    (r"store\s+credit", "store_credit"),
    (r"cash\s+app", "cashapp"),
    (r"union\s*pay", "unionpay"),
    (r"diners(?:\s+club)?", "diners"),
    (r"visa", "visa"),
    (r"mastercard", "mastercard"),
    (r"amex", "amex"),
    (r"discover", "discover"),
    (r"jcb", "jcb"),
    (r"paypal", "paypal"),
    (r"venmo", "venmo"),
    (r"zelle", "zelle"),
    (r"cashapp", "cashapp"),
    (r"check", "check"),
    (r"cheque", "check"),
    (r"cash", "cash"),
    (r"ebt", "ebt"),
    (r"debit(?:\s+card)?", "debit"),
    (r"credit(?:\s+card)?", "credit"),
    (r"card", "card"),
)

# Build a single combined regex that captures the tender keyword
# plus its amount on the same line. The amount may carry an
# optional masked-PAN ("**** 1234" / "** 5678" / "...1234") AND
# an optional separator (": " / " - " / "  ") AND an optional
# currency symbol AND an optional leading sign before the value.
#
# We intentionally require the amount to sit on the same line as
# the keyword so a "Visa" header at the top doesn't pair with the
# total at the bottom.
#
# The amount regex matches the standard two-decimal currency form
# (e.g. ``25.00``, ``-12.50``, ``$10.00``, ``1,250.00``). Comma-
# thousands grouping is accepted; the regex strips them before
# float() conversion. Comma-decimal style (``25,00``) is also
# accepted.
_TENDER_AMOUNT = (
    r"-?\s*[$€£¥]?\s*"
    r"\d{1,5}(?:[.,]\d{2,3})*(?:[.,]\d{2})"
)


def _build_tender_pattern(keyword: str) -> re.Pattern[str]:
    """Compile a per-keyword tender-line matcher.

    Matches:
        <keyword> [mask] [: / - / whitespace separator] <amount>

    on a single line (the body cannot contain a newline before
    the amount). Mask shapes accepted:
        ****  1234
        ****1234
        **    5678
        ......1234
        XXXX 1234
    """
    return re.compile(
        # Word-boundary lookbehind to avoid matching mid-word.
        r"(?<![A-Za-z])"
        rf"(?:{keyword})\b"
        # Optional masked-PAN: 2+ mask chars + optional digits tail.
        # We use [^\S\n] so newlines don't get swallowed.
        r"(?:[^\S\n]+[*xX.]{2,16}[^\S\n]*\d{0,6})?"
        # Optional separator (colon / dash / whitespace).
        r"[^\S\n]*[:\-=][^\S\n]*"
        rf"(?P<amt>{_TENDER_AMOUNT})",
        re.IGNORECASE,
    )


# Compile once at module load.
_TENDER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (_build_tender_pattern(kw), kind) for kw, kind in _TENDER_CATALOGUE
)

_MAX_TENDERS = 10


def _parse_amount(raw: str) -> float | None:
    """Parse a tender-amount string into a positive float, or None."""
    cleaned = raw.strip().lstrip("-+").lstrip()
    # Strip currency symbol.
    for sym in "$€£¥":
        cleaned = cleaned.replace(sym, "")
    cleaned = cleaned.strip()
    if not cleaned:
        return None
    # Normalise comma-decimal / comma-thousands.
    if "," in cleaned and "." in cleaned:
        # Both separators present -- the rightmost is the decimal.
        last_comma = cleaned.rfind(",")
        last_dot = cleaned.rfind(".")
        if last_comma > last_dot:
            # Comma is decimal, dot is thousands.
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # Dot is decimal, comma is thousands.
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # Only comma -- if the comma sits in the last 3 positions
        # AND there are 2-3 digits after, treat as decimal.
        # Otherwise, treat as thousands separator.
        last_comma = cleaned.rfind(",")
        after = cleaned[last_comma + 1:]
        if len(after) == 2:
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    try:
        val = float(cleaned)
    except ValueError:
        return None
    return abs(val)  # Field semantic is positive amount.


def _find_tenders(text: str) -> list[dict[str, str | float]]:
    """Return split-payment / multi-tender lines, or empty list.

    Walks the text line-by-line. Each line is matched against the
    tender catalogue most-specific-first; the FIRST tender keyword
    to match on a line claims that line. The list is returned ONLY
    when 2+ distinct tender entries are found because a single
    tender line is the ordinary case (already covered by the
    ``payment_method`` and ``tendered`` slots).

    Returns at most 10 entries (real-world split-bill receipts
    rarely exceed 4-6 components). Order preserves first-seen-in-
    OCR order so dashboards render the breakdown in receipt-print
    order.
    """
    if not text:
        return []
    out: list[dict[str, str | float]] = []
    seen_signatures: set[tuple[str, float]] = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        # Try each tender pattern in catalogue order. First match
        # on a line wins; we don't try to match multiple tenders
        # on the same line because real-world split receipts put
        # one tender per line.
        for pattern, kind in _TENDER_PATTERNS:
            m = pattern.search(line)
            if not m:
                continue
            amt = _parse_amount(m.group("amt"))
            if amt is None:
                break  # next line
            sig = (kind, amt)
            if sig in seen_signatures:
                break
            seen_signatures.add(sig)
            out.append({"kind": kind, "amount": amt})
            break
        if len(out) >= _MAX_TENDERS:
            break
    # Require 2+ distinct entries to surface (single tender is
    # already handled by payment_method/tendered).
    if len(out) < 2:
        return []
    return out


# Cash-rounding keywords printed on receipts in countries where small
# denomination coins are out of circulation. Ordered MOST-SPECIFIC
# first so multi-word forms win over short aliases. The bare
# ``rounding`` alias is the catch-all because that's the shortest
# unambiguous wording -- it does NOT misfire on prose because
# receipt OCR rarely contains full prose AND the regex requires a
# digit-amount immediately after the keyword.
_ROUNDING_KEYWORDS = (
    "rounding adjustment",
    "cash rounding",
    "cash discrepancy",
    "rounding",
    "round down",
    "round up",
)


def _find_signed_amount_after(text: str, keyword: str) -> float | None:
    """Return the SIGNED amount on the same line as ``keyword``.

    Mirrors ``_find_amount_after`` but captures an optional leading
    ``-`` (and an optional leading ``+`` for symmetry) on the
    amount. Cash-rounding adjustments are typically NEGATIVE on the
    receipt (the customer paid 0.02 less than the printed total) so
    a sign-aware capture is required -- the unsigned helper would
    return the absolute value and lose the sign.

    Returns the LAST occurrence on the same principle as
    ``_find_amount_after`` (a keyword that appears more than once
    is read last-wins).
    """
    pattern = re.compile(
        # Separator class is `:` ONLY (not `-`) because a leading
        # ``-`` immediately after the keyword belongs to the SIGN,
        # not the separator. ``_find_amount_after``'s own ``[:\-]?``
        # would consume the minus and leave the amount unsigned --
        # we cannot reuse it here.
        #
        # Sign can appear EITHER before the currency symbol
        # (``-$0.02``) OR after it (``$-0.02``). We capture both
        # placements but emit a single ``sign`` group that fires
        # whichever side carried it.
        rf"(?:(?<=\n)|(?<=^)|(?<=[^a-zA-Z])){re.escape(keyword)}\s*:?\s*"
        r"(?P<sign1>[+\-])?\s*[$€£¥]?\s*(?P<sign2>[+\-])?\s*"
        r"(?P<amt>\d{1,5}(?:[.,]\d{2}))",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return None
    last = matches[-1]
    amt = float(last.group("amt").replace(",", "."))
    sign = last.group("sign1") or last.group("sign2")
    if sign == "-":
        amt = -amt
    return amt


def _find_rounding(text: str) -> float | None:
    """Return the cash-rounding adjustment, or None.

    Recognises "Rounding -0.02", "Cash Rounding 0.03", "Rounding
    Adjustment -0.04", "Cash Discrepancy 0.01", "Round Down 0.02",
    "Round Up 0.03" (case-insensitive). The sign is preserved (a
    leading ``-`` on the amount is captured) so dashboards know
    whether the customer benefited (negative) or paid a tiny
    premium (positive).

    LAST-occurrence semantics for consistency with the other
    ``_find_amount_after`` callers. ``None`` when no rounding line
    is printed (the common case in countries that still use 1c / 2c
    coins).

    Distinct from ``discount`` (a marketing reduction the merchant
    chose) and ``change`` (the bills / coins handed back); rounding
    is a regulatory adjustment for small-coin scarcity.
    """
    for keyword in _ROUNDING_KEYWORDS:
        value = _find_signed_amount_after(text, keyword)
        if value is not None:
            return value
    return None


# Tax-jurisdiction keywords. Each entry is the canonical title-case
# rendering we emit; the matcher is case-insensitive. Recognised
# vocabularies:
#
#   * US: state / county / city / local / sales / federal / use
#     tax (each with the "Tax" suffix)
#   * Canada: HST, PST, GST, QST (no "Tax" suffix; the abbreviation
#     IS the jurisdiction name)
#   * EU / UK: VAT, EU VAT, Import VAT
#   * India: CGST, SGST, IGST, UTGST, CESS
#   * AU / NZ: GST (also matched by the Canada entry; same name)
#   * Specialty: Liquor Tax, Tobacco Tax, Hotel Tax, Lodging Tax,
#     Tourism Tax, Restaurant Tax, Resort Fee Tax, Service Tax
#
# Ordered MOST SPECIFIC FIRST so multi-word forms ("State Tax")
# win over the bare alias ("Tax") that already powers the top-level
# ``tax`` slot. The plain "Tax" keyword is intentionally NOT in
# this catalogue because a receipt that just prints "Tax 2.00"
# carries no jurisdiction signal -- the top-level ``tax`` field
# captures the amount and ``tax_lines`` stays empty for the single-
# line case.
_TAX_JURISDICTION_KEYWORDS: tuple[str, ...] = (
    # US multi-word forms (most specific first).
    "Resort Fee Tax",
    "Restaurant Tax",
    "Lodging Tax",
    "Tourism Tax",
    "Liquor Tax",
    "Tobacco Tax",
    "Hotel Tax",
    "Service Tax",
    "Federal Tax",
    "Sales Tax",
    "County Tax",
    "State Tax",
    "Local Tax",
    "City Tax",
    "Use Tax",
    # EU / UK.
    "Import VAT",
    "EU VAT",
    "VAT",
    # India (specific GST forms before bare GST).
    "UTGST",
    "CGST",
    "SGST",
    "IGST",
    "CESS",
    # Canada.
    "HST",
    "PST",
    "QST",
    # AU / NZ / Canada (bare GST is the shortest unambiguous tax tag).
    "GST",
)


def _find_tax_lines(text: str) -> list[dict[str, str | float]]:
    """Return the per-jurisdiction tax breakdown found in ``text``.

    Each entry is a ``{"jurisdiction": str, "amount": float}`` dict.
    Jurisdictions are emitted in the canonical title-case form from
    ``_TAX_JURISDICTION_KEYWORDS``. Amount is the signed positive
    float printed on the line (negative tax adjustments are extremely
    rare and would land via ``_find_amount_after``'s unsigned capture
    -- we accept that limitation and surface them as the absolute
    value).

    Returns an empty list when the receipt has 0 or 1 distinct tax
    jurisdictions. The single-line case (a bare ``Tax 2.00``) lives
    in the top-level ``tax`` slot; ``tax_lines`` only carries a
    breakdown when MULTIPLE jurisdictions appear so a dashboard can
    rely on ``len(tax_lines) > 0`` meaning "this receipt has a real
    multi-jurisdiction breakdown".

    Each (jurisdiction, line-position) pair is captured exactly once.
    A keyword that appears multiple times in OCR order (a printed
    summary echoing the line items) captures the LAST occurrence per
    jurisdiction, mirroring ``_find_amount_after``'s last-wins
    semantics. The returned list is sorted by source-text offset so a
    dashboard rendering the breakdown sees the same top-to-bottom
    ordering as the printer.
    """
    if not text:
        return []
    # Track (best_offset, amount, end_offset) per canonical jurisdiction.
    # We pick the LAST printed occurrence of each jurisdiction (matches
    # last-wins semantics for the top-level ``tax`` slot when a receipt
    # echoes the summary at the bottom), with the constraint that the
    # match cannot overlap any longer-keyword jurisdiction already
    # recorded (so ``VAT`` doesn't double-match inside ``Import VAT``).
    hits: dict[str, tuple[int, float, int]] = {}
    for keyword in _TAX_JURISDICTION_KEYWORDS:
        # We need both a per-keyword position AND the amount, so use a
        # local regex instead of calling _find_amount_after (which only
        # returns the value). Same separator class so we stay
        # compatible with the rest of the receipt extractor.
        pattern = re.compile(
            rf"(?:(?<=\n)|(?<=^)|(?<=[^a-zA-Z])){re.escape(keyword)}"
            r"\s*[:\-]?\s*[$€£¥]?\s*"
            r"(?P<amt>\d{1,5}(?:[.,]\d{2}))",
            re.IGNORECASE,
        )
        # Walk every match in source order. The longest-first keyword
        # ordering means the spans of already-recorded jurisdictions
        # are pinned; we accept the LAST current-keyword match that
        # doesn't overlap any of them. This keeps last-wins semantics
        # for echoed summary lines (a receipt that prints the totals
        # twice picks up the bottom copy) while preventing ``VAT``
        # from stealing the suffix of an ``Import VAT`` span recorded
        # by an earlier loop iteration.
        existing_spans = _spans(hits)
        chosen: re.Match[str] | None = None
        for m in pattern.finditer(text):
            start = m.start()
            end = m.end()
            overlap = any(
                existing_start <= start < existing_end
                or existing_start < end <= existing_end
                for existing_start, existing_end in existing_spans
            )
            if overlap:
                continue
            chosen = m
        if chosen is None:
            continue
        try:
            amt = float(chosen.group("amt").replace(",", "."))
        except ValueError:
            continue
        # Defensive: bound the amount at 0.01..99999.99 so a garbage
        # OCR match on a long number doesn't sneak in.
        if not (0.01 <= amt <= 99999.99):
            continue
        hits[keyword] = (chosen.start(), amt, chosen.end())
    # Sort by source-text offset and emit. We need len >= 2 for the
    # breakdown to be useful (one jurisdiction lives in the top-level
    # ``tax`` slot already).
    if len(hits) < 2:
        return []
    ordered = sorted(hits.items(), key=lambda kv: kv[1][0])
    return [{"jurisdiction": k, "amount": v[1]} for k, v in ordered]


def _spans(hits: dict[str, tuple[int, float, int]]) -> list[tuple[int, int]]:
    """Return the (start, end) spans of every recorded hit."""
    return [(v[0], v[2]) for v in hits.values()]


# Gift-card / store-credit / voucher keywords ordered MOST-SPECIFIC
# first so multi-word forms beat short aliases. The bare "Voucher"
# alias sits LAST because it's the most ambiguous: some restaurants
# print "Voucher Number: 12345" for promotional coupons (which the
# promo_code matcher should catch instead). To keep voucher from
# absorbing the promo case, the matcher requires a digit-amount on
# the SAME line (an alphanumeric tail like "Voucher Number: ABC123"
# fails the regex and falls through to promo_code).
_GIFT_CARD_KEYWORDS: tuple[str, ...] = (
    "gift card applied",
    "gift card redeemed",
    "gift card",
    "store credit applied",
    "store credit",
    "gc redeemed",
    "gc applied",
    "voucher applied",
    "voucher redeemed",
    "voucher",
)


def _find_gift_card_applied(text: str) -> float | None:
    """Return the gift-card amount applied to the receipt, or None.

    Recognises "Gift Card -25.00", "Gift Card Applied 25.00",
    "Store Credit -15.00", "GC Redeemed 10.00", "Voucher 5.00"
    (case-insensitive). Stored as a POSITIVE float regardless of
    whether the printer used a leading ``-``: the field's semantic
    is "amount knocked off by the gift card" and the sign is
    implied.

    LAST-occurrence semantics for consistency with the other
    receipt extractors. ``None`` when no gift-card line is printed.

    Distinct from ``discount`` (a marketing promotion) and
    ``tendered`` (the cash/card customer paid with) because a gift
    card is a stored-value tender that dashboards want to track
    separately for reconciliation.
    """
    for keyword in _GIFT_CARD_KEYWORDS:
        value = _find_signed_amount_after(text, keyword)
        if value is not None:
            # Always positive: the printer's sign carries no extra
            # information once we've identified the field's semantic.
            return abs(value)
    return None


# Promo / discount / coupon code keywords. We expect the value to
# be an alphanumeric CODE (not a money amount), so we use a
# dedicated regex distinct from ``_find_amount_after``. Ordered
# MOST SPECIFIC first so a multi-word form ("Promo Code") wins
# over a bare alias ("Code").
_PROMO_CODE_KEYWORDS: tuple[str, ...] = (
    "discount code",
    "coupon code",
    "voucher code",
    "promo code",
    "promotion code",
    "rebate code",
    "offer code",
    "referral code",
)


# Loyalty / rewards points-earned keywords. Receipts from
# point-issuing programmes (Starbucks Stars, Air Miles, hotel /
# airline / supermarket points) print the per-transaction earn as
# a small footer line. We catalogue the EARN vocabulary explicitly
# so a balance line (``Total Points: 1245`` / ``Points Balance:
# 1245`` / ``Current Points: 800``) is NEVER captured -- only the
# per-transaction earn from THIS receipt.
#
# Ordered most-specific-first so multi-word earn forms win over the
# bare ``Points`` alias. The bare ``Points`` matcher only fires when
# the balance-disqualifying vocabulary is NOT present anywhere on
# the same line.
_POINTS_EARNED_KEYWORDS: tuple[str, ...] = (
    # Multi-word earn forms (most specific first).
    "Points Earned",
    "Points Awarded",
    "Points Added",
    "Points Issued",
    "Stars Earned",
    "Stars Awarded",
    "Stars Added",
    "Miles Earned",
    "Miles Awarded",
    "Miles Added",
    "Rewards Earned",
    "Rewards Awarded",
    "Rewards Points Earned",
    "Reward Points Earned",
    "Reward Points",
    "Rewards Points",
    "Bonus Points",
    "Air Miles",
    "FF Miles",
    "Frequent Flyer Miles",
    "Loyalty Points",
    "Member Points",
    "Club Points",
    "Star Points",
    "Avios",
    # Bare aliases (last; balance-vocabulary guard below blocks misuse).
    "Points",
    "Stars",
    "Miles",
)

# Balance-vocabulary tokens that DISQUALIFY a candidate line. When
# any of these appear on the SAME line as a points keyword, the
# matcher rejects the line because it's reporting account balance,
# not per-transaction earn. We list this catalogue explicitly so
# adding a new disqualifier is a one-line change.
_POINTS_BALANCE_DISQUALIFIERS: tuple[str, ...] = (
    "balance",
    "total points",
    "current",
    "remaining",
    "available",
    "lifetime",
    "redeemable",
    "accumulated",
    "ytd",
    "year-to-date",
    "year to date",
)

_POINTS_EARNED_MIN = 1
_POINTS_EARNED_MAX = 1_000_000  # Defensive upper bound; real-world earns are rarely 6+ digits


def _find_points_earned(text: str) -> int | None:
    """Return the loyalty / rewards points earned for this receipt,
    or None.

    Walks every ``_POINTS_EARNED_KEYWORDS`` entry against every line.
    The keyword + numeric value pattern is the standard
    ``Keyword: NNN`` / ``Keyword NNN`` / ``Keyword #NNN`` shape with a
    digit-only or thousands-grouped integer value. Decimals are
    intentionally rejected (a points value is always a whole number).

    Balance-vs-earn distinction: any line that ALSO contains a
    balance-vocabulary token (``balance`` / ``total points`` /
    ``current`` / ``remaining`` / ``available`` / ``lifetime`` /
    ``redeemable`` / ``accumulated`` / ``ytd``) is skipped because
    the printer is reporting the account balance, not the
    per-receipt earn.

    First-match-wins per keyword priority: the most-specific
    keyword (``Points Earned``) is tried first; bare aliases
    (``Points``) only fire when no specific form matched. Within a
    single keyword, the LAST occurrence on the receipt wins (echoed
    summary footers).

    Bounds: 1..1_000_000. We reject 0 because a printed
    ``Points: 0`` line is almost always "card not scanned" rather
    than a genuine zero earn, and the false-positive cost of
    surfacing those is higher than the cost of missing a true zero
    earn. Values above 1_000_000 are rejected as defensive (a
    real-world per-receipt earn is rarely 6+ digits; OCR runs that
    high suggest a misread of the customer's account-balance).

    Negative values are rejected (a refund that subtracts points
    would print ``Points Redeemed: 10`` or ``Points Deducted: 10``;
    we don't capture redeem/deduct here because the field semantic
    is positive earn).

    ``None`` when no recognised earn line is present, when the
    candidate value is out of bounds, or when the only candidate
    sits on a balance line.
    """
    if not text:
        return None
    for keyword in _POINTS_EARNED_KEYWORDS:
        pattern = re.compile(
            rf"(?:(?<=\n)|(?<=^)|(?<=[^A-Za-z])){re.escape(keyword)}"
            r"\s*[:#\-]?\s*"
            # Integer only; thousands-grouped 1,234 accepted but a
            # decimal point disqualifies (we want pure integer). The
            # trailing negative-lookahead rejects (a) any additional
            # digit (so a 10-digit run doesn't partial-match as 7
            # digits + 3 extra) AND (b) a decimal separator + digit
            # (so 25.5 doesn't partial-match as 25).
            r"(?P<n>\d{1,3}(?:,\d{3})+|\d{1,7})"
            r"(?!\s*[.,]?\d)",
            re.IGNORECASE,
        )
        # Walk every match in source order; pick the LAST hit on a
        # NON-BALANCE line so an echoed footer wins over the header.
        chosen: int | None = None
        for m in pattern.finditer(text):
            # Find the line this match sits on so we can check for
            # balance-disqualifying vocabulary.
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            if line_end == -1:
                line_end = len(text)
            line = text[line_start:line_end].lower()
            if any(d in line for d in _POINTS_BALANCE_DISQUALIFIERS):
                continue
            raw_value = m.group("n").replace(",", "")
            try:
                value = int(raw_value)
            except ValueError:
                continue
            if not (_POINTS_EARNED_MIN <= value <= _POINTS_EARNED_MAX):
                continue
            chosen = value
        if chosen is not None:
            return chosen
    return None


# Tip-jar / digital-tip URL extraction. POS terminals (Square,
# Stripe Terminal, Toast, Clover) print a short URL or QR-code
# target at the bottom of restaurant / cafe receipts so the
# customer can tip via phone. Examples:
#
#   Tip QR: tip.example.com/abc123
#   Scan to tip: https://tipme.app/jane
#   Leave a tip online: tip.toasttab.com/r/123abc
#   Add a tip: square.link/tip/xy7
#   Tip your server: https://venmo.com/u/jane
#   Cash App: $jane
#
# We surface the URL (or Cash App / Venmo tag) for dashboards that
# want to track which merchants offer digital tipping.

# Keyword catalogue, ordered most-specific-first. Each entry is a
# (keyword-regex-fragment, vocabulary-needed) tuple where the
# vocabulary-needed flag is True when the URL on the same line
# must also contain "tip"-style vocabulary as a defence (the bare
# "Scan to" / "Scan code" form would otherwise misfire on a
# loyalty signup QR or marketing URL).
_TIP_URL_KEYWORDS: tuple[tuple[str, bool], ...] = (
    # Most specific: explicit "Tip URL" / "Tip QR" labels
    (r"tip\s*(?:qr|url|link|code)", False),
    # "Scan to tip" / "Scan to leave a tip"
    (r"scan\s+to\s+(?:tip|leave\s+a\s+tip|leave\s+tip)", False),
    # "Leave a tip" / "Leave a tip online" / "Add a tip"
    (r"(?:leave|add)\s+a\s+tip(?:\s+online)?", False),
    # "Tip your server" / "Tip your driver" / "Tip your barista"
    (r"tip\s+your\s+(?:server|driver|barista|courier|host|stylist|guide)", False),
    # "Digital tip" / "Online tip" / "Mobile tip"
    (r"(?:digital|online|mobile)\s+tip", False),
    # Bare "Tip:" followed by a URL on same line
    (r"tip", True),
)


# URL pattern for the captured value. We accept both http(s):// and
# bare hostnames because most printers omit the scheme to save ink.
# The hostname must contain at least one dot. Path / query / fragment
# accepted with conservative URL chars.
_TIP_URL_VALUE = (
    r"(?:https?://)?"
    r"(?:[a-zA-Z0-9][a-zA-Z0-9\-]{0,62}\.)+"
    r"[a-zA-Z]{2,24}"
    r"(?:/[A-Za-z0-9._~\-/?#&=+%@$()*]*)?"
)


# Compile the URL-based keyword matchers. The ``url`` group captures
# the URL itself.
_TIP_URL_REGEXES: list[tuple[re.Pattern[str], bool]] = []
for _kw, _needs_tip_in_url in _TIP_URL_KEYWORDS:
    _pat = re.compile(
        rf"(?<![A-Za-z])(?:{_kw})\s*[:#\-]?\s+(?P<url>{_TIP_URL_VALUE})",
        re.IGNORECASE,
    )
    _TIP_URL_REGEXES.append((_pat, _needs_tip_in_url))


# Cash App tag form: ``Cash App: $jane`` / ``$Cashtag: jane``.
# Cash App tags are case-insensitive and 1..20 alphanumeric chars.
_CASHAPP_TAG_RE = re.compile(
    r"(?<![A-Za-z])(?:cash\s*app|cash\s*tag|cashapp)\s*[:#\-]?\s*"
    r"(?P<tag>\$[A-Za-z][A-Za-z0-9_]{1,19})",
    re.IGNORECASE,
)

# Venmo tag form: ``Venmo: @jane`` -- Venmo handles use @ prefix.
_VENMO_TAG_RE = re.compile(
    r"(?<![A-Za-z])(?:venmo)\s*[:#\-]?\s*"
    r"(?P<tag>@[A-Za-z][A-Za-z0-9_\-\.]{1,29})",
    re.IGNORECASE,
)


def _find_tip_url(text: str) -> str | None:
    """Return the tip-jar URL / Cash App / Venmo tag printed on the
    receipt, or None.

    Tries each keyword catalogue entry in order (most-specific first).
    Returns the first match. The keyword + URL must sit on the same
    OCR line so a tipping URL doesn't accidentally pick up a
    randomly-placed merchant URL elsewhere in the receipt.

    The ``raw["urls"]`` cross-category extractor captures every URL
    in the receipt regardless of context; this helper specifically
    identifies the TIP URL so dashboards can surface "digital tip
    adoption" analytics per merchant.

    Cash App ``$tag`` and Venmo ``@handle`` shapes also qualify --
    a receipt that prints ``Cash App: $jane`` returns ``$jane`` as
    the captured value.
    """
    if not text:
        return None
    # First, try the URL-keyword matchers in priority order. We
    # search line by line so the keyword and URL must sit on the
    # SAME line (a tipping URL deeper in the receipt body that's not
    # paired with a keyword is just a regular URL).
    for line in text.splitlines():
        for pat, needs_tip_in_url in _TIP_URL_REGEXES:
            m = pat.search(line)
            if not m:
                continue
            url = m.group("url").strip().rstrip(",.;:")
            if needs_tip_in_url:
                # For the bare-"tip" keyword pattern, the URL itself
                # must contain "tip" (in host or path) as a defence.
                if "tip" not in url.lower():
                    continue
            return url
    # Fall back to Cash App / Venmo tag forms.
    cm = _CASHAPP_TAG_RE.search(text)
    if cm:
        return cm.group("tag")
    vm = _VENMO_TAG_RE.search(text)
    if vm:
        return vm.group("tag")
    return None


def _find_promo_code(text: str) -> str | None:
    """Return the promo / discount / coupon code applied, or None.

    Recognises "Promo Code: SAVE10", "Coupon Code SUMMER2024",
    "Discount Code WELCOME20", "Voucher Code GIFT5", and the bare
    "Code: NEWUSER" form (only when paired with a discount /
    promo / coupon keyword on the SAME line so a generic
    "Order Code: 12345" doesn't false-positive).

    LAST-occurrence semantics: a receipt that lists multiple codes
    (a refer-a-friend code AND a checkout promo) keeps the last
    one applied. Codes are stored verbatim (case-preserved) with
    surrounding punctuation stripped.

    ``None`` when no recognised code is present.
    """
    if not text:
        return None
    # Try the explicit "X Code: VALUE" forms first.
    for keyword in _PROMO_CODE_KEYWORDS:
        pattern = re.compile(
            rf"(?:(?<=\n)|(?<=^)|(?<=[^a-zA-Z])){re.escape(keyword)}"
            r"\s*[:#\-]?\s*"
            r"(?P<code>[A-Z0-9][A-Z0-9._\-]{1,31})\b",
            re.IGNORECASE,
        )
        matches = list(pattern.finditer(text))
        if matches:
            code = matches[-1].group("code")
            # Reject pure-digit codes longer than 2 digits because a
            # bare 5+ digit run after "Promo Code:" is almost always
            # an order number, not a promo code. Short numeric codes
            # (e.g. "Promo: 50") stay because some merchants use
            # them.
            if code.isdigit() and len(code) > 3:
                continue
            return code.strip(",.:;-")
    # Fall back to the "Code: VALUE" form ONLY when the line ALSO
    # contains a discount / promo / coupon vocabulary word. This
    # keeps "Order Code: 12345" / "Customer Code: ABC" from
    # false-positiving.
    for line in text.splitlines():
        low = line.lower()
        if not any(
            kw in low for kw in ("discount", "promo", "coupon", "voucher", "rebate")
        ):
            continue
        # Match a bare "Code: VALUE" on this line.
        m = re.search(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-zA-Z]))code\s*[:#\-]?\s*"
            r"(?P<code>[A-Z0-9][A-Z0-9._\-]{1,31})\b",
            line,
            re.IGNORECASE,
        )
        if m:
            code = m.group("code")
            if code.isdigit() and len(code) > 3:
                continue
            return code.strip(",.:;-")
    return None


# SKU / barcode / UPC / EAN / Item-Code / PLU printed alongside the
# line item. Recognised wording (case-insensitive; ordered
# most-specific-first so a "Item Code" beats a bare "Item #"):
#
#   SKU: 1234567                  -> 1234567
#   SKU 1234567                   -> 1234567
#   Barcode: 0123456789012        -> 0123456789012
#   Barcode 0123456789012         -> 0123456789012
#   UPC: 042100005264             -> 042100005264
#   EAN: 5012345678900            -> 5012345678900
#   Item Code: ABC-12345          -> ABC-12345
#   Item #ABC-12345               -> ABC-12345
#   Item No. ABC-99               -> ABC-99
#   PLU: 4011                     -> 4011
#
# The value catch (alphanumerics + dashes / underscores / dots /
# slashes) is bounded 3..32 chars to keep noisy OCR runs out. The
# regex is anchored to consume the keyword + value as a single
# group so callers can strip the matched span from the line and use
# the leftover description for the per-line parser.
_SKU_KEYWORD_RE = re.compile(
    r"(?<![A-Za-z])"
    r"(?:"
    r"item\s+(?:code|no\.?|number)|"
    r"item\s*#|"
    r"sku|barcode|upc|ean|gtin|plu"
    r")"
    r"\s*[:#\-]?\s*"
    r"(?P<sku>[A-Za-z0-9][A-Za-z0-9._/\-]{2,31})",
    re.IGNORECASE,
)


def _extract_sku_from_line(line: str) -> tuple[str | None, str]:
    """Return ``(sku, cleaned_line)`` where the SKU keyword + value
    span has been stripped from the line.

    Returns ``(None, line)`` unchanged when no SKU keyword is present.

    The SKU value preserves the original case (alphanumeric IDs are
    case-meaningful on many systems) and strips surrounding
    whitespace from the cleaned line so the per-item parser can
    re-parse it cleanly. Multiple SKU keywords on the same line
    collapse to the FIRST match because per-item SKUs are normally
    printed exactly once per line.
    """
    if not line:
        return None, line
    m = _SKU_KEYWORD_RE.search(line)
    if not m:
        return None, line
    sku = m.group("sku")
    # Strip the matched span; collapse multiple whitespace runs left
    # over to a single space so a description split across the SKU
    # ("Latte SKU: 12345 5.00" -> "Latte 5.00") re-parses cleanly.
    cleaned = (line[: m.start()] + " " + line[m.end():]).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return sku, cleaned


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


# Refund-reason extraction. When a POS system prompts the cashier
# to enter a reason for a refund / void / return, the receipt
# prints it as either:
#
#   "Refund - damaged goods"
#   "Refund: wrong size"
#   "Void Reason: pricing error"
#   "Return Reason: defective"
#   "Refund Reason: customer changed mind"
#   "Reason: customer satisfaction"          (only when refund_amount
#                                              is also present so the
#                                              bare ``Reason`` keyword
#                                              has anchor context)
#
# We extract the cleaned freeform string verbatim (case-preserved
# because cashier-entered reasons often quote the customer's
# exact wording).

# Priority order (most-specific first): compound keyword forms
# (``Refund Reason:`` / ``Void Reason:`` / ``Return Reason:``)
# beat the bare ``Reason:`` keyword which in turn beats the
# inline ``Refund - reason`` form. This ensures a receipt that
# prints both ``Refund 12.50`` AND ``Refund Reason: damaged``
# resolves to the explicit reason line.
_REFUND_REASON_COMPOUND = re.compile(
    r"(?:(?<=\n)|(?<=^)|(?<=[^a-zA-Z]))"
    r"(?:refund|void|return|cancel(?:lation|led)?|reversal)"
    r"\s+reason\s*[:\-]\s*"
    r"(?P<reason>[^\n\r]+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_REFUND_REASON_BARE = re.compile(
    r"(?:(?<=\n)|(?<=^)|(?<=[^a-zA-Z]))"
    r"reason\s*[:\-]\s*"
    r"(?P<reason>[^\n\r]+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# Inline refund-with-reason form: the refund keyword + separator +
# free-form reason on the SAME line. Excludes lines that contain a
# numeric amount because those are the ``Refund 12.50`` totals line.
# Examples that should match:
#   Refund - damaged goods
#   REFUND: wrong size
#   Void: pricing error
#   Return: defective merchandise
# Examples that should NOT match:
#   Refund 12.50
#   REFUND: $12.50
#   Refund Amount: -25.00
_REFUND_REASON_INLINE = re.compile(
    r"(?:(?<=\n)|(?<=^)|(?<=[^a-zA-Z]))"
    r"(?:refund|void(?:ed)?|return(?:ed)?|cancel(?:lation|led)?|reversal)"
    r"\s*[:\-]\s*"
    r"(?P<reason>[^\n\r]+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _clean_reason(raw: str) -> str | None:
    """Trim and validate a captured reason string.

    Returns ``None`` when the cleaned reason is:
      * empty after stripping whitespace / punctuation
      * a pure number (the ``Refund: 12.50`` total line leaks
        through to us; we filter)
      * a currency-amount shape (``$12.50``, ``-25.00``)
      * the literal word ``transaction`` / ``sale`` / ``payment``
        (these are status words that follow ``Void``/``Cancel`` on
        a totals line)
    """
    if not raw:
        return None
    cleaned = raw.strip().rstrip(".,;:")
    if not cleaned:
        return None
    # Reject if the cleaned text is just a number or currency amount.
    if re.match(r"^[-]?[$€£¥]?\s*\d+(?:[.,]\d{1,3})?$", cleaned):
        return None
    # Reject status words that follow Void/Cancel on totals lines.
    status_only = {
        "transaction", "sale", "payment", "amount", "total",
    }
    if cleaned.lower() in status_only:
        return None
    # Reject overly-long captures (likely OCR noise picking up the
    # next line). Real reasons are typically 1..80 characters.
    if len(cleaned) > 120:
        return None
    return cleaned


def _find_refund_reason(text: str, has_refund_amount: bool) -> str | None:
    """Return the refund / void / return reason, or None.

    The ``has_refund_amount`` flag controls whether the bare
    ``Reason:`` keyword counts as evidence -- without an
    anchoring refund amount on the same receipt, the bare
    keyword is too generic (a receipt for a normal sale may
    print "Reason: subscription renewal" alongside a charge
    description and we don't want that to misfire as a refund).

    Priority order:
    1. Compound keyword forms (``Refund Reason:`` /
       ``Void Reason:`` / ``Return Reason:``) -- the
       most-specific signal.
    2. Bare ``Reason:`` keyword (ONLY when has_refund_amount is True).
    3. Inline ``Refund - <reason>`` / ``Void: <reason>`` form
       (the same-line refund keyword followed by a reason).

    Last-match-wins within each priority tier so a receipt that
    prints both a refund total line AND a follow-up reason line
    captures the reason from the dedicated line.
    """
    if not text:
        return None
    # 1) Compound keyword forms beat everything else.
    matches = list(_REFUND_REASON_COMPOUND.finditer(text))
    if matches:
        for m in reversed(matches):
            cleaned = _clean_reason(m.group("reason"))
            if cleaned is not None:
                return cleaned
    # 2) Bare ``Reason:`` keyword -- only when a refund amount is
    #    also present (avoid false-positives on normal sales).
    if has_refund_amount:
        matches = list(_REFUND_REASON_BARE.finditer(text))
        if matches:
            for m in reversed(matches):
                cleaned = _clean_reason(m.group("reason"))
                if cleaned is not None:
                    return cleaned
    # 3) Inline ``Refund - <reason>`` form. We only try this when no
    #    higher-priority match landed -- and we have to discriminate
    #    "Refund - damaged goods" (reason!) from "Refund: $12.50"
    #    (amount masquerading as reason). The _clean_reason helper
    #    catches the amount case via the pure-number check.
    matches = list(_REFUND_REASON_INLINE.finditer(text))
    if matches:
        for m in reversed(matches):
            cleaned = _clean_reason(m.group("reason"))
            if cleaned is not None:
                return cleaned
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


# Signature / signed-by detection. Credit-card slips and delivery
# receipts commonly print a signature line near the bottom:
#
#   Signature: ________________
#   Signature: Bob Smith
#   X___________________________
#   X: Bob Smith
#   Signed by: Bob Smith
#   Customer signature: Alice
#   Cardholder signature: ___________
#   Authorized by: Charlie
#
# We surface a small dict so dashboards can distinguish a present-but-
# blank signature box from a named signer. The detector tries each
# keyword in priority order (most-specific first); the first non-empty
# match wins.
_SIGNATURE_KEYWORDS: tuple[str, ...] = (
    r"customer\s+signature",
    r"cardholder\s+signature",
    r"merchant\s+signature",
    r"authorized\s+signature",
    r"authorised\s+signature",
    r"authorized\s+by",
    r"authorised\s+by",
    r"signed\s+by",
    r"signature",
    # Bare ``X`` placeholder line: ``X____`` (with the underscore
    # filler) or ``X: Bob`` (with a name) or ``X.`` (handled below).
    r"x",
)
# Captured signer-name tail. We accept the same letter / dot / dash /
# apostrophe set as the cashier / server matchers so multi-part names
# (``Mary-Jane O'Brien``) survive. Bounded 1..30 chars; the trailing
# trim normalises whitespace.
_SIGNATURE_NAME_TAIL = r"(?P<name>[A-Za-z][A-Za-z .'\-]{0,29})"
# Placeholder-only tail: any run of underscores / dashes / dots / spaces
# / or the literal word ``_____`` (commonly OCR'd as a mix). Empty
# string is also accepted as ``present`` because some receipts print
# the bare ``Signature:`` keyword and rely on a visual line beneath.
_SIGNATURE_PLACEHOLDER = re.compile(r"^[\s_\-.]*$")


def _find_signature(text: str) -> dict[str, str | bool] | None:
    """Return a signature dict (``{"present": True}`` or
    ``{"present": True, "name": "Bob"}``), or ``None`` when no
    signature line is present.

    Detection rule: scan each line; the first matching keyword wins.
    When the value after the keyword looks like a real name we
    surface it under the ``name`` key; when the value is empty or
    purely placeholder characters (underscores / dashes / dots /
    spaces) we surface ``{"present": True}`` only.

    The bare ``X`` keyword is matched conservatively: it must sit at
    the START of a line (after optional whitespace) and be followed
    by either a placeholder run OR a separator (``:`` / space) + name.
    A stray ``X`` in prose (``X-Ray``, ``X11``) is rejected by the
    word-boundary requirement.
    """
    if not text:
        return None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for kw in _SIGNATURE_KEYWORDS:
            if kw == "x":
                # Bare ``X`` -- only fire at start of line with the
                # placeholder / name shape immediately after. The
                # separator between ``X`` and the rest may be ``:`` /
                # ``.`` or whitespace; we explicitly DO NOT accept
                # ``-`` as a separator because ``X-Ray`` / ``X-Wing``
                # / hyphenated compound words would otherwise look
                # like signature lines.
                m = re.match(
                    r"^[Xx](?:\s*[:.]?\s*(?P<rest>.*))?$",
                    line,
                )
                if not m:
                    continue
                rest = (m.group("rest") or "").strip()
                # Reject hyphen-led rest (``X-Ray``, ``X-Wing``) --
                # this is a hyphenated compound, not a signature.
                if rest.startswith("-"):
                    continue
                # Reject if the captured ``X`` is actually part of a
                # word. We have a non-placeholder rest; require it to
                # start with a letter (a name) and not a digit
                # (X11) or a digit-letter mix.
                if rest and not _SIGNATURE_PLACEHOLDER.match(rest):
                    if not rest[0].isalpha():
                        continue
                    # Reject single-token all-caps that looks like
                    # an acronym/code rather than a name (X RAY,
                    # X TERMINAL). A real signed name has a vowel.
                    if rest.isupper() and not any(c in "AEIOUaeiou" for c in rest):
                        continue
                if not rest or _SIGNATURE_PLACEHOLDER.match(rest):
                    return {"present": True}
                # Name capture for the bare-X case.
                nm = re.match(_SIGNATURE_NAME_TAIL, rest)
                if nm:
                    name = nm.group("name").strip().rstrip(".,;:-")
                    if "  " in name:
                        name = name.split("  ", 1)[0].strip()
                    name = re.sub(r"\s+", " ", name)
                    if name and any(c.isalpha() for c in name):
                        return {"present": True, "name": name}
                return {"present": True}
            # Worded keyword (Signature / Signed by / etc).
            pat = re.compile(
                rf"^(?P<lead>.*?)(?<![A-Za-z]){kw}\s*[:\-]?\s*(?P<rest>.*)$",
                re.IGNORECASE,
            )
            m = pat.match(line)
            if not m:
                continue
            # Reject when the keyword sits deep inside the line and
            # the lead text looks like prose (e.g. ``please sign at
            # the X``) -- only fire when the keyword is at the start
            # of the line OR after a small prefix that itself is
            # signature-context (a star / dash bullet).
            lead = m.group("lead").strip()
            if lead and not re.match(r"^[\*\-\u2022]+$", lead):
                continue
            rest = m.group("rest").strip()
            if not rest or _SIGNATURE_PLACEHOLDER.match(rest):
                return {"present": True}
            nm = re.match(_SIGNATURE_NAME_TAIL, rest)
            if nm:
                name = nm.group("name").strip().rstrip(".,;:-")
                if "  " in name:
                    name = name.split("  ", 1)[0].strip()
                name = re.sub(r"\s+", " ", name)
                if name and any(c.isalpha() for c in name):
                    return {"present": True, "name": name}
            return {"present": True}
    return None


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


# Line-item modifier / customisation detection. Restaurant POS
# systems print add-ons / removes / substitutions on indented
# lines beneath the item they belong to:
#
#   Burger                12.00
#     + Add bacon          2.00
#     - No onions
#     * Substitute fries
#
# Recognised prefix markers (in priority order so the most
# specific shape claims first):
# * ``+`` / ``Add`` / ``Extra`` / ``With`` / ``w/`` -> kind="add"
# * ``-`` / ``No`` / ``Without`` / ``w/o`` / ``Hold`` / ``Omit`` / ``Skip`` -> kind="remove"
# * ``*`` / ``Sub`` / ``Substitute`` / ``Swap`` -> kind="sub"
# * Otherwise: bare freeform text on an indented line -> kind="note"
#
# Price suffix (``+ Add bacon 2.00``) is captured into the ``price``
# slot. Free customisations (``- No onions``) leave ``price=None``.

_MOD_ADD_PREFIX_RE = re.compile(
    r"^[+]\s+(?P<text>.+?)(?:\s+(?P<price>\d+(?:[.,]\d{2})))?\s*$",
)
_MOD_REMOVE_PREFIX_RE = re.compile(
    r"^[-](?!\s*\d)\s+(?P<text>.+?)(?:\s+(?P<price>\d+(?:[.,]\d{2})))?\s*$",
)
_MOD_SUB_PREFIX_RE = re.compile(
    r"^[*]\s+(?P<text>.+?)(?:\s+(?P<price>\d+(?:[.,]\d{2})))?\s*$",
)
# Word-prefix forms (no sigil, but distinctive keyword). The keyword
# is consumed in the priority dispatch so a line ``Add bacon 2.00``
# is captured as add-kind with text="bacon" price=2.00.
_MOD_ADD_WORD_RE = re.compile(
    r"^(?:add|extra|with|w/)\s+(?P<text>.+?)(?:\s+(?P<price>\d+(?:[.,]\d{2})))?\s*$",
    re.IGNORECASE,
)
_MOD_REMOVE_WORD_RE = re.compile(
    r"^(?:no|without|w/o|hold|omit|skip|less)\s+(?P<text>.+?)\s*$",
    re.IGNORECASE,
)
_MOD_SUB_WORD_RE = re.compile(
    r"^(?:sub|substitute|swap|replace)\s+(?P<text>.+?)\s*$",
    re.IGNORECASE,
)

# Maximum number of modifiers attached per item. A single base
# item rarely has more than a few customisations in practice.
_MAX_MODIFIERS_PER_ITEM = 10


def _parse_modifier_line(line: str, indented: bool) -> dict | None:
    """Return a modifier dict for ``line`` or None if it isn't a
    recognised modifier shape.

    The ``indented`` flag tells us whether the source line was
    indented in the original receipt text -- bare word-prefix
    forms (``Add bacon``) ONLY count as modifiers when the line was
    indented because the word ``Add`` could otherwise appear as
    the start of a legitimate item name on a non-indented line.

    Sigil-prefix forms (``+ Add bacon``, ``- No onions``,
    ``* Substitute fries``) fire whether or not the line is
    indented because the sigil itself is the distinctive signal.
    """
    if not line:
        return None
    cleaned = line.rstrip()
    if not cleaned:
        return None

    # Sigil-prefix forms first (the sigil is the strongest signal).
    m = _MOD_ADD_PREFIX_RE.match(cleaned)
    if m:
        text = m.group("text").strip().strip(".,:;-")
        price_raw = m.group("price")
        price = float(price_raw.replace(",", ".")) if price_raw else None
        if text and 1 <= len(text) <= 80:
            return {"kind": "add", "text": text, "price": price}

    m = _MOD_REMOVE_PREFIX_RE.match(cleaned)
    if m:
        text = m.group("text").strip().strip(".,:;-")
        price_raw = m.group("price")
        price = float(price_raw.replace(",", ".")) if price_raw else None
        if text and 1 <= len(text) <= 80:
            return {"kind": "remove", "text": text, "price": price}

    m = _MOD_SUB_PREFIX_RE.match(cleaned)
    if m:
        text = m.group("text").strip().strip(".,:;-")
        price_raw = m.group("price")
        price = float(price_raw.replace(",", ".")) if price_raw else None
        if text and 1 <= len(text) <= 80:
            return {"kind": "sub", "text": text, "price": price}

    # Word-prefix forms require indentation so they don't false-
    # positive on item names that start with the keyword
    # ("Add Pizza Special").
    if not indented:
        return None

    m = _MOD_ADD_WORD_RE.match(cleaned)
    if m:
        text = m.group("text").strip().strip(".,:;-")
        price_raw = m.group("price")
        price = float(price_raw.replace(",", ".")) if price_raw else None
        if text and 1 <= len(text) <= 80:
            return {"kind": "add", "text": text, "price": price}

    m = _MOD_REMOVE_WORD_RE.match(cleaned)
    if m:
        text = m.group("text").strip().strip(".,:;-")
        if text and 1 <= len(text) <= 80:
            return {"kind": "remove", "text": text, "price": None}

    m = _MOD_SUB_WORD_RE.match(cleaned)
    if m:
        text = m.group("text").strip().strip(".,:;-")
        if text and 1 <= len(text) <= 80:
            return {"kind": "sub", "text": text, "price": None}

    # Bare indented note. Only count when the line is short enough to
    # plausibly be a note (not the next item's description) and has
    # no trailing price tail (a price would make it a regular item).
    if re.search(r"\s\d+(?:[.,]\d{2})\s*$", cleaned):
        return None
    if 1 <= len(cleaned) <= 60:
        return {"kind": "note", "text": cleaned.strip(), "price": None}

    return None


def _parse_items(text: str) -> list[ReceiptLine]:
    items: list[ReceiptLine] = []
    for raw in text.splitlines():
        # Detect indentation BEFORE stripping so we can route
        # indented lines to the modifier parser when no item-shape
        # matches.
        indented = bool(raw) and raw[0] in (" ", "\t")
        line = raw.strip()
        if not line:
            continue
        # 0a) Per-line SKU / barcode extraction. We strip the SKU
        #     keyword + value off the line BEFORE the per-item parsers
        #     fire so a line like "Latte SKU: 12345 5.00" parses as
        #     "Latte 5.00" with sku=12345 attached. A line that is
        #     ONLY a SKU declaration ("SKU: 12345" on its own) attaches
        #     to the LAST item already in the list -- that mirrors how
        #     retail printers commonly print the SKU on the line
        #     below the item description.
        sku, line = _extract_sku_from_line(line)
        if sku is not None and not line:
            if items:
                items[-1].sku = sku
            continue
        low = line.lower()
        # 0b) Per-item percent-off discount. Run BEFORE the keyword skip
        #     so a line like ``Promo: BOGO 50% off Latte 4.00`` is parsed
        #     as a discounted item even though it contains the
        #     ``promo`` / ``discount`` keywords that would otherwise
        #     push it through ``continue``. We only short-circuit when
        #     the line genuinely has a ``\d+% off`` clause.
        if re.search(r"\d{1,2}\s*%\s*off\b", line, re.IGNORECASE):
            discounted = _try_pct_off(line)
            if discounted is not None:
                if sku is not None:
                    discounted.sku = sku
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
                items.append(ReceiptLine(description=desc, qty=qty, price=unit, sku=sku))
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
                items.append(ReceiptLine(description=desc, qty=qty, price=unit, sku=sku))
                if len(items) >= 30:
                    break
                continue
        # 3) Bare desc + price (original behaviour).
        m = re.search(r"^(.*?)\s+(\d+(?:[.,]\d{2}))$", line)
        if not m:
            # The line had no recognisable price tail. Two interpretation
            # paths:
            #
            # 3a) SKU keyword on an item-less line attaches to the last
            #     item (existing behaviour).
            # 3b) Otherwise check if the line is a modifier shape
            #     (+ Add bacon / - No onions / * Substitute fries /
            #     bare indented note / Word-prefix Add bacon /
            #     No onions / Sub fries) and attach to the last item.
            if sku is not None and items:
                items[-1].sku = sku
                continue
            if items:
                mod = _parse_modifier_line(line, indented)
                if mod is not None and len(items[-1].modifiers) < _MAX_MODIFIERS_PER_ITEM:
                    items[-1].modifiers.append(mod)
            continue
        desc = m.group(1).strip().strip(".:-")
        try:
            price = float(m.group(2).replace(",", "."))
        except ValueError:
            continue
        if 0.01 <= price <= 9999 and 2 <= len(desc) <= 60:
            # Before treating this as a fresh item, check if it's a
            # modifier with a price tail (e.g. ``+ Add bacon 2.00``).
            # Modifier lines with explicit sigils trump the
            # base-item interpretation.
            if items:
                mod = _parse_modifier_line(line, indented)
                if mod is not None and mod["kind"] in ("add", "remove", "sub") and \
                   len(items[-1].modifiers) < _MAX_MODIFIERS_PER_ITEM:
                    items[-1].modifiers.append(mod)
                    continue
            items.append(ReceiptLine(description=desc, price=price, sku=sku))
    return items[:30]


def _find_recurring(text: str) -> dict[str, str | None] | None:
    """Return recurring / subscription marker dict, or None.

    Returns a dict with keys ``interval`` (canonical cadence tag
    or None), ``next_charge`` (next-billing date verbatim or None),
    and ``keyword`` (the literal phrase that fired the matcher).

    Recognised markers fall into three families:

    1. **Cadence-bearing keywords** (most specific): ``Monthly
       subscription``, ``Annual subscription``, ``Recurring
       monthly``, ``Billed monthly``, ``Renews monthly``, ``Charged
       weekly``, ``Quarterly subscription``, etc.
    2. **Auto-renew keywords**: ``Auto-renew``, ``Auto renews``,
       ``Automatic renewal``, ``Renews on <date>``.
    3. **Subscription / recurring keywords** (least specific):
       ``Subscription``, ``Recurring charge``, ``Recurring
       payment``, ``This is a recurring charge``.

    Distinct from a one-off charge: a regular retail / restaurant
    receipt has NO recurring keyword, so this returns None for
    99% of receipts.

    Side-effect: if a ``Next charge: <date>`` or ``Renews on
    <date>`` is printed on the SAME line or one of the next 2
    lines after the recurring keyword, the date is captured into
    ``next_charge``.

    Trial-period markers (``Free trial``, ``Trial ends on X``,
    ``Trial expires``) are tagged as ``interval='trial'`` because
    a trial that ends triggers a real subscription charge -- the
    dashboard surfaces these so the user can audit upcoming
    automatic conversions.

    Safety:
    * Bare ``subscribe`` / ``subscription`` matchers require
      the keyword to be standalone or preceded by a structural
      character (line-start, colon, period, space) so prose
      like ``Subscriber count`` doesn't false-positive.
    * Bare ``Monthly`` alone (without subscription / charge /
      bill context) does NOT fire because plain ``Monthly``
      sometimes appears in newsletter footers.
    """
    if not text:
        return None
    # Map of keyword -> canonical interval tag. Order MATTERS --
    # longest / most-specific patterns first so the multi-word
    # forms beat the bare aliases.
    candidates: list[tuple[re.Pattern, str | None]] = [
        # Cadence-bearing multi-word forms. Longer / more-specific
        # patterns come FIRST so "Semi-annual subscription" beats
        # "Annual subscription" and "Biweekly subscription" beats
        # "Weekly subscription".
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Semi-annual subscription)",
            re.IGNORECASE,
        ), "semiannual"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Biweekly subscription)",
            re.IGNORECASE,
        ), "biweekly"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Monthly subscription)",
            re.IGNORECASE,
        ), "monthly"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Annual subscription)",
            re.IGNORECASE,
        ), "annual"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Yearly subscription)",
            re.IGNORECASE,
        ), "annual"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Weekly subscription)",
            re.IGNORECASE,
        ), "weekly"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Quarterly subscription)",
            re.IGNORECASE,
        ), "quarterly"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Daily subscription)",
            re.IGNORECASE,
        ), "daily"),
        # Billed / charged + cadence.
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Billed monthly)",
            re.IGNORECASE,
        ), "monthly"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Billed annually)",
            re.IGNORECASE,
        ), "annual"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Billed weekly)",
            re.IGNORECASE,
        ), "weekly"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Billed quarterly)",
            re.IGNORECASE,
        ), "quarterly"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Charged monthly)",
            re.IGNORECASE,
        ), "monthly"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Charged annually)",
            re.IGNORECASE,
        ), "annual"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Recurring monthly)",
            re.IGNORECASE,
        ), "monthly"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Recurring annually)",
            re.IGNORECASE,
        ), "annual"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Recurring weekly)",
            re.IGNORECASE,
        ), "weekly"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Renews monthly)",
            re.IGNORECASE,
        ), "monthly"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Renews annually)",
            re.IGNORECASE,
        ), "annual"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Renews weekly)",
            re.IGNORECASE,
        ), "weekly"),
        # Trial markers.
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Free trial)",
            re.IGNORECASE,
        ), "trial"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Trial period)",
            re.IGNORECASE,
        ), "trial"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Trial ends)",
            re.IGNORECASE,
        ), "trial"),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Trial expires)",
            re.IGNORECASE,
        ), "trial"),
        # Auto-renew family.
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Auto[\- ]renews)",
            re.IGNORECASE,
        ), None),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Auto[\- ]renew)",
            re.IGNORECASE,
        ), None),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Automatic renewal)",
            re.IGNORECASE,
        ), None),
        # Recurring family.
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Recurring charge)",
            re.IGNORECASE,
        ), None),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Recurring payment)",
            re.IGNORECASE,
        ), None),
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Recurring billing)",
            re.IGNORECASE,
        ), None),
        # Bare subscription.
        (re.compile(
            r"(?:(?<=\n)|(?<=^)|(?<=[^a-z]))(Subscription)\b",
            re.IGNORECASE,
        ), None),
    ]
    for pat, interval in candidates:
        m = pat.search(text)
        if not m:
            continue
        keyword = m.group(1).strip()
        # Look for a next-charge / renewal date on the same or next
        # 2 lines.
        next_charge = _find_next_charge_date(text, m.end())
        return {
            "interval": interval,
            "next_charge": next_charge,
            "keyword": keyword,
        }
    return None


# Next-charge date patterns: ``Next charge: 2024-03-15`` /
# ``Renews on April 1, 2024`` / ``Renewal: 2024-03-15`` etc.
_NEXT_CHARGE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(
        r"(?:Next charge|Next billing|Next payment)"
        r"[\s:#\-]+(?P<date>[A-Za-z0-9 ,/\-:.]{4,40})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:Renews on|Renewal date|Renewal on|Renews)"
        r"[\s:#\-]+(?P<date>[A-Za-z0-9 ,/\-:.]{4,40})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:Auto[\- ]renews on)"
        r"[\s:#\-]+(?P<date>[A-Za-z0-9 ,/\-:.]{4,40})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:Trial ends on|Trial expires on)"
        r"[\s:#\-]+(?P<date>[A-Za-z0-9 ,/\-:.]{4,40})",
        re.IGNORECASE,
    ),
)


def _find_next_charge_date(text: str, after_offset: int) -> str | None:
    """Find a next-charge date within ~3 lines of ``after_offset``.

    We search the WHOLE remaining text rather than just the
    adjacent lines because a Stripe-issued receipt often prints
    the recurring keyword in the header and the next-charge date
    in the body. Returns ``None`` when no recognised date pattern
    fires.
    """
    if not text:
        return None
    # Search both BEFORE and AFTER the marker because some
    # receipts print the renewal date in the header (above the
    # keyword) and others print it below.
    for pat in _NEXT_CHARGE_PATTERNS:
        for m in pat.finditer(text):
            date = m.group("date").strip()
            # Strip trailing punctuation / phrases.
            date = re.sub(r"\s+(at|in|until|by|via|to)\s+.*$", "", date, flags=re.IGNORECASE)
            date = date.rstrip(",.;:")
            date = date.strip()
            if date and len(date) >= 4:
                return date
    return None


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
    refund_amount = _find_refund_amount(text)
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
        refund_amount=refund_amount,
        refund_reason=_find_refund_reason(text, refund_amount is not None),
        loyalty_id=_find_loyalty_id(text),
        store_id=_find_store_id(text),
        register_id=_find_register_id(text),
        cashier=_find_cashier(text),
        server=_find_server(text),
        signature=_find_signature(text),
        service_charge=_find_service_charge(text),
        delivery_fee=_find_delivery_fee(text),
        tendered=_find_tendered(text),
        change=_find_change(text),
        rounding=_find_rounding(text),
        tax_lines=_find_tax_lines(text),
        gift_card_applied=_find_gift_card_applied(text),
        promo_code=_find_promo_code(text),
        suggested_tips=_find_suggested_tips(text),
        points_earned=_find_points_earned(text),
        tip_url=_find_tip_url(text),
        tenders=_find_tenders(text),
        recurring=_find_recurring(text),
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
        "party_size", "refund_amount", "refund_reason", "loyalty_id", "store_id",
        "register_id", "cashier", "server", "signature",
        "service_charge", "delivery_fee", "tendered", "change",
        "rounding", "gift_card_applied", "promo_code", "points_earned",
        "tip_url", "recurring",
    ):
        if getattr(merged, f) in (None, "", 0):
            setattr(merged, f, getattr(parsed, f))
    if not merged.items:
        merged.items = parsed.items
    # Backfill tax_lines when caller supplied none. We never override
    # a non-empty caller-supplied list because the LLM may have
    # surfaced a richer breakdown than the regex-based extractor can.
    if not merged.tax_lines:
        merged.tax_lines = parsed.tax_lines
    # Backfill suggested_tips when caller supplied none. Same rule as
    # tax_lines -- the LLM may surface the table; if not, the regex
    # pass fills it.
    if not merged.suggested_tips:
        merged.suggested_tips = parsed.suggested_tips
    # Backfill tenders when caller supplied none. The LLM may have
    # surfaced an explicit split-tender breakdown from the OCR
    # screenshot; if not, the regex pass fills it from the
    # printed lines.
    if not merged.tenders:
        merged.tenders = parsed.tenders
    # Backfill recurring marker when caller supplied none. The LLM
    # may surface the subscription marker; if not, the regex pass
    # fills it from the printed keyword.
    if merged.recurring is None:
        merged.recurring = parsed.recurring
    # Recompute tip_percent against the merged tip + subtotal/total so a
    # caller that only supplied a subtotal still gets a derived percent
    # when the OCR pass discovered the tip.
    if merged.tip_percent in (None, 0):
        merged.tip_percent = _compute_tip_percent(
            merged.tip, merged.subtotal, merged.total
        )
    return merged
