"""Tests for the cross-category credit-card / PAN extractor.

Credit-card metadata found in OCR text is stashed under
``ExtractedFields.raw["credit_cards"]`` by the enrich pipeline so
dashboards and routing rules have a single place to look regardless
of which category the screenshot belongs to.

The matcher recognises:

* Full 13..19 digit PANs (with optional space / dash separators
  between groups) that pass the Luhn checksum. The brand is
  identified from the BIN using the public network catalogues
  (Visa / Mastercard / Amex / Discover / JCB / Diners / UnionPay).
* Masked PANs (``****4242``, ``**** **** **** 4242``, ``XXXX-XXXX-
  XXXX-4242``, ``....4242``). When the BIN is hidden, the
  ``bin`` field is ``None`` and the brand is inferred from a
  same-line brand keyword if present.

Output shape: a list of ``{"brand", "bin", "last4"}`` dicts. The
full PAN is deliberately NEVER returned so storage cannot leak the
card secret.

Common test PANs used in this suite (all Luhn-valid):

* 4242424242424242 -- Stripe's canonical Visa test card.
* 5555555555554444 -- Stripe's canonical Mastercard test card.
* 378282246310005  -- Stripe's canonical Amex test card.
* 6011111111111117 -- Stripe's canonical Discover test card.
* 3530111333300000 -- Stripe's canonical JCB test card.
* 30569309025904   -- Stripe's canonical Diners test card.
* 6200000000000005 -- common UnionPay test card.
"""
from __future__ import annotations

import pytest
from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_credit_cards

# ---- full PAN: brand detection -----------------------------------------


def test_visa_basic():
    out = extract_credit_cards("card 4242424242424242 charged")
    assert out == [{"brand": "visa", "bin": "424242", "last4": "4242"}]


def test_visa_13_digit():
    """The legacy 13-digit Visa form is still accepted."""
    # 4222222222222 is a known Luhn-valid 13-digit Visa test PAN.
    out = extract_credit_cards("legacy 4222222222222 here")
    assert out == [{"brand": "visa", "bin": "422222", "last4": "2222"}]


def test_visa_with_spaces():
    out = extract_credit_cards("4242 4242 4242 4242")
    assert out == [{"brand": "visa", "bin": "424242", "last4": "4242"}]


def test_visa_with_dashes():
    out = extract_credit_cards("4242-4242-4242-4242")
    assert out == [{"brand": "visa", "bin": "424242", "last4": "4242"}]


def test_mastercard_basic():
    out = extract_credit_cards("mc 5555555555554444 here")
    assert out == [{"brand": "mastercard", "bin": "555555", "last4": "4444"}]


def test_mastercard_2series_range():
    """The 2221..2720 expansion range tags as Mastercard."""
    # 2221000000000009 -- Luhn-valid example in the expansion range.
    out = extract_credit_cards("expansion 2221000000000009")
    assert out == [{"brand": "mastercard", "bin": "222100", "last4": "0009"}]


def test_amex_basic():
    out = extract_credit_cards("amex 378282246310005 used")
    assert out == [{"brand": "amex", "bin": "378282", "last4": "0005"}]


def test_amex_15_digit():
    out = extract_credit_cards("paid 371449635398431 today")
    assert out == [{"brand": "amex", "bin": "371449", "last4": "8431"}]


def test_discover_basic():
    out = extract_credit_cards("disc 6011111111111117 yo")
    assert out == [{"brand": "discover", "bin": "601111", "last4": "1117"}]


def test_jcb_basic():
    out = extract_credit_cards("jcb 3530111333300000 used")
    assert out == [{"brand": "jcb", "bin": "353011", "last4": "0000"}]


def test_diners_basic():
    """30569309025904 is the canonical Diners test PAN."""
    out = extract_credit_cards("diners 30569309025904 paid")
    assert out == [{"brand": "diners", "bin": "305693", "last4": "5904"}]


def test_unionpay_basic():
    out = extract_credit_cards("up 6200000000000005 used")
    assert out == [{"brand": "unionpay", "bin": "620000", "last4": "0005"}]


# ---- full PAN: Luhn rejection ------------------------------------------


def test_rejects_failing_luhn():
    """A 16-digit run that fails Luhn is not a PAN."""
    # 4242424242424243 fails Luhn (last digit off by one).
    assert extract_credit_cards("not a card 4242424242424243") == []


