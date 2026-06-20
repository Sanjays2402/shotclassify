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
    for symbol, code in [("$", "USD"), ("€", "EUR"), ("£", "GBP"), ("¥", "JPY")]:
        if symbol in text:
            return code
    if re.search(r"\busd\b", text, re.IGNORECASE):
        return "USD"
    if re.search(r"\beur\b", text, re.IGNORECASE):
        return "EUR"
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


def _parse_items(text: str) -> list[ReceiptLine]:
    items: list[ReceiptLine] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if any(k in low for k in [
            "subtotal", "total", "tax", "vat", "tip", "gratuity", "service",
            "change", "cash", "discount", "coupon", "promo", "savings",
            "loyalty", "rewards",
        ]):
            continue
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
        items=_parse_items(text),
    )


def enrich_receipt(existing: ReceiptFields | None, ocr: OCRResult) -> ReceiptFields:
    parsed = parse_receipt_text(ocr.text)
    if existing is None:
        return parsed
    merged = existing.model_copy()
    for f in (
        "vendor", "date", "subtotal", "tax", "tip", "discount", "total",
        "currency", "payment_method",
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
