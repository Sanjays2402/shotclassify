"""Receipt payment-method detection.

ReceiptFields.payment_method is a small canonical enum so dashboards
and routing rules can match on a known string instead of every
printer's wording. This module covers the catalog: visa, mastercard,
amex, discover, apple_pay, google_pay, debit, credit, cash, and
None when nothing is recognised.
"""
from __future__ import annotations

import pytest
from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract.receipt import enrich_receipt, parse_receipt_text


def _ocr(text: str) -> OCRResult:
    return OCRResult(text=text, language="eng", word_count=len(text.split()))


@pytest.mark.parametrize(
    "snippet,expected",
    [
        ("VISA ****1234", "visa"),
        ("Visa Debit ****0001", "visa"),  # visa wins over debit (more specific)
        ("Master Card ****1111", "mastercard"),
        ("MASTERCARD ****1111", "mastercard"),
        ("M/C ****1111", "mastercard"),
        ("American Express ****1001", "amex"),
        ("AMEX ****1001", "amex"),
        ("Discover ****2222", "discover"),
        ("Apple Pay (Visa)", "apple_pay"),
        ("APPLEPAY", "apple_pay"),
        ("Google Pay", "google_pay"),
        ("Debit Card", "debit"),
        ("CREDIT CARD", "credit"),
        ("CASH", "cash"),
    ],
)
def test_payment_method_canonicalised(snippet, expected):
    text = f"Vendor\nSubtotal 10.00\nTotal 10.00\n{snippet}\n"
    parsed = parse_receipt_text(text)
    assert parsed.payment_method == expected


def test_payment_method_none_when_absent():
    text = "Grocery\nMilk 2.00\nSubtotal 2.00\nTotal 2.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.payment_method is None


def test_apple_pay_wins_over_visa_when_both_present():
    """Apple Pay over a Visa card should be tagged as apple_pay (the
    pattern is checked first because the customer experience is
    contactless, even if the underlying network is Visa)."""
    text = (
        "Cafe\nSubtotal 5.00\nTotal 5.00\n"
        "Apple Pay (Visa ****0001)\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.payment_method == "apple_pay"


def test_amex_pattern_wins_over_bare_credit():
    """A receipt that says 'Credit Card AMEX 1001' should land on amex,
    not the generic 'credit', because amex is checked first."""
    text = (
        "Diner\nSubtotal 18.00\nTotal 18.00\n"
        "Credit Card AMEX 1001\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.payment_method == "amex"


def test_enrich_preserves_existing_payment_method():
    """An LLM-supplied payment_method survives enrichment."""
    text = "Diner\nSubtotal 20.00\nTotal 20.00\nVISA ****0001\n"
    existing = ReceiptFields(vendor="Diner", payment_method="amex")
    merged = enrich_receipt(existing, _ocr(text))
    assert merged.payment_method == "amex"  # not overwritten


def test_enrich_fills_in_missing_payment_method():
    text = "Diner\nSubtotal 20.00\nTotal 20.00\nMastercard ****1234\n"
    existing = ReceiptFields(vendor="Diner")
    merged = enrich_receipt(existing, _ocr(text))
    assert merged.payment_method == "mastercard"


def test_word_boundary_avoids_false_positives():
    """The bare 'cash' pattern must not fire on 'cashback' or
    'cashier'."""
    text = "Store\nCashback eligible\nCashier: Bob\nSubtotal 1.00\nTotal 1.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.payment_method is None
