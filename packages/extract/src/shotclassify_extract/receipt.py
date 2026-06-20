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


def _detect_currency(text: str) -> str | None:
    for symbol, code in [("$", "USD"), ("€", "EUR"), ("£", "GBP"), ("¥", "JPY")]:
        if symbol in text:
            return code
    if re.search(r"\busd\b", text, re.IGNORECASE):
        return "USD"
    if re.search(r"\beur\b", text, re.IGNORECASE):
        return "EUR"
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
            "change", "cash",
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


def parse_receipt_text(text: str) -> ReceiptFields:
    return ReceiptFields(
        vendor=_guess_vendor(text),
        date=_guess_date(text),
        subtotal=_find_amount_after(text, "subtotal"),
        tax=_find_amount_after(text, "tax") or _find_amount_after(text, "vat"),
        tip=_find_tip(text),
        total=_find_amount_after(text, "total"),
        currency=_detect_currency(text),
        items=_parse_items(text),
    )


def enrich_receipt(existing: ReceiptFields | None, ocr: OCRResult) -> ReceiptFields:
    parsed = parse_receipt_text(ocr.text)
    if existing is None:
        return parsed
    merged = existing.model_copy()
    for f in ("vendor", "date", "subtotal", "tax", "tip", "total", "currency"):
        if getattr(merged, f) in (None, "", 0):
            setattr(merged, f, getattr(parsed, f))
    if not merged.items:
        merged.items = parsed.items
    return merged
