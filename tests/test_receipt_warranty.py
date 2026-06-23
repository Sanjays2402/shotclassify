"""Receipt warranty / return-period notice extraction tests.

A new ``ReceiptFields.warranty`` slot captures the small-print
return-window or warranty-period notice printed at the footer of
most retail receipts. Output is a dict ``{"kind": str,
"duration_days": int | None, "notice": str}`` or None for
receipts with no warranty notice.

``kind`` is one of ``return`` / ``warranty`` / ``no_returns``.
"""
from __future__ import annotations

from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract.receipt import _find_warranty, enrich_receipt

# ---- Return-window notices ---------------------------------------


def test_returns_within_30_days():
    out = _find_warranty("Returns accepted within 30 days")
    assert out is not None
    assert out["kind"] == "return"
    assert out["duration_days"] == 30


def test_30_day_return_policy():
    out = _find_warranty("30 day return policy")
    assert out is not None
    assert out["kind"] == "return"
    assert out["duration_days"] == 30


def test_hyphenated_30_day_returns():
    out = _find_warranty("30-day returns")
    assert out is not None
    assert out["kind"] == "return"
    assert out["duration_days"] == 30


def test_return_within_14_days():
    out = _find_warranty("Return within 14 days")
    assert out is not None
    assert out["kind"] == "return"
    assert out["duration_days"] == 14


def test_returns_in_60_days():
    out = _find_warranty("Returns in 60 days")
    assert out is not None
    assert out["kind"] == "return"
    assert out["duration_days"] == 60


def test_returnable_within_2_weeks():
    out = _find_warranty("Returnable within 2 weeks")
    assert out is not None
    assert out["kind"] == "return"
    assert out["duration_days"] == 14


def test_exchangeable_within_30_days():
    out = _find_warranty("Exchangeable within 30 days")
    assert out is not None
    assert out["kind"] == "return"
    assert out["duration_days"] == 30


def test_return_window_phrase():
    out = _find_warranty("30 day return window")
    assert out is not None
    assert out["kind"] == "return"
    assert out["duration_days"] == 30


def test_return_period_phrase():
    out = _find_warranty("90 day return period")
    assert out is not None
    assert out["kind"] == "return"
    assert out["duration_days"] == 90


def test_return_by_date_form():
    out = _find_warranty("Return by 04/15/2024")
    assert out is not None
    assert out["kind"] == "return"
    # Date form does not carry a numeric duration.
    assert out["duration_days"] is None
    assert "04/15/2024" in out["notice"]


def test_return_before_date_form():
    out = _find_warranty("Return before April 15")
    assert out is not None
    assert out["kind"] == "return"


# ---- Warranty notices --------------------------------------------


def test_one_year_warranty():
    out = _find_warranty("1-year warranty included")
    assert out is not None
    assert out["kind"] == "warranty"
    assert out["duration_days"] == 365


def test_two_year_warranty():
    out = _find_warranty("2 year warranty")
    assert out is not None
    assert out["kind"] == "warranty"
    assert out["duration_days"] == 730


def test_90_day_warranty():
    out = _find_warranty("90-day warranty")
    assert out is not None
    assert out["kind"] == "warranty"
    assert out["duration_days"] == 90


def test_manufacturer_warranty_2_years():
    out = _find_warranty("Manufacturer warranty: 2 years")
    assert out is not None
    assert out["kind"] == "warranty"
    assert out["duration_days"] == 730
    assert "manufacturer" in out["notice"].lower()


def test_limited_1_year_warranty():
    out = _find_warranty("Limited 1-year warranty")
    assert out is not None
    assert out["kind"] == "warranty"
    assert out["duration_days"] == 365
    assert "limited" in out["notice"].lower()


def test_extended_warranty_3_years():
    out = _find_warranty("Extended warranty 3 years")
    assert out is not None
    assert out["kind"] == "warranty"
    assert out["duration_days"] == 1095


def test_warranty_colon_form():
    out = _find_warranty("Warranty: 18 months")
    assert out is not None
    assert out["kind"] == "warranty"
    assert out["duration_days"] == 540


def test_manufacturers_apostrophe_form():
    out = _find_warranty("Manufacturer's warranty 1 year")
    assert out is not None
    assert out["kind"] == "warranty"
    assert out["duration_days"] == 365


# ---- No-returns notices ------------------------------------------


def test_final_sale_no_refunds():
    out = _find_warranty("Final sale - no refunds")
    assert out is not None
    assert out["kind"] == "no_returns"
    assert out["duration_days"] is None


def test_final_sale_no_returns():
    out = _find_warranty("Final sale, no returns")
    assert out is not None
    assert out["kind"] == "no_returns"


def test_all_sales_final():
    out = _find_warranty("All sales final")
    assert out is not None
    assert out["kind"] == "no_returns"


def test_all_sales_are_final():
    out = _find_warranty("All sales are final")
    assert out is not None
    assert out["kind"] == "no_returns"


def test_no_returns_accepted():
    out = _find_warranty("No returns accepted")
    assert out is not None
    assert out["kind"] == "no_returns"


def test_no_returns_or_exchanges():
    out = _find_warranty("No returns or exchanges")
    assert out is not None
    assert out["kind"] == "no_returns"


def test_non_refundable():
    out = _find_warranty("Non-refundable purchase")
    assert out is not None
    assert out["kind"] == "no_returns"


def test_nonrefundable_no_hyphen():
    out = _find_warranty("Nonrefundable item")
    assert out is not None
    assert out["kind"] == "no_returns"


def test_bare_final_sale():
    out = _find_warranty("Notice: Final sale")
    assert out is not None
    assert out["kind"] == "no_returns"


