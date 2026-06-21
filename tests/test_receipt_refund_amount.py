"""Receipt refund / void / cancelled-transaction detection.

A new ``ReceiptFields.refund_amount`` populates whenever the receipt
represents a returned / voided / cancelled transaction. Stored as a
positive float (the amount being refunded) regardless of whether
the printer wrote the value bare with a refund keyword or with an
explicit leading ``-`` sign.

Recognised keyword vocabularies (case-insensitive):

* ``Refund`` / ``Refund Amount`` / ``Refund Total``
* ``Void`` / ``Void Sale`` / ``Void Transaction``
* ``Cancelled`` / ``Cancelled Transaction`` / ``Cancellation``
* ``Return`` / ``Return Amount`` / ``Return Total``
* ``Reversal``

Fallback (no keyword): a top-level ``Total -12.50`` / ``Subtotal
-12.50`` with an explicit leading minus sign is also tagged as a
refund. Per-line negative amounts are NOT tagged here (those are
discount lines handled by the existing per-item parser).

The LLM wire format in ``classify/client.py`` accepts the same
``refund_amount`` field when the vision model populates it directly.
"""
from __future__ import annotations

import pytest
from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract.receipt import enrich_receipt, parse_receipt_text


def _ocr(text: str) -> OCRResult:
    return OCRResult(text=text, language="eng", word_count=len(text.split()))


# ---- bare refund keywords ----------------------------------------------


@pytest.mark.parametrize(
    "line,expected",
    [
        ("REFUND 12.50", 12.50),
        ("Refund 12.50", 12.50),
        ("Refund Amount 12.50", 12.50),
        ("Refund Amount: 12.50", 12.50),
        ("Refund Total 12.50", 12.50),
        ("REFUND: 12.50", 12.50),
        ("REFUND = 12.50", 12.50),
    ],
)
def test_refund_keyword_amount(line, expected):
    text = f"ACME Cafe\nLatte 5.00\n{line}\n"
    parsed = parse_receipt_text(text)
    assert parsed.refund_amount == expected


@pytest.mark.parametrize(
    "line,expected",
    [
        ("VOID 12.50", 12.50),
        ("Void 12.50", 12.50),
        ("Void Sale 12.50", 12.50),
        ("Void Transaction 12.50", 12.50),
        ("VOID: 12.50", 12.50),
    ],
)
def test_void_keyword_amount(line, expected):
    text = f"ACME Cafe\nItem 10.00\n{line}\n"
    parsed = parse_receipt_text(text)
    assert parsed.refund_amount == expected


@pytest.mark.parametrize(
    "line,expected",
    [
        ("CANCELLED 12.50", 12.50),
        ("Cancelled 12.50", 12.50),
        ("Cancelled Transaction 12.50", 12.50),
        ("Cancellation 12.50", 12.50),
    ],
)
def test_cancelled_keyword_amount(line, expected):
    text = f"ACME Cafe\nItem 10.00\n{line}\n"
    parsed = parse_receipt_text(text)
    assert parsed.refund_amount == expected


@pytest.mark.parametrize(
    "line,expected",
    [
        ("Return 12.50", 12.50),
        ("RETURN 12.50", 12.50),
        ("Return Amount 12.50", 12.50),
        ("Return Total 12.50", 12.50),
        ("RETURN: 12.50", 12.50),
    ],
)
def test_return_keyword_amount(line, expected):
    text = f"ACME Cafe\nItem 10.00\n{line}\n"
    parsed = parse_receipt_text(text)
    assert parsed.refund_amount == expected


def test_reversal_keyword_amount():
    text = "ACME Cafe\nItem 10.00\nReversal 10.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.refund_amount == 10.00


# ---- signed forms ------------------------------------------------------


def test_signed_refund_strips_minus():
    """``REFUND: -12.50`` should normalise to 12.50 (positive)."""
    text = "ACME\nREFUND: -12.50\n"
    parsed = parse_receipt_text(text)
    assert parsed.refund_amount == 12.50


def test_signed_void_strips_minus():
    text = "ACME\nVOID: -25.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.refund_amount == 25.00


def test_signed_with_dollar_sign():
    text = "ACME\nREFUND -$12.50\n"
    parsed = parse_receipt_text(text)
    assert parsed.refund_amount == 12.50


# ---- negative-total fallback (no keyword) ------------------------------


def test_negative_total_implies_refund():
    """``Total -12.50`` with no keyword still tags as refund."""
    text = "ACME Cafe\nItem 10.00\nTotal -12.50\n"
    parsed = parse_receipt_text(text)
    assert parsed.refund_amount == 12.50


def test_negative_subtotal_implies_refund():
    text = "ACME Cafe\nItem 10.00\nSubtotal -12.50\nTotal -12.50\n"
    parsed = parse_receipt_text(text)
    assert parsed.refund_amount == 12.50


