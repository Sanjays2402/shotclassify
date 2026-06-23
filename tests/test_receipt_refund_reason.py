"""Receipt refund-reason extraction tests.

When a POS system prompts the cashier to enter a reason for a
refund / void / return, the receipt prints it as:

  Refund - damaged goods                    (inline form)
  Refund: customer changed mind             (inline form)
  Refund Reason: pricing error              (compound form)
  Void Reason: cashier error                (compound form)
  Return Reason: defective                  (compound form)
  Reason: wrong size                        (bare form, only when
                                             refund_amount is also
                                             populated as anchor)

The new ``ReceiptFields.refund_reason`` slot captures the cleaned
free-form reason string verbatim (case-preserved).
"""
from __future__ import annotations

from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract.receipt import (
    _find_refund_reason,
    enrich_receipt,
    parse_receipt_text,
)

# ---- Compound keyword forms (most specific) ----------------


def test_refund_reason_keyword():
    text = "Refund 12.50\nRefund Reason: damaged goods"
    fields = parse_receipt_text(text)
    assert fields.refund_amount == 12.50
    assert fields.refund_reason == "damaged goods"


def test_void_reason_keyword():
    text = "Void 5.00\nVoid Reason: pricing error"
    fields = parse_receipt_text(text)
    assert fields.refund_amount == 5.00
    assert fields.refund_reason == "pricing error"


def test_return_reason_keyword():
    text = "Return 25.00\nReturn Reason: defective"
    fields = parse_receipt_text(text)
    assert fields.refund_amount == 25.00
    assert fields.refund_reason == "defective"


def test_cancellation_reason_keyword():
    text = "Cancelled 100.00\nCancellation Reason: customer no-show"
    fields = parse_receipt_text(text)
    assert fields.refund_amount == 100.00
    assert fields.refund_reason == "customer no-show"


def test_reversal_reason_keyword():
    text = "Reversal 30.00\nReversal Reason: duplicate charge"
    fields = parse_receipt_text(text)
    assert fields.refund_reason == "duplicate charge"


def test_compound_with_dash_separator():
    text = "Refund 12.50\nRefund Reason - wrong color"
    fields = parse_receipt_text(text)
    assert fields.refund_reason == "wrong color"


def test_compound_with_uppercase():
    text = "Refund 12.50\nREFUND REASON: customer satisfaction"
    fields = parse_receipt_text(text)
    assert fields.refund_reason == "customer satisfaction"


# ---- Bare Reason keyword (only with refund_amount anchor) ---


def test_bare_reason_with_refund_amount_anchor():
    text = "Refund 12.50\nReason: customer changed mind"
    fields = parse_receipt_text(text)
    assert fields.refund_amount == 12.50
    assert fields.refund_reason == "customer changed mind"


def test_bare_reason_without_anchor_rejected():
    # No refund amount -> bare Reason shouldn't fire as refund reason
    text = "Charge: subscription\nReason: monthly renewal\nTotal 9.99"
    fields = parse_receipt_text(text)
    assert fields.refund_amount is None
    assert fields.refund_reason is None


def test_bare_reason_with_negative_total_anchor():
    # Negative total triggers refund_amount detection, which then
    # allows the bare Reason to fire.
    text = "Subtotal: -25.00\nTotal: -25.00\nReason: customer dispute"
    fields = parse_receipt_text(text)
    assert fields.refund_amount == 25.00
    assert fields.refund_reason == "customer dispute"


# ---- Inline ``Refund - reason`` form -----------------------


def test_inline_refund_dash_reason():
    text = "Refund - wrong size"
    reason = _find_refund_reason(text, has_refund_amount=False)
    assert reason == "wrong size"


def test_inline_refund_colon_reason():
    text = "REFUND: damaged in shipping"
    reason = _find_refund_reason(text, has_refund_amount=False)
    assert reason == "damaged in shipping"


def test_inline_void_reason():
    text = "Void: pricing error"
    reason = _find_refund_reason(text, has_refund_amount=False)
    assert reason == "pricing error"


def test_inline_return_reason():
    text = "Return: defective merchandise"
    reason = _find_refund_reason(text, has_refund_amount=False)
    assert reason == "defective merchandise"


def test_inline_with_currency_amount_rejected():
    # Inline form must not steal the refund amount line.
    text = "Refund: $12.50"
    reason = _find_refund_reason(text, has_refund_amount=False)
    assert reason is None


def test_inline_with_bare_number_rejected():
    text = "Refund: 12.50"
    reason = _find_refund_reason(text, has_refund_amount=False)
    assert reason is None


def test_inline_with_negative_amount_rejected():
    text = "Refund: -12.50"
    reason = _find_refund_reason(text, has_refund_amount=False)
    assert reason is None