def test_no_returns_beats_returns_matcher():
    """``Final sale - no returns`` must NOT be claimed by the
    return-window matcher just because it contains the word
    ``returns``."""
    out = _find_warranty("Final sale, no returns")
    assert out is not None
    assert out["kind"] == "no_returns"


# ---- Unit normalisation ------------------------------------------


def test_days_normalised():
    out = _find_warranty("Returns within 7 days")
    assert out["duration_days"] == 7


def test_weeks_normalised():
    out = _find_warranty("Returns within 4 weeks")
    assert out["duration_days"] == 28


def test_months_normalised():
    out = _find_warranty("6 month return policy")
    assert out["duration_days"] == 180


def test_year_singular():
    out = _find_warranty("1 year warranty")
    assert out["duration_days"] == 365


def test_yrs_alias():
    out = _find_warranty("2 yrs warranty")
    assert out["duration_days"] == 730


def test_yr_singular_alias():
    out = _find_warranty("1 yr warranty")
    assert out["duration_days"] == 365


def test_18_months_normalised():
    out = _find_warranty("18 months warranty")
    assert out["duration_days"] == 540


# ---- Real-world footers -----------------------------------------


def test_full_retail_footer():
    text = (
        "Best Buy\n"
        "Total: $499.99\n"
        "Payment: VISA ****1234\n"
        "Thank you for your purchase!\n"
        "Returns accepted within 30 days\n"
        "Manufacturer warranty: 1 year\n"
    )
    out = _find_warranty(text)
    assert out is not None
    # No-returns runs first; warranty runs before return-window
    # in the pattern catalogue. Manufacturer-prefixed beats bare
    # warranty so we land on the warranty entry first... actually
    # we land on whichever pattern matches FIRST in the ordered
    # list. The warranty matchers are ordered BEFORE return
    # matchers, so the manufacturer warranty wins.
    assert out["kind"] == "warranty"
    assert out["duration_days"] == 365


def test_return_only_footer():
    text = (
        "Walmart\n"
        "Total: $35.99\n"
        "Cash\n"
        "Returns within 90 days\n"
    )
    out = _find_warranty(text)
    assert out is not None
    assert out["kind"] == "return"
    assert out["duration_days"] == 90


def test_no_returns_footer():
    text = (
        "Designer Boutique\n"
        "Total: $250.00\n"
        "Final sale\n"
        "All sales final\n"
    )
    out = _find_warranty(text)
    assert out is not None
    assert out["kind"] == "no_returns"


# ---- Negative cases ---------------------------------------------


def test_no_warranty_phrase_returns_none():
    assert _find_warranty("Total: $25.00\nThank you!") is None


def test_empty_text():
    assert _find_warranty("") is None


def test_unrelated_text_with_year_word():
    out = _find_warranty("Year-end clearance sale")
    assert out is None


def test_unrelated_with_days_keyword():
    out = _find_warranty("Open 7 days a week")
    assert out is None


def test_unrelated_returns_in_sentence():
    out = _find_warranty("This product returns to the shelf weekly")
    # No numeric duration + no return-policy phrasing.
    assert out is None


# ---- Enrich integration -----------------------------------------


def test_enrich_backfills_warranty():
    text = "Total: $49.99\nReturns within 30 days"
    ocr = OCRResult(text=text, word_count=10, mean_confidence=0.9)
    out = enrich_receipt(None, ocr)
    assert out.warranty is not None
    assert out.warranty["kind"] == "return"
    assert out.warranty["duration_days"] == 30


def test_enrich_preserves_caller_warranty():
    """When an LLM has already supplied warranty, enrich keeps
    the caller's value rather than overwriting."""
    caller = ReceiptFields(
        warranty={"kind": "warranty", "duration_days": 730, "notice": "LLM-provided"}
    )
    text = "Returns within 30 days"
    ocr = OCRResult(text=text, word_count=4, mean_confidence=0.9)
    out = enrich_receipt(caller, ocr)
    assert out.warranty is not None
    assert out.warranty["notice"] == "LLM-provided"
    assert out.warranty["duration_days"] == 730


def test_restaurant_receipt_has_no_warranty():
    """Most restaurant receipts have no warranty notice."""
    text = (
        "Bistro Cafe\n"
        "Latte 5.00\n"
        "Croissant 3.50\n"
        "Subtotal 8.50\n"
        "Tax 0.85\n"
        "Total 9.35\n"
    )
    ocr = OCRResult(text=text, word_count=20, mean_confidence=0.9)
    out = enrich_receipt(None, ocr)
    assert out.warranty is None


def test_three_year_warranty():
    out = _find_warranty("3-year warranty included")
    assert out is not None
    assert out["kind"] == "warranty"
    assert out["duration_days"] == 1095


def test_notice_whitespace_normalised():
    """Multiple spaces in the matched notice collapse to one."""
    out = _find_warranty("Returns  within   30  days")
    assert out is not None
    # Storage should have single spaces.
    assert "  " not in out["notice"]


def test_uppercase_input():
    out = _find_warranty("RETURNS WITHIN 30 DAYS")
    assert out is not None
    assert out["kind"] == "return"
    assert out["duration_days"] == 30


def test_zero_duration_rejected():
    """A zero-day return policy is non-sensical and should not
    populate duration_days even if the matcher fires."""
    # 0 is excluded by bound check; we never accept it as
    # legitimate duration.
    out = _find_warranty("Returns within 0 days")
    # Match might still tag but duration stays None.
    if out is not None:
        assert out["duration_days"] is None


def test_huge_duration_capped_out():
    """A 1000-day return policy is OCR noise; we reject durations
    beyond 999."""
    out = _find_warranty("Returns within 9999 days")
    # The bound check yields duration_days=None on out-of-range.
    if out is not None:
        assert out["duration_days"] is None