def test_rejects_all_zeros():
    """Sixteen zeros fail Luhn -- never a real PAN."""
    assert extract_credit_cards("placeholder 0000000000000000") == []


def test_rejects_too_short():
    """12 digits is shorter than every PAN spec."""
    assert extract_credit_cards("not card 123456789012") == []


def test_rejects_too_long():
    """20 digits exceeds the PAN max."""
    assert extract_credit_cards("not card 12345678901234567890") == []


# ---- full PAN: unknown brand ------------------------------------------


def test_known_pan_unknown_brand():
    """A valid Luhn 16-digit PAN with a BIN outside every catalogued
    range surfaces with brand=None but real BIN+last4."""
    # 7000000000000005 -- Luhn-valid 16-digit, 7-prefix is not in any
    # documented brand range.
    out = extract_credit_cards("unknown 7000000000000005 used")
    assert out == [{"brand": None, "bin": "700000", "last4": "0005"}]


# ---- masked PANs -------------------------------------------------------


def test_masked_basic_asterisks():
    out = extract_credit_cards("ending ****4242 today")
    assert out == [{"brand": None, "bin": None, "last4": "4242"}]


def test_masked_full_groups():
    out = extract_credit_cards("on file **** **** **** 4242")
    assert out == [{"brand": None, "bin": None, "last4": "4242"}]


def test_masked_xs():
    out = extract_credit_cards("XXXX-XXXX-XXXX-4242 expired")
    assert out == [{"brand": None, "bin": None, "last4": "4242"}]


def test_masked_lowercase_xs():
    out = extract_credit_cards("xxxx-xxxx-xxxx-4242")
    assert out == [{"brand": None, "bin": None, "last4": "4242"}]


def test_masked_dots():
    out = extract_credit_cards("ending ....4242")
    assert out == [{"brand": None, "bin": None, "last4": "4242"}]


def test_masked_with_brand_keyword_visa():
    out = extract_credit_cards("Visa ending in 4242")
    # The literal "in 4242" doesn't match the masked-pan regex
    # (no mask chars). The matcher requires explicit mask chars.
    # This text yields no card.
    assert out == []


def test_masked_with_brand_keyword_explicit_mask():
    out = extract_credit_cards("Visa **** 4242 charged")
    assert out == [{"brand": "visa", "bin": None, "last4": "4242"}]


def test_masked_with_brand_keyword_amex():
    out = extract_credit_cards("Amex ****1005")
    assert out == [{"brand": "amex", "bin": None, "last4": "1005"}]


def test_masked_with_brand_keyword_american_express():
    out = extract_credit_cards("American Express ****1005")
    assert out == [{"brand": "amex", "bin": None, "last4": "1005"}]


def test_masked_with_brand_keyword_master_card_two_word():
    out = extract_credit_cards("Master Card ****4444")
    assert out == [{"brand": "mastercard", "bin": None, "last4": "4444"}]


def test_masked_with_brand_keyword_mc_short():
    out = extract_credit_cards("MC ****4444")
    assert out == [{"brand": "mastercard", "bin": None, "last4": "4444"}]


def test_masked_brand_only_pinned_when_word_boundary():
    """``masterclass`` doesn't pin the brand to ``mastercard``."""
    out = extract_credit_cards("masterclass ****4444 promo")
    assert out == [{"brand": None, "bin": None, "last4": "4444"}]


def test_masked_brand_keyword_on_different_line_not_pinned():
    """Brand keyword must be on the same line as the masked PAN."""
    text = "Visa\nseparate line ****4242"
    out = extract_credit_cards(text)
    assert out == [{"brand": None, "bin": None, "last4": "4242"}]


# ---- multiple PANs / de-dup --------------------------------------------


def test_multiple_distinct_full_pans():
    text = "card1 4242424242424242 card2 5555555555554444"
    out = extract_credit_cards(text)
    assert out == [
        {"brand": "visa", "bin": "424242", "last4": "4242"},
        {"brand": "mastercard", "bin": "555555", "last4": "4444"},
    ]


def test_dedup_same_pan_twice():
    text = "first 4242424242424242 again 4242424242424242"
    out = extract_credit_cards(text)
    assert out == [{"brand": "visa", "bin": "424242", "last4": "4242"}]


