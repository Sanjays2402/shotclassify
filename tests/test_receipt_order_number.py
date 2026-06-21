"""Receipt order / invoice / reference number extraction.

The new ``ReceiptFields.order_number`` slot carries the order /
invoice / receipt / reference / transaction / confirmation / check
number printed on most receipts. Stored as a string because vendors
mix digits with letters (``ABC-12345``, ``INV-00099``,
``TKT-2024-007``, ``CONF-12-99``).

The matcher loops through a keyword catalogue in priority order:
invoice (long+bare) -> order (long+bare) -> receipt -> check ->
transaction -> reference -> confirmation. First keyword to match
wins. Within a keyword the first occurrence wins (the number is
usually printed once near the top of the receipt). A value must
contain at least one digit so ``Reference: see below`` does not
false-positive.
"""
from __future__ import annotations

from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract import enrich_receipt
from shotclassify_extract.receipt import _find_order_number, parse_receipt_text

# ---- _find_order_number helper ----------------------------------------


def test_invoice_no_with_dashes_and_letters():
    assert _find_order_number("Invoice No: ABC-12345") == "ABC-12345"


def test_invoice_hash_separator():
    """Some printers use ``#:`` between the keyword and value."""
    assert _find_order_number("Invoice #: 99001") == "99001"


def test_invoice_bare_keyword():
    """Bare ``Invoice 99001`` (no ``No``/``#``) still extracts."""
    assert _find_order_number("Invoice 99001 dated today") == "99001"


def test_order_hash_value():
    """``Order #12345`` -> ``12345``; the hash is consumed by the keyword."""
    assert _find_order_number("Order #12345 today") == "12345"


def test_order_number_word():
    assert _find_order_number("Order Number: 12345") == "12345"


def test_order_id_word():
    assert _find_order_number("Order ID 99001") == "99001"


def test_receipt_no_dot():
    """Some printers abbreviate as ``Receipt No.`` (with the period)."""
    assert _find_order_number("Receipt No. ABC-099") == "ABC-099"


def test_reference_with_year_format():
    assert _find_order_number("Reference: TKT-2024-007") == "TKT-2024-007"


def test_ref_short_form():
    assert _find_order_number("Ref # 12345 OK") == "12345"


def test_transaction_id():
    assert _find_order_number("Transaction ID 7788") == "7788"


def test_check_hash_two_digits():
    """US restaurant pattern. 2-digit values must still match."""
    assert _find_order_number("Check #45") == "45"


def test_check_hash_one_digit():
    """Edge: ``Check #1`` (very first order of the day)."""
    assert _find_order_number("Check #1 next") == "1"


def test_confirmation_number():
    assert _find_order_number("Confirmation No: CONF-12-99") == "CONF-12-99"


def test_slash_value_pos_style():
    """Some POS systems print ``2024/07/00099`` style numbers."""
    assert _find_order_number("Invoice No: 2024/07/00099") == "2024/07/00099"


# ---- rejection / boundary cases ---------------------------------------


def test_no_keyword_returns_none():
    assert _find_order_number("Bistro Cafe\n123 Main St") is None


def test_keyword_without_digits_rejected():
    """``Order: foo bar`` has no digits; do not extract."""
    assert _find_order_number("Order: foo bar") is None


def test_empty_string_returns_none():
    assert _find_order_number("") is None
    assert _find_order_number("   \n   ") is None


def test_keyword_priority_invoice_wins_over_order():
    """When both ``Invoice No`` and ``Order #`` appear, the more
    formal invoice keyword wins because it's earlier in the catalogue
    priority list."""
    text = (
        "Bistro Cafe\n"
        "Invoice No: ABC-001\n"
        "Order #99\n"
    )
    assert _find_order_number(text) == "ABC-001"


def test_keyword_priority_order_wins_over_reference():
    """When ``Order Number`` and ``Reference`` both appear, order wins."""
    text = "Order Number: 100\nReference: REF-99\n"
    assert _find_order_number(text) == "100"


def test_substring_not_matched():
    """``ordering`` should not match the ``order`` bare keyword because
    of the (?<![A-Za-z]) lookbehind."""
    assert _find_order_number("ordering options below: choose one") is None


def test_word_at_start_of_line_still_matched():
    """A keyword at the very start of input has no preceding char; the
    lookbehind allows it."""
    assert _find_order_number("Invoice No: ABC-001") == "ABC-001"


# ---- parse_receipt_text integration -----------------------------------


def test_parse_receipt_text_populates_order_number():
    text = (
        "Bistro Cafe\n"
        "Invoice No: ABC-12345\n"
        "Date: 2024-07-01\n"
        "Subtotal: 20.00\n"
        "Total: 21.80\n"
        "VISA ****1234\n"
    )
    out = parse_receipt_text(text)
    assert out.order_number == "ABC-12345"
    # Sanity: other receipt fields still parse correctly.
    assert out.vendor == "Bistro Cafe"
    assert out.subtotal == 20.0
    assert out.payment_method == "visa"


def test_parse_receipt_text_no_order_number():
    text = "Bistro Cafe\nSubtotal: 5.00\nTotal: 5.00\n"
    out = parse_receipt_text(text)
    assert out.order_number is None


def test_enrich_receipt_fills_order_number_when_missing():
    """An LLM-supplied receipt that lacks order_number should get the
    OCR-parsed value backfilled."""
    existing = ReceiptFields(vendor="Bistro Cafe", total=21.80)
    ocr = OCRResult(text="Invoice No: ABC-12345\nTotal: 21.80\n", word_count=4)
    out = enrich_receipt(existing, ocr)
    assert out.order_number == "ABC-12345"
    assert out.vendor == "Bistro Cafe"  # caller value preserved
    assert out.total == 21.80


def test_enrich_receipt_preserves_existing_order_number():
    """When the LLM already supplied order_number, the OCR-parsed
    value must NOT overwrite it."""
    existing = ReceiptFields(order_number="LLM-OVERRIDE")
    ocr = OCRResult(text="Invoice No: ABC-12345\n", word_count=3)
    out = enrich_receipt(existing, ocr)
    assert out.order_number == "LLM-OVERRIDE"


# ---- LLM round-trip via classify client --------------------------------


def test_llm_supplied_order_number_survives_round_trip():
    """The classify client's payload-mapping path must hand
    ``order_number`` through to ReceiptFields."""
    from shotclassify_classify.client import _parse_llm_payload

    payload = {
        "primary": "receipt",
        "confidences": [{"category": "receipt", "score": 0.9}],
        "rationale": "",
        "fields": {
            "receipt": {
                "vendor": "Cafe",
                "order_number": "INV-99",
                "total": 5.0,
                "items": [],
            }
        },
    }
    _, fields = _parse_llm_payload(payload)
    assert fields.receipt is not None
    assert fields.receipt.order_number == "INV-99"
