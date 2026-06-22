"""Receipt tendered / change extraction (cash-handling receipts).

Two new ``ReceiptFields`` slots for cash-receipt parsing:

* ``tendered`` -- the cash amount handed to the cashier (``Tendered
  20.00`` / ``Cash 20.00`` / ``Paid 20.00`` / ``Cash Tendered 20.00``
  / ``Tender 20.00`` / ``Amount Tendered 20.00`` / ``Amount Paid
  20.00`` / ``Payment 20.00``).
* ``change`` -- the change handed back (``Change 7.50`` / ``Change
  Due 7.50`` / ``Change Given 7.50`` / ``Cash Change 7.50``).

Both use last-occurrence semantics for consistency with the other
``_find_amount_after`` callers (tip / discount / service-charge /
delivery-fee). ``None`` for card-only receipts that do not break out
a tender / change pair.

Dashboards use the (tendered, change) pair to spot till-discrepancy
anomalies (a cashier who consistently mis-keys tendered amounts will
show up as elevated change variance).
"""
from __future__ import annotations

from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract import enrich_receipt
from shotclassify_extract.receipt import (
    _find_change,
    _find_tendered,
    parse_receipt_text,
)

# ---- _find_tendered ------------------------------------------------


def test_tendered_basic():
    assert _find_tendered("Tendered 20.00\n") == 20.00


def test_tendered_cash_tendered_form():
    assert _find_tendered("Cash Tendered 20.00\n") == 20.00


def test_tendered_amount_tendered_form():
    assert _find_tendered("Amount Tendered 20.00\n") == 20.00


def test_tendered_cash_form():
    assert _find_tendered("Cash 20.00\n") == 20.00


def test_tendered_paid_form():
    assert _find_tendered("Paid 20.00\n") == 20.00


def test_tendered_payment_form():
    assert _find_tendered("Payment 20.00\n") == 20.00


def test_tendered_amount_paid_form():
    assert _find_tendered("Amount Paid 20.00\n") == 20.00


def test_tendered_tender_form():
    assert _find_tendered("Tender 20.00\n") == 20.00


def test_tendered_case_insensitive():
    assert _find_tendered("TENDERED 20.00\n") == 20.00


def test_tendered_with_currency_symbol():
    assert _find_tendered("Tendered $20.00\n") == 20.00


def test_tendered_with_dash_separator():
    assert _find_tendered("Tendered - 20.00\n") == 20.00


def test_tendered_with_colon_separator():
    assert _find_tendered("Tendered: 20.00\n") == 20.00


def test_tendered_decimal_comma():
    assert _find_tendered("Tendered 20,00\n") == 20.00


def test_tendered_last_occurrence_wins():
    text = "Cash Tendered: 10.00\nCash Tendered 20.00\n"
    assert _find_tendered(text) == 20.00


def test_tendered_none_when_absent():
    assert _find_tendered("Subtotal 12.00\nTotal 13.00\n") is None


def test_tendered_does_not_match_cashier_line():
    """A cashier line ("Cashier #04") must NOT register as a "Cash 04"
    tendered amount because the underlying _find_amount_after regex
    requires a digit-amount IMMEDIATELY after the keyword (with at
    most ``:`` / ``-`` separators)."""
    assert _find_tendered("Cashier #04\nTotal 5.00\n") is None


def test_tendered_handles_large_amount():
    assert _find_tendered("Tendered 1234.56\n") == 1234.56


# ---- _find_change --------------------------------------------------


def test_change_basic():
    assert _find_change("Change 7.50\n") == 7.50


def test_change_due_form():
    assert _find_change("Change Due 7.50\n") == 7.50


def test_change_given_form():
    assert _find_change("Change Given 7.50\n") == 7.50


def test_change_cash_change_form():
    assert _find_change("Cash Change 7.50\n") == 7.50


def test_change_case_insensitive():
    assert _find_change("CHANGE 7.50\n") == 7.50


def test_change_with_currency_symbol():
    assert _find_change("Change $7.50\n") == 7.50


