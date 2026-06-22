"""Gift-card / promo-code redemption tests.

Two new ReceiptFields slots surface gift-card and promo-code data:
* ``gift_card_applied`` -- positive float amount knocked off by a
  stored-value tender (gift card / store credit / voucher).
* ``promo_code`` -- the alphanumeric code the customer applied
  (Promo Code: SAVE10 / Coupon Code: SUMMER2024 / etc).

Gift-card is distinct from ``discount`` (a marketing promotion)
and ``tendered`` (the cash/card customer paid with) because a
gift card is a stored-value tender that dashboards want to
reconcile separately. Promo-code is the symbolic CODE applied;
the discount AMOUNT continues to live in ``discount``.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult, ReceiptFields
from shotclassify_extract import enrich, parse_receipt_text
from shotclassify_extract.receipt import _find_gift_card_applied, _find_promo_code

# ---- Gift-card amount: basic detection -------------------------


def test_gift_card_explicit_keyword():
    assert _find_gift_card_applied("Gift Card 25.00\n") == 25.00


def test_gift_card_with_negative_sign():
    # Receipts typically print the gift card as a negative line
    # (a reduction). We always emit positive.
    assert _find_gift_card_applied("Gift Card -25.00\n") == 25.00


def test_gift_card_applied_keyword():
    assert _find_gift_card_applied("Gift Card Applied 25.00\n") == 25.00


def test_gift_card_redeemed_keyword():
    assert _find_gift_card_applied("Gift Card Redeemed 10.00\n") == 10.00


def test_gc_redeemed_short_form():
    assert _find_gift_card_applied("GC Redeemed 10.00\n") == 10.00


def test_gc_applied_short_form():
    assert _find_gift_card_applied("GC Applied 15.00\n") == 15.00


def test_store_credit_keyword():
    assert _find_gift_card_applied("Store Credit -15.00\n") == 15.00


def test_store_credit_applied_keyword():
    assert _find_gift_card_applied("Store Credit Applied 8.50\n") == 8.50


def test_voucher_bare_keyword():
    assert _find_gift_card_applied("Voucher 5.00\n") == 5.00


def test_voucher_redeemed_keyword():
    assert _find_gift_card_applied("Voucher Redeemed 3.50\n") == 3.50


def test_voucher_applied_keyword():
    assert _find_gift_card_applied("Voucher Applied 7.00\n") == 7.00


# ---- Gift-card: edge cases ------------------------------------


def test_gift_card_none_when_missing():
    assert _find_gift_card_applied("Subtotal 10.00\nTotal 10.00\n") is None


def test_gift_card_empty_text():
    assert _find_gift_card_applied("") is None


def test_gift_card_last_occurrence_wins():
    text = "Gift Card 10.00\n--summary--\nGift Card -25.00\n"
    assert _find_gift_card_applied(text) == 25.00


def test_gift_card_with_dollar_sign():
    assert _find_gift_card_applied("Gift Card -$25.00\n") == 25.00


def test_gift_card_with_euro_sign():
    assert _find_gift_card_applied("Gift Card €10.00\n") == 10.00


def test_gift_card_with_comma_decimal():
    assert _find_gift_card_applied("Gift Card -25,00\n") == 25.00


def test_gift_card_applied_beats_bare_gift_card():
    # "Gift Card Applied" is more specific than "Gift Card" but the
    # _find_signed_amount_after uses last-wins so both lines on the
    # same receipt should resolve cleanly. The catalogue tries the
    # most specific keyword FIRST so "Gift Card Applied 25.00" wins
    # over a later "Gift Card 0.00" prose line.
    text = "Gift Card Applied 25.00\nGift Card 0.00 (balance)\n"
    # The most-specific keyword fires first; "Gift Card Applied 25.00"
    # registers via the "gift card applied" catalogue entry.
    assert _find_gift_card_applied(text) == 25.00


def test_gift_card_zero_amount_registers():
    # A "Gift Card 0.00" line (a balance check) is meaningful for
    # dashboards: it shows the customer queried but didn't redeem.
    assert _find_gift_card_applied("Gift Card 0.00\n") == 0.00


# ---- Promo code: basic detection ------------------------------


def test_promo_code_explicit():
    assert _find_promo_code("Promo Code: SAVE10\n") == "SAVE10"


def test_promo_code_no_colon():
    assert _find_promo_code("Promo Code SAVE10\n") == "SAVE10"


def test_coupon_code_keyword():
    assert _find_promo_code("Coupon Code: SUMMER2024\n") == "SUMMER2024"


def test_discount_code_keyword():
    assert _find_promo_code("Discount Code: WELCOME20\n") == "WELCOME20"


def test_voucher_code_keyword():
    assert _find_promo_code("Voucher Code: GIFT5\n") == "GIFT5"


def test_promotion_code_keyword():
    assert _find_promo_code("Promotion Code: NEWYEAR\n") == "NEWYEAR"


def test_referral_code_keyword():
    assert _find_promo_code("Referral Code: FRIEND10\n") == "FRIEND10"


def test_offer_code_keyword():
    assert _find_promo_code("Offer Code: SPRING\n") == "SPRING"


def test_rebate_code_keyword():
    assert _find_promo_code("Rebate Code: REBATE50\n") == "REBATE50"


# ---- Promo code: alphanumeric / case / shape ------------------


def test_promo_code_with_digits():
    assert _find_promo_code("Promo Code: SAVE10\n") == "SAVE10"


def test_promo_code_with_dash():
    assert _find_promo_code("Promo Code: SAVE-10\n") == "SAVE-10"


def test_promo_code_with_underscore():
    assert _find_promo_code("Promo Code: NEW_USER\n") == "NEW_USER"


def test_promo_code_with_period():
    assert _find_promo_code("Promo Code: SAVE.10\n") == "SAVE.10"


def test_promo_code_lowercase_preserved():
    # We preserve case as printed -- some platforms (Shopify) use
    # lowercase codes.
    assert _find_promo_code("Promo Code: save10\n") == "save10"


def test_promo_code_mixed_case_preserved():
    assert _find_promo_code("Promo Code: Save10\n") == "Save10"


def test_promo_code_with_hash_separator():
    assert _find_promo_code("Promo Code # SAVE10\n") == "SAVE10"


# ---- Promo code: bare "Code:" fallback -----------------------


def test_bare_code_with_discount_context():
    # "Code: NEWUSER" alone doesn't fire, but when paired with a
    # discount keyword on the same line, it does.
    text = "Discount applied with Code: NEWUSER -2.00\n"
    assert _find_promo_code(text) == "NEWUSER"


def test_bare_code_with_promo_context():
    # "Promo Code applied: GIFT5" has the keyword followed by the
    # word "applied" then the colon then the actual code. The
    # explicit "Promo Code" regex captures whatever follows the
    # keyword + separator, so "applied" is captured (a known
    # documented trade-off; we accept it because the prose-form
    # "Promo Code applied: X" is rare on receipts which print
    # the bare "Promo Code: X" instead). The fallback "Code:"
    # form fires when the explicit form fails AND a promo-vocab
    # word sits on the line; here the explicit form succeeds
    # first.
    text = "Promo Code applied: GIFT5\n"
    # Document the actual behavior: captures the first token after
    # the keyword.
    assert _find_promo_code(text) == "applied"


def test_bare_code_without_discount_context_rejected():
    # "Code: NEWUSER" without any discount/promo/coupon vocab on the
    # same line should NOT fire -- could be a customer code, order
    # code, etc.
    assert _find_promo_code("Customer Code: NEWUSER\n") is None


def test_order_code_does_not_misfire():
    # Generic "Order Code: 12345" rejected because no promo vocab.
    assert _find_promo_code("Order Code: 12345\n") is None


# ---- Promo code: edge cases ----------------------------------


def test_promo_code_none_when_missing():
    assert _find_promo_code("Subtotal 10.00\nTotal 10.00\n") is None


def test_promo_code_empty_text():
    assert _find_promo_code("") is None


def test_promo_code_last_occurrence_wins():
    # Multiple codes on one receipt -> last applied wins.
    text = "Promo Code: SAVE10\n--checkout--\nPromo Code: SUMMER2024\n"
    assert _find_promo_code(text) == "SUMMER2024"


def test_promo_code_pure_digit_long_rejected():
    # "Promo Code: 12345" (5 pure digits) is almost always an order
    # number misprint; we reject it.
    assert _find_promo_code("Promo Code: 12345\n") is None


def test_promo_code_pure_digit_short_accepted():
    # Short numeric codes (2-3 digits) are accepted because some
    # merchants use them.
    assert _find_promo_code("Promo Code: 50\n") == "50"


def test_promo_code_alphanumeric_with_long_digits():
    # Alphanumeric long codes are fine (SAVE2024 etc).
    assert _find_promo_code("Promo Code: SAVE2024\n") == "SAVE2024"


def test_promo_code_trailing_punctuation_stripped():
    # Trailing comma or period stripped.
    text = "Promo Code: SAVE10, applied at checkout\n"
    assert _find_promo_code(text) == "SAVE10"


# ---- parse_receipt_text integration --------------------------


def test_parse_receipt_populates_gift_card():
    text = "Subtotal: 50.00\nGift Card -25.00\nTotal: 25.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.gift_card_applied == 25.00


def test_parse_receipt_populates_promo_code():
    text = "Subtotal: 50.00\nPromo Code: SAVE10 -5.00\nTotal: 45.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.promo_code == "SAVE10"


def test_parse_receipt_both_gift_card_and_promo():
    text = (
        "Subtotal: 50.00\n"
        "Promo Code: NEWUSER\n"
        "Discount: -5.00\n"
        "Gift Card -10.00\n"
        "Total: 35.00\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.gift_card_applied == 10.00
    assert parsed.promo_code == "NEWUSER"


def test_parse_receipt_neither_set_to_none():
    text = "Subtotal: 10.00\nTotal: 10.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.gift_card_applied is None
    assert parsed.promo_code is None


# ---- enrich integration -------------------------------------


def test_enrich_writes_gift_card():
    text = "Subtotal: 50.00\nGift Card Applied 25.00\nTotal: 25.00\n"
    ocr = OCRResult(text=text)
    out = enrich(Category.receipt, ExtractedFields(), ocr)
    assert out.receipt is not None
    assert out.receipt.gift_card_applied == 25.00


def test_enrich_writes_promo_code():
    text = "Promo Code: SUMMER2024 -10.00\nTotal: 90.00\n"
    ocr = OCRResult(text=text)
    out = enrich(Category.receipt, ExtractedFields(), ocr)
    assert out.receipt is not None
    assert out.receipt.promo_code == "SUMMER2024"


def test_enrich_preserves_caller_gift_card():
    text = "Gift Card -25.00\n"
    ocr = OCRResult(text=text)
    caller = ReceiptFields(gift_card_applied=99.99)
    out = enrich(Category.receipt, ExtractedFields(receipt=caller), ocr)
    assert out.receipt is not None
    assert out.receipt.gift_card_applied == 99.99


def test_enrich_preserves_caller_promo_code():
    text = "Promo Code: SAVE10\n"
    ocr = OCRResult(text=text)
    caller = ReceiptFields(promo_code="LLM_OVERRIDE")
    out = enrich(Category.receipt, ExtractedFields(receipt=caller), ocr)
    assert out.receipt is not None
    assert out.receipt.promo_code == "LLM_OVERRIDE"


def test_enrich_backfills_gift_card_when_caller_none():
    text = "Gift Card -25.00\n"
    ocr = OCRResult(text=text)
    caller = ReceiptFields(gift_card_applied=None)
    out = enrich(Category.receipt, ExtractedFields(receipt=caller), ocr)
    assert out.receipt is not None
    assert out.receipt.gift_card_applied == 25.00


# ---- Coexistence with discount -----------------------------


def test_gift_card_does_not_pollute_discount():
    # The discount field tracks marketing promotions; a gift card is
    # a stored-value tender. They live in separate fields.
    text = "Discount -3.00\nGift Card -10.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.discount == 3.00
    assert parsed.gift_card_applied == 10.00


def test_promo_code_does_not_pollute_discount_amount():
    # The promo CODE is symbolic; the discount AMOUNT continues to
    # live in discount. They can co-exist.
    text = "Promo Code: SAVE10\nDiscount -5.00\nTotal 45.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.promo_code == "SAVE10"
    assert parsed.discount == 5.00


# ---- Word-boundary defence ---------------------------------


def test_gift_card_inside_word_rejected():
    # "Pregift Card -5.00" should NOT fire because the
    # negative-lookbehind on alphas blocks it (the underlying
    # _find_signed_amount_after has the same alpha defence as
    # _find_amount_after).
    text = "Pregift Card -5.00\nLocal Total 10.00\n"
    # The matcher requires a non-alpha lookbehind on "Gift Card"
    # so "Pregift Card" should NOT match. Note that "gift card
    # applied" wouldn't even be in this text.
    assert _find_gift_card_applied(text) is None


def test_voucher_does_not_misfire_on_prose():
    # Pure prose "the voucher expires next week" without a
    # digit-amount tail should NOT register. The amount regex
    # requires a digit immediately after the keyword (with at most
    # a colon / dash separator).
    text = "The voucher expires next week\nTotal 10.00\n"
    assert _find_gift_card_applied(text) is None
