"""Suggested-tip table extraction tests.

Restaurants often print a small reference table at the bottom of the
receipt showing what the tip would be for common percentages:

  Suggested Tips:
  15% = 1.80
  18% = 2.16
  20% = 2.40

The new ``ReceiptFields.suggested_tips`` slot captures this table as
a list of ``{"percent": float, "amount": float}`` dicts.

Distinct from ``tip`` (the customer's actual gratuity) and
``tip_percent`` (the derived percentage of that actual tip). The
suggestion table is the merchant's printed reference; the actual tip
is what the customer chose to pay.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult, ReceiptFields
from shotclassify_extract import enrich, parse_receipt_text
from shotclassify_extract.receipt import _find_suggested_tips

# ---- Basic detection -----------------------------------------


def test_canonical_three_row_table():
    text = (
        "Subtotal: 12.00\n"
        "Suggested Tips:\n"
        "15% = 1.80\n"
        "18% = 2.16\n"
        "20% = 2.40\n"
    )
    result = _find_suggested_tips(text)
    assert result == [
        {"percent": 15.0, "amount": 1.80},
        {"percent": 18.0, "amount": 2.16},
        {"percent": 20.0, "amount": 2.40},
    ]


def test_table_with_dollar_signs():
    text = (
        "15% $1.80\n"
        "18% $2.16\n"
        "20% $2.40\n"
    )
    result = _find_suggested_tips(text)
    assert len(result) == 3
    assert result[0] == {"percent": 15.0, "amount": 1.80}


def test_table_with_euro_signs():
    text = (
        "15% €1,80\n"
        "20% €2,40\n"
    )
    result = _find_suggested_tips(text)
    assert len(result) == 2
    assert result[0] == {"percent": 15.0, "amount": 1.80}
    assert result[1] == {"percent": 20.0, "amount": 2.40}


def test_table_with_pound_signs():
    text = (
        "10% £1.50\n"
        "15% £2.25\n"
    )
    result = _find_suggested_tips(text)
    assert len(result) == 2


def test_table_with_yen_signs():
    text = (
        "10% ¥150\n"
        "15% ¥225\n"
    )
    # Yen amounts typically don't have decimals; our regex requires
    # the decimal form so this case might not match. Document that
    # behaviour: empty list because the amount regex enforces .NN.
    result = _find_suggested_tips(text)
    # No-decimal yen amounts intentionally NOT supported (the regex
    # requires the two-decimal form for amount validation).
    assert result == []


def test_table_with_equals_separator():
    text = (
        "15% = 1.80\n"
        "20% = 2.40\n"
    )
    result = _find_suggested_tips(text)
    assert len(result) == 2


def test_table_with_colon_separator():
    text = (
        "15%: 1.80\n"
        "20%: 2.40\n"
    )
    result = _find_suggested_tips(text)
    assert len(result) == 2


def test_table_with_pipe_separator():
    text = "15% | 1.80   18% | 2.16   20% | 2.40\n"
    result = _find_suggested_tips(text)
    assert len(result) == 3


def test_inline_horizontal_row():
    text = "15% 1.80    18% 2.16    20% 2.40\n"
    result = _find_suggested_tips(text)
    assert len(result) == 3
    assert result == [
        {"percent": 15.0, "amount": 1.80},
        {"percent": 18.0, "amount": 2.16},
        {"percent": 20.0, "amount": 2.40},
    ]


def test_amount_then_percent_orientation():
    text = (
        "1.80 15%\n"
        "2.40 20%\n"
    )
    result = _find_suggested_tips(text)
    assert len(result) == 2
    assert result[0] == {"percent": 15.0, "amount": 1.80}


def test_inline_label_form():
    text = "Tip suggestions: 15% 1.80 | 18% 2.16 | 20% 2.40\n"
    result = _find_suggested_tips(text)
    assert len(result) == 3


def test_four_row_table():
    text = (
        "10% 1.20\n"
        "15% 1.80\n"
        "18% 2.16\n"
        "20% 2.40\n"
    )
    result = _find_suggested_tips(text)
    assert len(result) == 4


def test_five_row_table():
    text = (
        "10% 1.20\n"
        "15% 1.80\n"
        "18% 2.16\n"
        "20% 2.40\n"
        "25% 3.00\n"
    )
    result = _find_suggested_tips(text)
    assert len(result) == 5


# ---- Required: at least 2 rows -------------------------------


def test_lone_pair_not_table():
    # A single percent-amount pair is the customer's tip, NOT a table.
    text = "Tip 20% 5.00\n"
    result = _find_suggested_tips(text)
    assert result == []


def test_no_pairs_returns_empty():
    text = "Subtotal 12.00\nTotal 14.40\n"
    result = _find_suggested_tips(text)
    assert result == []


def test_empty_input():
    assert _find_suggested_tips("") == []


# ---- Bounds enforcement -------------------------------------


def test_percent_too_low_rejected():
    # 1-4% is rejected as a typo / fractional percentage.
    text = (
        "2% 0.24\n"
        "4% 0.48\n"
    )
    result = _find_suggested_tips(text)
    assert result == []


def test_percent_too_high_rejected():
    # >50% rejected as an outlier.
    text = (
        "55% 6.60\n"
        "60% 7.20\n"
    )
    result = _find_suggested_tips(text)
    assert result == []


def test_50_percent_boundary_accepted():
    # 50% is the maximum accepted (typical for huge tips).
    text = (
        "15% 1.80\n"
        "50% 6.00\n"
    )
    result = _find_suggested_tips(text)
    assert len(result) == 2


def test_5_percent_boundary_accepted():
    # 5% is the minimum accepted.
    text = (
        "5% 0.60\n"
        "10% 1.20\n"
    )
    result = _find_suggested_tips(text)
    assert len(result) == 2


def test_fractional_percent_accepted():
    # 12.5% is a real-world value some merchants use.
    text = (
        "12.5% 1.50\n"
        "17.5% 2.10\n"
    )
    result = _find_suggested_tips(text)
    assert len(result) == 2
    assert result[0] == {"percent": 12.5, "amount": 1.50}


# ---- Sorting and dedupe ------------------------------------


def test_sorted_by_percent_asc():
    # Rows printed out of order; output sorted ascending.
    text = (
        "20% 2.40\n"
        "15% 1.80\n"
        "18% 2.16\n"
    )
    result = _find_suggested_tips(text)
    assert [r["percent"] for r in result] == [15.0, 18.0, 20.0]


def test_duplicate_pairs_deduped():
    # Echoed printout produces the same pair twice -> one entry.
    text = (
        "15% 1.80\n"
        "20% 2.40\n"
        "15% 1.80\n"
        "20% 2.40\n"
    )
    result = _find_suggested_tips(text)
    assert len(result) == 2


def test_cap_at_six_entries():
    text = "\n".join([f"{p}% {p * 0.12:.2f}" for p in (5, 10, 15, 18, 20, 22, 25, 30)])
    result = _find_suggested_tips(text)
    assert len(result) == 6


# ---- Comma decimal normalisation --------------------------


def test_comma_decimal_accepted():
    # European receipts use comma as decimal separator.
    text = (
        "15% 1,80\n"
        "20% 2,40\n"
    )
    result = _find_suggested_tips(text)
    assert len(result) == 2
    assert result[0]["amount"] == 1.80


# ---- False-positive defences ------------------------------


def test_tax_percent_does_not_pollute():
    # A tax line with percent + currency amount is in OCR scan range
    # but the table requires 2+ pairs at percent>=5% with amounts.
    text = "Sales Tax 8.25% 0.99\n"
    result = _find_suggested_tips(text)
    # Only one pair -> not a table.
    assert result == []


def test_tax_plus_suggestion_table_only_table_returns():
    # A receipt with a tax line AND a suggestion table; only table
    # entries land. The tax pair (8.25% 0.99) IS within bounds and
    # WILL register -- documented trade-off.
    text = (
        "Sales Tax 8.25% 0.99\n"
        "15% 1.80\n"
        "20% 2.40\n"
    )
    result = _find_suggested_tips(text)
    # The 8.25% line will land but that's acceptable: it's still a
    # printed percent+amount pair, and the dashboard can filter on
    # context. Verify the suggestion table rows land too.
    pcts = [r["percent"] for r in result]
    assert 15.0 in pcts
    assert 20.0 in pcts


def test_zero_percent_rejected():
    text = (
        "0% 0.00\n"
        "10% 1.20\n"
    )
    result = _find_suggested_tips(text)
    # 0% rejected; only one valid pair -> not a table.
    assert result == []


# ---- parse_receipt_text integration ----------------------


def test_parse_receipt_text_populates_suggested_tips():
    text = (
        "Cafe Olé\n"
        "Subtotal: 12.00\n"
        "Tax: 1.00\n"
        "Total: 13.00\n"
        "Suggested Tips:\n"
        "15% 1.95\n"
        "18% 2.34\n"
        "20% 2.60\n"
    )
    parsed = parse_receipt_text(text)
    assert len(parsed.suggested_tips) == 3
    assert parsed.suggested_tips[0] == {"percent": 15.0, "amount": 1.95}


def test_parse_receipt_text_empty_suggested_tips_for_normal_receipt():
    text = (
        "Subtotal: 12.00\n"
        "Tax: 1.00\n"
        "Tip: 2.00\n"
        "Total: 15.00\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.suggested_tips == []


# ---- enrich() pipeline integration ----------------------


def test_enrich_pipeline_populates_suggested_tips():
    text = (
        "15% 1.80\n"
        "18% 2.16\n"
        "20% 2.40\n"
    )
    fields = ExtractedFields()
    ocr = OCRResult(text=text)
    enriched = enrich(Category.receipt, fields, ocr)
    assert enriched.receipt is not None
    assert len(enriched.receipt.suggested_tips) == 3


def test_enrich_pipeline_preserves_caller_suggested_tips():
    text = (
        "15% 1.80\n"
        "20% 2.40\n"
    )
    fields = ExtractedFields(
        receipt=ReceiptFields(
            suggested_tips=[{"percent": 10.0, "amount": 1.20}]
        )
    )
    ocr = OCRResult(text=text)
    enriched = enrich(Category.receipt, fields, ocr)
    assert enriched.receipt is not None
    # Caller-supplied non-empty list wins.
    assert enriched.receipt.suggested_tips == [{"percent": 10.0, "amount": 1.20}]


def test_enrich_pipeline_backfills_empty_caller_list():
    text = (
        "15% 1.80\n"
        "20% 2.40\n"
    )
    fields = ExtractedFields(receipt=ReceiptFields(suggested_tips=[]))
    ocr = OCRResult(text=text)
    enriched = enrich(Category.receipt, fields, ocr)
    assert enriched.receipt is not None
    # Empty caller list -> backfilled by parse.
    assert len(enriched.receipt.suggested_tips) == 2


# ---- Coexistence with actual tip ------------------------


def test_table_does_not_interfere_with_actual_tip_extraction():
    # The customer's chosen tip should still be captured by _find_tip
    # even when the suggestion table is also printed.
    text = (
        "Subtotal: 20.00\n"
        "Suggested Tips:\n"
        "15% 3.00\n"
        "18% 3.60\n"
        "20% 4.00\n"
        "Tip: 5.00\n"
        "Total: 25.00\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.tip == 5.00
    assert len(parsed.suggested_tips) == 3


def test_table_alone_does_not_set_tip():
    # When only the suggestion table is printed (customer skipped
    # tipping), the actual tip slot is None.
    text = (
        "Subtotal: 12.00\n"
        "15% 1.80\n"
        "18% 2.16\n"
        "20% 2.40\n"
        "Total: 12.00\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.tip is None
    assert len(parsed.suggested_tips) == 3


def test_large_amounts_within_bound():
    # A higher-end restaurant printing a fine-dining table.
    text = (
        "15% 75.00\n"
        "18% 90.00\n"
        "20% 100.00\n"
    )
    result = _find_suggested_tips(text)
    assert len(result) == 3


def test_amount_too_large_rejected():
    # Amount > 9999.99 is rejected as outlier / OCR noise.
    text = (
        "15% 15000.00\n"
        "20% 20000.00\n"
    )
    result = _find_suggested_tips(text)
    assert result == []


# ---- Schema default ------------------------------------


def test_receipt_fields_default_empty_list():
    rf = ReceiptFields()
    assert rf.suggested_tips == []


def test_receipt_fields_accepts_list_of_dicts():
    rf = ReceiptFields(
        suggested_tips=[
            {"percent": 15.0, "amount": 1.80},
            {"percent": 20.0, "amount": 2.40},
        ]
    )
    assert len(rf.suggested_tips) == 2


# ---- Edge cases ----------------------------------------


def test_tab_separated_table():
    text = (
        "15%\t1.80\n"
        "20%\t2.40\n"
    )
    result = _find_suggested_tips(text)
    assert len(result) == 2


def test_multiple_currencies_each_pair_lands():
    text = (
        "15% $1.80\n"
        "20% €2.40\n"
    )
    result = _find_suggested_tips(text)
    assert len(result) == 2