def test_change_with_dash_separator():
    assert _find_change("Change - 7.50\n") == 7.50


def test_change_with_colon_separator():
    assert _find_change("Change: 7.50\n") == 7.50


def test_change_zero_still_registers():
    """A bare "Change 0.00" line still surfaces -- dashboards want to
    track exact-payment cash receipts too (the 0.00 is meaningful)."""
    assert _find_change("Change 0.00\n") == 0.00


def test_change_decimal_comma():
    assert _find_change("Change 7,50\n") == 7.50


def test_change_last_occurrence_wins():
    text = "Change suggested 5.00\nChange 7.50\n"
    assert _find_change(text) == 7.50


def test_change_none_when_absent():
    assert _find_change("Subtotal 12.00\nTotal 13.00\n") is None


# ---- parse_receipt_text integration --------------------------------


def test_parse_receipt_cash_tender_pair():
    text = (
        "Coffee 5.00\n"
        "Subtotal 5.00\n"
        "Tax 0.50\n"
        "Total 5.50\n"
        "Tendered 20.00\n"
        "Change 14.50\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.tendered == 20.00
    assert parsed.change == 14.50
    assert parsed.total == 5.50


def test_parse_receipt_cash_change_due():
    text = (
        "Subtotal 12.45\n"
        "Total 12.45\n"
        "Cash 20.00\n"
        "Change Due 7.55\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.tendered == 20.00
    assert parsed.change == 7.55


def test_parse_receipt_card_only_no_tender():
    text = (
        "Coffee 5.00\n"
        "Subtotal 5.00\n"
        "Total 5.00\n"
        "Visa ****1234 5.00\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.tendered is None
    assert parsed.change is None


def test_parse_receipt_exact_cash_no_change():
    text = (
        "Subtotal 5.00\n"
        "Total 5.00\n"
        "Cash 5.00\n"
        "Change 0.00\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.tendered == 5.00
    assert parsed.change == 0.00


def test_parse_receipt_with_all_fee_fields():
    text = (
        "Pizza 18.00\n"
        "Subtotal 18.00\n"
        "Service Charge 2.00\n"
        "Delivery Fee 3.99\n"
        "Tax 1.80\n"
        "Tip 4.00\n"
        "Total 29.79\n"
        "Cash 40.00\n"
        "Change 10.21\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.service_charge == 2.00
    assert parsed.delivery_fee == 3.99
    assert parsed.tip == 4.00
    assert parsed.tendered == 40.00
    assert parsed.change == 10.21


# ---- enrich_receipt: LLM-supplied values survive ----------------


def test_enrich_preserves_existing_tendered():
    existing = ReceiptFields(vendor="Cafe", tendered=25.00)
    ocr = OCRResult(text="Tendered 20.00\nChange 0.00\n")
    merged = enrich_receipt(existing, ocr)
    assert merged.tendered == 25.00  # not overwritten


def test_enrich_fills_in_missing_tendered():
    existing = ReceiptFields(vendor="Cafe")
    ocr = OCRResult(text="Tendered 20.00\nChange 0.00\n")
    merged = enrich_receipt(existing, ocr)
    assert merged.tendered == 20.00


def test_enrich_preserves_existing_change():
    existing = ReceiptFields(vendor="Cafe", change=5.00)
    ocr = OCRResult(text="Tendered 20.00\nChange 7.50\n")
    merged = enrich_receipt(existing, ocr)
    assert merged.change == 5.00  # not overwritten


def test_enrich_fills_in_missing_change():
    existing = ReceiptFields(vendor="Cafe")
    ocr = OCRResult(text="Tendered 20.00\nChange 7.50\n")
    merged = enrich_receipt(existing, ocr)
    assert merged.change == 7.50


def test_enrich_both_at_once():
    existing = ReceiptFields(vendor="Cafe")
    ocr = OCRResult(text="Tendered 20.00\nChange 7.50\n")
    merged = enrich_receipt(existing, ocr)
    assert merged.tendered == 20.00
    assert merged.change == 7.50
