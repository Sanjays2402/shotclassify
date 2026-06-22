"""Tax-jurisdiction breakdown tests (``ReceiptFields.tax_lines``).

When a receipt prints MORE than one tax line we surface each
jurisdiction as a ``{"jurisdiction": str, "amount": float}`` dict.
The top-level ``tax`` slot continues to carry the single SUM
(last-match-wins on the bare ``Tax`` keyword) for backward-compat
with existing dashboards.

Recognised jurisdiction vocabulary:
* US: State Tax, County Tax, City Tax, Local Tax, Sales Tax,
  Federal Tax, Use Tax
* Canada: HST, PST, GST, QST
* EU / UK: VAT, EU VAT, Import VAT
* AU / NZ: GST
* India: CGST, SGST, IGST, UTGST, CESS
* Other: Service Tax, Liquor Tax, Tobacco Tax, Hotel Tax,
  Lodging Tax, Tourism Tax, Restaurant Tax, Resort Fee Tax
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult, ReceiptFields
from shotclassify_extract import enrich, parse_receipt_text
from shotclassify_extract.receipt import _find_tax_lines

# ---- Empty / single-jurisdiction (no breakdown) ----------------


def test_empty_text_returns_empty_list():
    assert _find_tax_lines("") == []


def test_no_tax_lines_returns_empty():
    text = "Subtotal: 10.00\nTotal: 10.00\n"
    assert _find_tax_lines(text) == []


def test_single_jurisdiction_returns_empty():
    # ``tax_lines`` only carries a breakdown when MULTIPLE
    # jurisdictions appear; the single-line case sits in ``tax``.
    text = "Subtotal: 10.00\nState Tax 0.80\nTotal: 10.80\n"
    assert _find_tax_lines(text) == []


def test_bare_tax_keyword_not_in_catalogue():
    # ``Tax`` alone is NOT in the jurisdiction catalogue; it lives in
    # the top-level ``tax`` slot.
    text = "Subtotal: 10.00\nTax 0.80\nTotal: 10.80\n"
    assert _find_tax_lines(text) == []


# ---- Two-jurisdiction US breakdowns ----------------------------


def test_state_and_county_tax():
    text = (
        "Subtotal: 100.00\n"
        "State Tax 6.00\n"
        "County Tax 1.50\n"
        "Total: 107.50\n"
    )
    out = _find_tax_lines(text)
    assert len(out) == 2
    assert {"jurisdiction": "State Tax", "amount": 6.00} in out
    assert {"jurisdiction": "County Tax", "amount": 1.50} in out


def test_state_county_city_tax():
    text = (
        "Subtotal: 100.00\n"
        "State Tax 1.50\n"
        "County Tax 0.50\n"
        "City Tax 0.25\n"
        "Total: 102.25\n"
    )
    out = _find_tax_lines(text)
    assert len(out) == 3
    juris = [e["jurisdiction"] for e in out]
    assert juris == ["State Tax", "County Tax", "City Tax"]


def test_sales_tax_plus_local_tax():
    text = "Sales Tax 4.00\nLocal Tax 1.00\n"
    out = _find_tax_lines(text)
    assert len(out) == 2
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["Local Tax", "Sales Tax"]


def test_federal_plus_state_tax():
    text = "Federal Tax 2.50\nState Tax 1.00\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["Federal Tax", "State Tax"]


def test_use_tax_alongside_sales_tax():
    text = "Sales Tax 5.00\nUse Tax 0.50\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["Sales Tax", "Use Tax"]


# ---- Canadian HST / PST / GST / QST ----------------------------


def test_canadian_hst_pst():
    text = "Subtotal: 100.00\nHST 13.00\nPST 7.00\nTotal: 120.00\n"
    out = _find_tax_lines(text)
    assert len(out) == 2
    assert {"jurisdiction": "HST", "amount": 13.00} in out
    assert {"jurisdiction": "PST", "amount": 7.00} in out


def test_canadian_gst_pst():
    text = "GST 5.00\nPST 8.00\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["GST", "PST"]


def test_canadian_gst_qst():
    text = "GST 5.00\nQST 9.98\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["GST", "QST"]


def test_canadian_all_four():
    # Receipts rarely print all four but the matcher should handle it.
    text = "HST 1.30\nPST 0.40\nGST 0.50\nQST 0.90\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["GST", "HST", "PST", "QST"]


# ---- EU / UK VAT shapes ----------------------------------------


def test_vat_plus_import_vat():
    text = "VAT 20.00\nImport VAT 5.00\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["Import VAT", "VAT"]


def test_eu_vat_distinct_from_vat():
    text = "EU VAT 10.00\nImport VAT 5.00\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["EU VAT", "Import VAT"]


def test_eu_vat_does_not_double_match_vat():
    # "EU VAT" must NOT also be captured as plain "VAT" -- the
    # longer keyword wins via the longest-first ordering.
    text = "EU VAT 10.00\nImport VAT 5.00\n"
    out = _find_tax_lines(text)
    # No bare "VAT" entry should exist.
    juris = [e["jurisdiction"] for e in out]
    assert "VAT" not in juris


# ---- Indian GST family ----------------------------------------


def test_cgst_sgst_pair():
    text = "Subtotal: 1000.00\nCGST 9.00\nSGST 9.00\nTotal: 1018.00\n"
    out = _find_tax_lines(text)
    assert len(out) == 2
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["CGST", "SGST"]


def test_igst_inter_state():
    text = "IGST 18.00\nCESS 2.00\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["CESS", "IGST"]


def test_utgst_union_territory():
    text = "UTGST 5.00\nCGST 5.00\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["CGST", "UTGST"]


def test_indian_full_split():
    text = "CGST 9.00\nSGST 9.00\nCESS 0.50\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["CESS", "CGST", "SGST"]


# ---- Specialty taxes -------------------------------------------


def test_hotel_plus_tourism_tax():
    text = "Hotel Tax 12.00\nTourism Tax 3.00\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["Hotel Tax", "Tourism Tax"]


def test_liquor_plus_tobacco_tax():
    text = "Liquor Tax 5.00\nTobacco Tax 8.50\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["Liquor Tax", "Tobacco Tax"]


def test_restaurant_plus_state_tax():
    text = "Restaurant Tax 1.50\nState Tax 0.80\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["Restaurant Tax", "State Tax"]


def test_lodging_tax_alone_with_state():
    text = "Lodging Tax 4.00\nState Tax 1.00\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["Lodging Tax", "State Tax"]


def test_resort_fee_tax_specific():
    # "Resort Fee Tax" is the most specific multi-word form; it
    # must NOT also match the shorter "Service Tax" or bare keywords.
    text = "Resort Fee Tax 5.00\nState Tax 2.00\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["Resort Fee Tax", "State Tax"]


def test_service_tax_legacy_india():
    text = "Service Tax 1.50\nVAT 5.00\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["Service Tax", "VAT"]


# ---- Top-to-bottom ordering ------------------------------------


def test_order_preserves_source_order():
    text = "Subtotal: 100.00\nState Tax 5.00\nCounty Tax 1.50\nCity Tax 0.50\n"
    out = _find_tax_lines(text)
    juris = [e["jurisdiction"] for e in out]
    assert juris == ["State Tax", "County Tax", "City Tax"]


def test_order_canadian_top_to_bottom():
    text = "Subtotal: 100.00\nGST 5.00\nPST 7.00\nTotal: 112.00\n"
    out = _find_tax_lines(text)
    juris = [e["jurisdiction"] for e in out]
    assert juris == ["GST", "PST"]


# ---- Amount parsing edge cases ---------------------------------


def test_amount_with_dollar_sign():
    text = "State Tax $5.00\nCounty Tax $1.50\n"
    out = _find_tax_lines(text)
    assert {"jurisdiction": "State Tax", "amount": 5.00} in out


def test_amount_with_euro_sign():
    text = "VAT €20.00\nImport VAT €5.00\n"
    out = _find_tax_lines(text)
    assert {"jurisdiction": "VAT", "amount": 20.00} in out


def test_amount_with_comma_decimal():
    # Comma-decimal style (EU) is recognised.
    text = "VAT 20,00\nImport VAT 5,50\n"
    out = _find_tax_lines(text)
    assert {"jurisdiction": "VAT", "amount": 20.00} in out
    assert {"jurisdiction": "Import VAT", "amount": 5.50} in out


def test_amount_with_colon_separator():
    text = "State Tax: 5.00\nCity Tax: 1.00\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["City Tax", "State Tax"]


def test_amount_with_dash_separator():
    text = "State Tax - 5.00\nLocal Tax - 1.00\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["Local Tax", "State Tax"]


# ---- Last-occurrence semantics ---------------------------------


def test_repeated_keyword_uses_last_value():
    # A receipt that prints a summary at the bottom should use the
    # LAST occurrence of each keyword (matches the other receipt
    # extractors' last-wins semantics).
    text = "State Tax 5.00\nLocal Tax 1.00\n--Summary--\nState Tax 5.50\n"
    out = _find_tax_lines(text)
    for e in out:
        if e["jurisdiction"] == "State Tax":
            assert e["amount"] == 5.50


# ---- Word-boundary defence -------------------------------------


def test_bookstate_does_not_misfire():
    # Negative-lookbehind on alphas keeps "Bookstate Tax 5.00" from
    # being misread; but our keyword IS "State Tax" so a prose
    # "Bookstate" would only false-positive if the alpha defence
    # failed. Since the lookbehind requires non-alpha before the
    # keyword, "Bookstate Tax" is REJECTED.
    text = "Bookstate Tax 5.00\nLocal Tax 1.00\n"
    out = _find_tax_lines(text)
    juris = [e["jurisdiction"] for e in out]
    # Only "Local Tax" should land; the "Bookstate Tax" prose
    # rejects "State Tax" via the alpha-lookbehind.
    assert "State Tax" not in juris


def test_vat_inside_word_rejected():
    # "Privatize" should NOT match "VAT".
    text = "Privatize 5.00\nState Tax 1.00\n"
    out = _find_tax_lines(text)
    juris = [e["jurisdiction"] for e in out]
    assert "VAT" not in juris


# ---- Mixed currency / vocabulary ------------------------------


def test_mixed_us_and_canadian_separate():
    # A receipt that somehow prints both US state tax AND GST shouldn't
    # collapse them; both jurisdictions are distinct.
    text = "State Tax 5.00\nGST 1.00\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["GST", "State Tax"]


def test_us_with_eu_vat():
    text = "State Tax 5.00\nVAT 10.00\n"
    out = _find_tax_lines(text)
    juris = sorted(e["jurisdiction"] for e in out)
    assert juris == ["State Tax", "VAT"]


# ---- Out-of-range amounts ------------------------------------


def test_zero_amount_rejected():
    # Amounts must be >= 0.01.
    text = "State Tax 0.00\nLocal Tax 1.00\n"
    out = _find_tax_lines(text)
    juris = [e["jurisdiction"] for e in out]
    assert "State Tax" not in juris


def test_six_digit_amount_rejected():
    # The amount regex requires \d{1,5} (no 6-digit numbers).
    # Match-failure on State Tax leaves only Local Tax, which falls
    # below the >=2 jurisdiction threshold for emission.
    text = "State Tax 999999.00\nLocal Tax 1.00\nCity Tax 0.50\n"
    out = _find_tax_lines(text)
    juris = [e["jurisdiction"] for e in out]
    # State Tax rejected (6 digits); Local Tax + City Tax remain.
    assert "State Tax" not in juris
    assert "Local Tax" in juris
    assert "City Tax" in juris


# ---- parse_receipt_text integration ----------------------------


def test_parse_receipt_text_populates_tax_lines():
    text = "Subtotal: 100.00\nState Tax 6.00\nCounty Tax 1.50\nTotal: 107.50\n"
    parsed = parse_receipt_text(text)
    assert len(parsed.tax_lines) == 2
    juris = [e["jurisdiction"] for e in parsed.tax_lines]
    assert "State Tax" in juris
    assert "County Tax" in juris


def test_parse_receipt_text_single_jurisdiction_empty():
    text = "Subtotal: 100.00\nSales Tax 8.00\nTotal: 108.00\n"
    parsed = parse_receipt_text(text)
    # Single jurisdiction => empty list; the amount lives in the
    # top-level ``tax`` slot via _find_amount_after("tax").
    assert parsed.tax_lines == []


def test_parse_receipt_text_no_tax_empty():
    text = "Subtotal: 10.00\nTotal: 10.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.tax_lines == []


# ---- enrich integration ---------------------------------------


def test_enrich_writes_tax_lines():
    text = "Subtotal: 100.00\nState Tax 6.00\nCounty Tax 1.50\nTotal: 107.50\n"
    ocr = OCRResult(text=text)
    out = enrich(Category.receipt, ExtractedFields(), ocr)
    assert out.receipt is not None
    assert len(out.receipt.tax_lines) == 2


def test_enrich_preserves_caller_tax_lines():
    # When the caller (LLM) already supplied tax_lines, we keep them
    # rather than overriding from the OCR pass.
    text = "Subtotal: 100.00\nState Tax 6.00\nCounty Tax 1.50\nTotal: 107.50\n"
    ocr = OCRResult(text=text)
    caller = ReceiptFields(
        tax_lines=[{"jurisdiction": "LLM Special Tax", "amount": 99.99}]
    )
    fields = ExtractedFields(receipt=caller)
    out = enrich(Category.receipt, fields, ocr)
    assert out.receipt is not None
    assert len(out.receipt.tax_lines) == 1
    assert out.receipt.tax_lines[0]["jurisdiction"] == "LLM Special Tax"


def test_enrich_backfills_when_caller_empty():
    text = "State Tax 6.00\nCounty Tax 1.50\n"
    ocr = OCRResult(text=text)
    caller = ReceiptFields(tax_lines=[])
    fields = ExtractedFields(receipt=caller)
    out = enrich(Category.receipt, fields, ocr)
    assert out.receipt is not None
    juris = [e["jurisdiction"] for e in out.receipt.tax_lines]
    assert "State Tax" in juris


# ---- Coexistence with top-level ``tax`` -----------------------


def test_top_level_tax_still_populated():
    # A bare "Tax 2.00" line still feeds the top-level ``tax`` slot
    # even when no jurisdictions are present.
    text = "Subtotal: 10.00\nTax 0.80\nTotal: 10.80\n"
    parsed = parse_receipt_text(text)
    assert parsed.tax == 0.80
    assert parsed.tax_lines == []


def test_top_level_tax_sums_when_jurisdictions_present():
    # When the printer ALSO prints a "Total Tax" summary line, we
    # surface BOTH: the breakdown into tax_lines AND the summary
    # in the top-level tax slot (last-match-wins on "tax").
    text = (
        "Subtotal: 100.00\n"
        "State Tax 6.00\n"
        "County Tax 1.50\n"
        "Tax 7.50\n"  # printer summary
        "Total: 107.50\n"
    )
    parsed = parse_receipt_text(text)
    # Top-level tax captures the summary line.
    assert parsed.tax == 7.50
    # tax_lines captures the breakdown.
    assert len(parsed.tax_lines) == 2