def test_full_pan_and_masked_with_same_last4_distinct():
    """A full PAN and a masked-only entry with same last4 stay
    distinct because the BIN differs (None vs real)."""
    text = "full 4242424242424242 mask ****4242"
    out = extract_credit_cards(text)
    # Full PAN consumes its span; the masked matcher then sees a
    # plain ****4242 with no preceding full PAN to conflict.
    assert len(out) == 2
    assert {"brand": "visa", "bin": "424242", "last4": "4242"} in out
    assert {"brand": None, "bin": None, "last4": "4242"} in out


def test_dedup_masked_same_last4_no_brand():
    text = "first ****4242 again ****4242"
    out = extract_credit_cards(text)
    assert out == [{"brand": None, "bin": None, "last4": "4242"}]


# ---- order preservation -----------------------------------------------


def test_order_preserved_full_pans():
    text = "ny 4242424242424242 then la 5555555555554444"
    out = extract_credit_cards(text)
    assert out[0]["brand"] == "visa"
    assert out[1]["brand"] == "mastercard"


# ---- cap ---------------------------------------------------------------


def test_cap_at_50():
    """Output capped at 50 entries."""
    # Generate distinct masked PANs.
    pieces = [f"x ****{i:04d}" for i in range(60)]
    out = extract_credit_cards(" ".join(pieces))
    assert len(out) == 50
    assert out[0]["last4"] == "0000"


# ---- degenerate inputs -------------------------------------------------


def test_empty_string():
    assert extract_credit_cards("") == []


def test_none_input():
    assert extract_credit_cards(None) == []  # type: ignore[arg-type]


def test_no_cards_in_text():
    assert extract_credit_cards("no card numbers here at all") == []


def test_just_digits_no_pan():
    """A short digit run is not a PAN."""
    assert extract_credit_cards("12345") == []


def test_phone_number_not_a_pan():
    """A 10-digit phone fails Luhn enough of the time and is too short
    anyway. ``(415) 555-1234`` -> 4155551234 (10 digits, below 13)."""
    assert extract_credit_cards("phone (415) 555-1234") == []


# ---- security guarantee: full PAN never returned -----------------------


def test_full_pan_never_in_output():
    """A full PAN appears only as BIN+last4 -- never as a full string."""
    out = extract_credit_cards("paid 4242424242424242")
    assert all("4242424242424242" not in str(v) for entry in out for v in entry.values())


def test_full_pan_never_in_output_amex_15():
    """Amex 15-digit form also only surfaces as BIN+last4."""
    out = extract_credit_cards("amex 378282246310005")
    assert all("378282246310005" not in str(v) for entry in out for v in entry.values())


# ---- enrich pipeline integration --------------------------------------


@pytest.mark.parametrize(
    "category",
    [
        Category.receipt,
        Category.error_stacktrace,
        Category.code_snippet,
        Category.chat_screenshot,
        Category.document,
        Category.other,
    ],
)
def test_pipeline_stashes_credit_cards_for_every_category(category):
    text = "paid 4242424242424242 today"
    ocr = OCRResult(text=text, confidence=0.95)
    out = enrich(category, ExtractedFields(), ocr)
    assert out.raw.get("credit_cards") == [
        {"brand": "visa", "bin": "424242", "last4": "4242"}
    ]


def test_pipeline_no_cards_no_key():
    text = "no card numbers at all"
    ocr = OCRResult(text=text, confidence=0.95)
    out = enrich(Category.other, ExtractedFields(), ocr)
    assert "credit_cards" not in (out.raw or {})


def test_pipeline_masked_with_brand_keyword():
    text = "Visa **** 4242"
    ocr = OCRResult(text=text, confidence=0.95)
    out = enrich(Category.receipt, ExtractedFields(), ocr)
    assert out.raw.get("credit_cards") == [
        {"brand": "visa", "bin": None, "last4": "4242"}
    ]


def test_pipeline_preserves_other_raw_keys():
    text = "see https://example.com paid 4242424242424242"
    ocr = OCRResult(text=text, confidence=0.95)
    out = enrich(Category.other, ExtractedFields(), ocr)
    assert out.raw.get("credit_cards") == [
        {"brand": "visa", "bin": "424242", "last4": "4242"}
    ]
    assert out.raw.get("urls") == ["https://example.com"]