def test_inline_long_phrase():
    text = "Refund - customer reported item arrived broken in shipping"
    reason = _find_refund_reason(text, has_refund_amount=False)
    assert reason == "customer reported item arrived broken in shipping"


# ---- Priority order -----------------------------------------


def test_compound_beats_bare():
    # When both compound AND bare reasons appear, compound wins.
    text = (
        "Refund 12.50\n"
        "Reason: customer mistake\n"
        "Refund Reason: pricing error"
    )
    fields = parse_receipt_text(text)
    assert fields.refund_reason == "pricing error"


def test_compound_beats_inline():
    text = (
        "Refund - cashier note\n"
        "Refund Reason: official explanation\n"
        "Total 12.50"
    )
    fields = parse_receipt_text(text)
    assert fields.refund_reason == "official explanation"


def test_bare_beats_inline():
    # When refund_amount anchors the bare form, bare beats inline.
    text = (
        "Refund - quick note\n"
        "Reason: detailed customer explanation\n"
        "Total -12.50"
    )
    fields = parse_receipt_text(text)
    assert fields.refund_reason == "detailed customer explanation"


def test_last_compound_wins():
    text = (
        "Refund 12.50\n"
        "Refund Reason: first reason\n"
        "Refund Reason: actual reason"
    )
    fields = parse_receipt_text(text)
    assert fields.refund_reason == "actual reason"


# ---- Cleanup defence ---------------------------------------


def test_trailing_punctuation_stripped():
    text = "Refund 12.50\nRefund Reason: damaged goods."
    fields = parse_receipt_text(text)
    assert fields.refund_reason == "damaged goods"


def test_trailing_semicolon_stripped():
    text = "Refund 12.50\nRefund Reason: damaged goods;"
    fields = parse_receipt_text(text)
    assert fields.refund_reason == "damaged goods"


def test_reason_with_internal_punctuation_preserved():
    # Punctuation inside the reason body must be preserved.
    text = "Refund 12.50\nRefund Reason: damaged, item #3 broken"
    fields = parse_receipt_text(text)
    assert fields.refund_reason == "damaged, item #3 broken"


def test_pure_number_reason_rejected():
    text = "Refund 12.50\nRefund Reason: 42"
    fields = parse_receipt_text(text)
    assert fields.refund_reason is None


def test_pure_currency_reason_rejected():
    text = "Refund 12.50\nRefund Reason: $5"
    fields = parse_receipt_text(text)
    assert fields.refund_reason is None


def test_overly_long_reason_rejected():
    long_text = "a" * 200
    text = f"Refund 12.50\nRefund Reason: {long_text}"
    fields = parse_receipt_text(text)
    assert fields.refund_reason is None


def test_status_word_only_rejected():
    # "Cancelled: transaction" / "Void: sale" shouldn't tag the
    # status word as a reason.
    text = "Void: transaction"
    reason = _find_refund_reason(text, has_refund_amount=False)
    assert reason is None


def test_status_word_sale_rejected():
    text = "Refund: sale"
    reason = _find_refund_reason(text, has_refund_amount=False)
    assert reason is None


# ---- Case preservation -------------------------------------


def test_case_preserved_in_reason_body():
    text = "Refund 12.50\nRefund Reason: Damaged ITEM"
    fields = parse_receipt_text(text)
    assert fields.refund_reason == "Damaged ITEM"


def test_lowercase_reason_preserved():
    text = "Refund 12.50\nRefund Reason: defective on arrival"
    fields = parse_receipt_text(text)
    assert fields.refund_reason == "defective on arrival"


# ---- Normal receipt -- no false-positives -------------------


def test_normal_sale_no_reason():
    text = """Latte 5.00
Muffin 3.00
Subtotal 8.00
Tax 0.50
Total 8.50
Cash Tendered 10.00
Change 1.50"""
    fields = parse_receipt_text(text)
    assert fields.refund_amount is None
    assert fields.refund_reason is None


def test_normal_sale_with_subscription_reason_no_false_positive():
    text = """Service: Annual subscription
Charge: 99.99
Reason: subscription renewal
Total 99.99"""
    fields = parse_receipt_text(text)
    # No refund amount means the bare ``Reason:`` keyword can't anchor
    # as a refund reason.
    assert fields.refund_reason is None


def test_empty_text():
    fields = parse_receipt_text("")
    assert fields.refund_reason is None


# ---- Realistic refund receipt -----------------------------


