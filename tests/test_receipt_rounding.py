"""Cash-rounding adjustment extraction tests.

A new ``ReceiptFields.rounding`` slot surfaces the regulatory
cash-rounding adjustment printed on receipts in countries where
small denomination coins are out of circulation (Australia, Canada,
New Zealand, Norway, Sweden, Switzerland, Hungary, Ireland,
Netherlands, etc.).

Recognised wording (case-insensitive; ordered most-specific first):

  Rounding Adjustment  -0.04
  Cash Rounding         0.03
  Cash Discrepancy      0.01
  Rounding             -0.02
  Round Down            0.02
  Round Up              0.03

The amount is stored SIGNED so dashboards know whether the customer
benefited from rounding (negative) or paid a tiny premium (positive).
``None`` for normal receipts that do not apply cash-rounding.

Distinct from ``discount`` (a marketing reduction the merchant
chose) and ``change`` (the bills / coins handed back); rounding is
a regulatory adjustment for small-coin scarcity.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult, ReceiptFields
from shotclassify_extract import enrich, parse_receipt_text
from shotclassify_extract.receipt import _find_rounding, _find_signed_amount_after

# ---- Signed amount helper -------------------------------------


def test_signed_amount_after_negative():
    assert _find_signed_amount_after("Rounding -0.02", "rounding") == -0.02


def test_signed_amount_after_positive():
    assert _find_signed_amount_after("Cash Rounding 0.03", "cash rounding") == 0.03


def test_signed_amount_after_explicit_plus():
    assert _find_signed_amount_after("Rounding +0.02", "rounding") == 0.02


def test_signed_amount_after_no_match():
    assert _find_signed_amount_after("Subtotal 10.00", "rounding") is None


def test_signed_amount_after_last_wins():
    text = "Rounding 0.02\n...\nRounding -0.03\n"
    assert _find_signed_amount_after(text, "rounding") == -0.03


# ---- Basic rounding detection --------------------------------


def test_rounding_negative():
    text = "Subtotal: 9.97\nRounding -0.02\nTotal: 9.95\n"
    assert _find_rounding(text) == -0.02


def test_rounding_positive():
    text = "Subtotal: 9.93\nRounding 0.02\nTotal: 9.95\n"
    assert _find_rounding(text) == 0.02


def test_cash_rounding_keyword():
    text = "Cash Rounding 0.03\n"
    assert _find_rounding(text) == 0.03


def test_rounding_adjustment_keyword():
    text = "Rounding Adjustment -0.04\n"
    assert _find_rounding(text) == -0.04


def test_cash_discrepancy_keyword():
    text = "Cash Discrepancy 0.01\n"
    assert _find_rounding(text) == 0.01


def test_round_down_keyword():
    text = "Round Down 0.02\n"
    assert _find_rounding(text) == 0.02


def test_round_up_keyword():
    text = "Round Up 0.03\n"
    assert _find_rounding(text) == 0.03


# ---- Keyword priority --------------------------------------


def test_multi_word_keyword_wins_over_bare_rounding():
    # ``Rounding Adjustment -0.04`` AND ``Rounding -0.02`` should
    # land the multi-word form first (most specific).
    text = "Rounding Adjustment -0.04\nRounding -0.02\n"
    assert _find_rounding(text) == -0.04


def test_cash_rounding_wins_over_bare_rounding():
    text = "Cash Rounding 0.03\nRounding -0.02\n"
    assert _find_rounding(text) == 0.03


def test_bare_rounding_when_only_keyword_present():
    text = "Subtotal 9.97\nRounding -0.02\nTotal 9.95\n"
    assert _find_rounding(text) == -0.02


# ---- Currency symbol handling -----------------------------


def test_rounding_with_dollar_symbol():
    text = "Rounding -$0.02\n"
    assert _find_rounding(text) == -0.02


def test_rounding_with_euro_symbol():
    text = "Rounding -€0.02\n"
    assert _find_rounding(text) == -0.02


def test_rounding_with_comma_decimal():
    # European decimal style (1,23 instead of 1.23).
    text = "Rounding -0,02\n"
    assert _find_rounding(text) == -0.02


# ---- Case insensitivity -----------------------------------


def test_rounding_uppercase():
    text = "ROUNDING -0.02\n"
    assert _find_rounding(text) == -0.02


def test_rounding_mixed_case():
    text = "Cash ROUNDING -0.03\n"
    assert _find_rounding(text) == -0.03


# ---- No rounding line -----------------------------------


def test_no_rounding_returns_none():
    text = "Subtotal: 10.00\nTax: 0.50\nTotal: 10.50\n"
    assert _find_rounding(text) is None


def test_empty_text_returns_none():
    assert _find_rounding("") is None


# ---- Prose / false-positive defence -------------------


def test_prose_round_not_matched_without_amount():
    # ``Round trip 3 days`` has no digit-amount immediately after
    # the keyword, so the regex won't fire.
    text = "Round trip flight 3 days later\n"
    assert _find_rounding(text) is None


def test_rounding_keyword_inside_word_rejected():
    # ``Surrounding -0.02`` should NOT match ``rounding -0.02``
    # because the negative-lookbehind on alphas blocks it.
    text = "Surrounding -0.02 area\n"
    assert _find_rounding(text) is None


# ---- Integration with parse_receipt_text -----------------


def test_parse_receipt_text_negative_rounding():
    text = (
        "AUSSIE COFFEE\n"
        "Latte         4.50\n"
        "Muffin        3.97\n"
        "Subtotal:     8.47\n"
        "Rounding     -0.02\n"
        "Total:        8.45\n"
        "Cash         10.00\n"
        "Change        1.55\n"
    )
    rec = parse_receipt_text(text)
    assert rec.rounding == -0.02
    # Sanity: other receipt fields should still be parsed correctly.
    assert rec.total == 8.45


def test_parse_receipt_text_positive_rounding():
    text = (
        "DAIRY MART\n"
        "Bread         2.49\n"
        "Subtotal:     2.49\n"
        "Cash Rounding 0.01\n"
        "Total:        2.50\n"
    )
    rec = parse_receipt_text(text)
    assert rec.rounding == 0.01


def test_parse_receipt_text_no_rounding():
    text = "Subtotal: 10.00\nTax: 0.50\nTotal: 10.50\n"
    rec = parse_receipt_text(text)
    assert rec.rounding is None


# ---- Pipeline integration -----------------------------


def test_enrich_pipeline_populates_rounding():
    text = "Subtotal: 9.97\nRounding -0.02\nTotal: 9.95\n"
    ocr = OCRResult(text=text)
    out = enrich(Category.receipt, ExtractedFields(), ocr)
    assert out.receipt is not None
    assert out.receipt.rounding == -0.02


def test_enrich_pipeline_caller_supplied_wins():
    text = "Subtotal: 9.97\nRounding -0.02\nTotal: 9.95\n"
    ocr = OCRResult(text=text)
    pre = ExtractedFields(receipt=ReceiptFields(rounding=-0.99))
    out = enrich(Category.receipt, pre, ocr)
    # Caller-supplied -0.99 wins over the parsed -0.02 because
    # the merge keeps existing non-zero values.
    assert out.receipt is not None
    assert out.receipt.rounding == -0.99


def test_enrich_pipeline_no_rounding_keeps_none():
    text = "Subtotal: 10.00\nTotal: 10.00\n"
    ocr = OCRResult(text=text)
    out = enrich(Category.receipt, ExtractedFields(), ocr)
    assert out.receipt is not None
    assert out.receipt.rounding is None


# ---- Real-world receipt samples ----------------------


def test_aud_supermarket_cash_rounding():
    text = (
        "WOOLWORTHS\n"
        "Bananas 1.5kg     4.49\n"
        "Milk 2L           3.50\n"
        "Bread             3.99\n"
        "Subtotal:        11.98\n"
        "Rounding:        -0.03\n"
        "Total:           11.95\n"
        "Cash:            12.00\n"
        "Change:           0.05\n"
    )
    rec = parse_receipt_text(text)
    assert rec.rounding == -0.03
    assert rec.total == 11.95
    assert rec.change == 0.05


def test_cad_pharmacy_cash_rounding():
    text = (
        "SHOPPERS DRUG MART\n"
        "Toothpaste        4.97\n"
        "Subtotal:         4.97\n"
        "GST:              0.25\n"
        "PST:              0.30\n"
        "Total:            5.52\n"
        "Cash Rounding:   -0.02\n"
        "Cash Tendered:   10.00\n"
        "Change:           4.46\n"
    )
    rec = parse_receipt_text(text)
    assert rec.rounding == -0.02
    assert rec.total == 5.52


def test_nzd_cafe_cash_rounding():
    text = (
        "FLIGHT COFFEE\n"
        "Flat White        4.50\n"
        "Total:            4.50\n"
        "Rounding:         0.00\n"
        "Cash:             5.00\n"
        "Change:           0.50\n"
    )
    rec = parse_receipt_text(text)
    # Explicit 0.00 rounding intentionally registers because
    # printing the line at all is a useful signal.
    assert rec.rounding == 0.0


def test_eur_dutch_supermarket_cash_discrepancy():
    text = (
        "ALBERT HEIJN\n"
        "Stroopwafels     2.49\n"
        "Kaas             3.78\n"
        "Subtotal:        6.27\n"
        "Cash Discrepancy 0.03\n"
        "Total:           6.30\n"
    )
    rec = parse_receipt_text(text)
    assert rec.rounding == 0.03
    assert rec.total == 6.30