def test_negative_total_with_dollar_sign():
    text = "ACME Cafe\nTotal: -$12.50\n"
    parsed = parse_receipt_text(text)
    assert parsed.refund_amount == 12.50


def test_positive_total_is_not_refund():
    """A normal positive sale does not populate refund_amount."""
    text = "ACME Cafe\nLatte 5.00\nTotal 5.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.refund_amount is None


# ---- rejection / edge cases --------------------------------------------


def test_no_refund_keyword_no_negative_total_returns_none():
    text = (
        "ACME Cafe\nLatte 5.00\nCroissant 3.00\n"
        "Subtotal 8.00\nTax 0.50\nTotal 8.50\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.refund_amount is None


def test_empty_text():
    assert parse_receipt_text("").refund_amount is None


def test_amount_out_of_range_rejected():
    """An OCR garble like ``Refund 999999.99`` (above the cap) is
    rejected as noise. The regex's 1..5 digit cap on the integer
    portion enforces this implicitly."""
    text = "ACME Cafe\nREFUND 9999999.99\n"
    parsed = parse_receipt_text(text)
    assert parsed.refund_amount is None


def test_refund_keyword_last_match_wins():
    """A receipt with a header summary plus the actual refund line
    should resolve to the actual line, not the header."""
    text = (
        "ACME Cafe\n"
        "Refunds Today: 100.00\n"  # header summary
        "...\n"
        "Refund Amount: 12.50\n"  # actual refund line
    )
    parsed = parse_receipt_text(text)
    assert parsed.refund_amount == 12.50


def test_per_line_negative_does_not_set_top_level_refund():
    """A per-item negative on a line (handled by the discount parser)
    must not populate the top-level refund_amount because the
    overall transaction is still a sale."""
    text = (
        "ACME Cafe\n"
        "Latte 5.00\n"
        "BOGO 50% off Croissant 3.00\n"
        "Subtotal 6.50\n"
        "Total 6.50\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.refund_amount is None


def test_word_boundary_protects_against_substring_false_positives():
    """``Pre-tax`` should not match the ``tax`` substring -- and
    similarly, neither ``return`` inside a word like ``Return policy
    statement`` followed by an unrelated price should trigger."""
    text = (
        "ACME Cafe\n"
        "Coffee 5.00\n"
        "Total 5.00\n"
        "Return policy on the back\n"  # no amount after ``Return policy``
    )
    parsed = parse_receipt_text(text)
    # ``Return policy on the back`` has no amount after the keyword
    # so no refund. (If the amount came on the next line it would
    # match -- acceptable since explicit "Return 12.50" IS a refund.)
    assert parsed.refund_amount is None


# ---- enrich_receipt merge behaviour ------------------------------------


def test_enrich_backfills_refund_amount_when_existing_missing():
    """LLM-supplied receipt with no refund_amount; OCR finds one ->
    OCR value should backfill."""
    existing = ReceiptFields(vendor="ACME", total=12.50)
    ocr = _ocr("ACME Cafe\nItem 12.50\nREFUND 12.50\n")
    enriched = enrich_receipt(existing, ocr)
    assert enriched.refund_amount == 12.50
    # Existing vendor preserved.
    assert enriched.vendor == "ACME"


def test_enrich_preserves_llm_supplied_refund_amount():
    """LLM-supplied refund_amount wins; OCR doesn't override."""
    existing = ReceiptFields(vendor="ACME", refund_amount=99.99)
    ocr = _ocr("ACME Cafe\nItem 12.50\nREFUND 12.50\n")
    enriched = enrich_receipt(existing, ocr)
    assert enriched.refund_amount == 99.99


def test_enrich_none_existing_uses_parsed_refund():
    ocr = _ocr("ACME\nREFUND 5.00\n")
    enriched = enrich_receipt(None, ocr)
    assert enriched.refund_amount == 5.00


# ---- LLM wire format ---------------------------------------------------


def test_llm_payload_round_trips_refund_amount():
    """The classify client should accept refund_amount in the receipt
    payload field and store it on the ReceiptFields model."""
    from shotclassify_classify.client import _parse_llm_payload

    payload = {
        "primary": "receipt",
        "confidences": [],
        "rationale": "test",
        "fields": {
            "receipt": {
                "vendor": "ACME",
                "total": 12.50,
                "refund_amount": 12.50,
                "items": [],
            }
        },
    }
    _, fields = _parse_llm_payload(payload)
    assert fields.receipt is not None
    assert fields.receipt.refund_amount == 12.50


def test_llm_payload_omits_refund_amount_when_not_provided():
    from shotclassify_classify.client import _parse_llm_payload

    payload = {
        "primary": "receipt",
        "confidences": [],
        "rationale": "test",
        "fields": {
            "receipt": {
                "vendor": "ACME",
                "total": 12.50,
                "items": [],
            }
        },
    }
    _, fields = _parse_llm_payload(payload)
    assert fields.receipt is not None
    assert fields.receipt.refund_amount is None