def test_realistic_refund_receipt():
    text = """ACME STORE #1234
========================
Tx: 9988
Cashier: Bob
Date: 2024-06-22

REFUND TRANSACTION
Original Sale: TX-7766

Original Items Returned:
  Coffee Beans 250g  -15.99
  Filters x100       -8.50

Subtotal:        -24.49
Tax:             -2.45
TOTAL REFUND:    -26.94

Refund Method:   Cash
Refund Reason:   defective product
Authorised by:   Manager #3

Thank you for shopping with us
"""
    fields = parse_receipt_text(text)
    # The refund amount is detected from the keyword line.
    assert fields.refund_amount == 26.94
    assert fields.refund_reason == "defective product"


def test_realistic_void_receipt():
    text = """Quick Stop POS
Register #4

VOID
Original Total: 18.45
Void: 18.45
Void Reason: cashier error
Authorised by: Manager
"""
    fields = parse_receipt_text(text)
    # The void keyword anchors refund_amount and Void Reason
    # populates refund_reason.
    assert fields.refund_amount == 18.45
    assert fields.refund_reason == "cashier error"


# ---- enrich_receipt backfill -------------------------------


def test_enrich_backfills_refund_reason():
    text = "Refund 12.50\nRefund Reason: damaged"
    existing = ReceiptFields()  # caller supplied nothing
    fields = enrich_receipt(existing, OCRResult(text=text))
    assert fields.refund_reason == "damaged"


def test_enrich_preserves_caller_supplied_refund_reason():
    text = "Refund 12.50\nRefund Reason: damaged"
    existing = ReceiptFields(refund_reason="customer story")
    fields = enrich_receipt(existing, OCRResult(text=text))
    # Caller's supplied reason wins (typical for LLM-supplied data).
    assert fields.refund_reason == "customer story"


def test_enrich_with_no_text_yields_none():
    fields = enrich_receipt(None, OCRResult(text="Latte 5.00\nTotal 5.00"))
    assert fields.refund_reason is None


# ---- LLM wire format ---------------------------------------


def test_llm_wire_format_refund_reason():
    from shotclassify_classify.client import _parse_llm_payload
    payload = {
        "primary": "receipt",
        "confidences": [],
        "rationale": "",
        "fields": {
            "receipt": {
                "refund_amount": 12.50,
                "refund_reason": "damaged goods",
            }
        },
    }
    _, fields = _parse_llm_payload(payload)
    assert fields.receipt is not None
    assert fields.receipt.refund_amount == 12.50
    assert fields.receipt.refund_reason == "damaged goods"


# ---- Inline form edge cases --------------------------------


def test_void_with_uppercase():
    text = "VOID - wrong customer"
    reason = _find_refund_reason(text, has_refund_amount=False)
    assert reason == "wrong customer"


def test_voided_with_ed_suffix():
    text = "Voided: cashier mistake"
    reason = _find_refund_reason(text, has_refund_amount=False)
    assert reason == "cashier mistake"


def test_returned_with_ed_suffix():
    text = "Returned: customer didn't like it"
    reason = _find_refund_reason(text, has_refund_amount=False)
    assert reason == "customer didn't like it"


def test_cancellation_inline():
    text = "Cancellation - duplicate booking"
    reason = _find_refund_reason(text, has_refund_amount=False)
    assert reason == "duplicate booking"


def test_cancelled_inline():
    text = "Cancelled: customer no-show"
    reason = _find_refund_reason(text, has_refund_amount=False)
    assert reason == "customer no-show"


# ---- Refund_reason without refund_amount -------------------


def test_refund_reason_compound_without_amount():
    # Compound form fires even without a refund amount because
    # the keyword itself is the anchor.
    text = "Refund Reason: damaged on shelf"
    reason = _find_refund_reason(text, has_refund_amount=False)
    assert reason == "damaged on shelf"


def test_refund_reason_inline_without_amount():
    # Inline form also fires without amount -- the refund keyword
    # itself is enough signal.
    text = "Refund - wrong item delivered"
    reason = _find_refund_reason(text, has_refund_amount=False)
    assert reason == "wrong item delivered"


# ---- Multi-word reasons ------------------------------------


def test_reason_with_multiple_words():
    text = "Refund 12.50\nRefund Reason: customer ordered the wrong size and didn't notice"
    fields = parse_receipt_text(text)
    assert fields.refund_reason == "customer ordered the wrong size and didn't notice"


def test_reason_with_apostrophe():
    text = "Refund 12.50\nRefund Reason: didn't fit"
    fields = parse_receipt_text(text)
    assert fields.refund_reason == "didn't fit"


def test_reason_with_quotation_marks():
    text = "Refund 12.50\nRefund Reason: customer said \"too small\""
    fields = parse_receipt_text(text)
    assert "too small" in (fields.refund_reason or "")


def test_reason_with_numbers():
    text = "Refund 12.50\nRefund Reason: order #1234 mispicked"
    fields = parse_receipt_text(text)
    assert "1234" in (fields.refund_reason or "")
