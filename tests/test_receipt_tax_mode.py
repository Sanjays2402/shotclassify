"""Receipt tax-mode detection (inclusive vs exclusive).

A new ``ReceiptFields.tax_mode`` slot carries one of ``"inclusive"``
/ ``"exclusive"`` / ``None``. Inclusive cues (``VAT included``,
``incl. GST``, ``prices include tax``) are common in EU / AU / NZ /
IN receipts. Exclusive cues (``+ tax``, ``plus tax``, ``tax extra``,
``excl. VAT``, ``ex GST``) dominate US sales-tax receipts.

When both signals appear (rare but possible on multi-page invoices)
the FIRST one in OCR order wins so the result mirrors how a human
would interpret the document top-to-bottom. When neither signal is
present we return ``None`` and the dashboard can fall back to its
own subtotal/total math.
"""
from __future__ import annotations

from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract import enrich_receipt
from shotclassify_extract.receipt import _detect_tax_mode, parse_receipt_text

# ---- _detect_tax_mode helper -----------------------------------------


def test_inclusive_vat_included():
    assert _detect_tax_mode("Total 12.00 VAT included") == "inclusive"


def test_inclusive_incl_vat():
    assert _detect_tax_mode("Subtotal 10.00 incl. VAT") == "inclusive"


def test_inclusive_incl_dot_tax():
    assert _detect_tax_mode("Total 5.00 incl. tax") == "inclusive"


def test_inclusive_incl_gst():
    """AU/NZ phrasing: ``Total $22 incl. GST``."""
    assert _detect_tax_mode("Total $22.00 incl. GST") == "inclusive"


def test_inclusive_gst_inclusive():
    assert _detect_tax_mode("GST inclusive") == "inclusive"


def test_inclusive_prices_include_tax():
    """The marketing-style phrase used at the top of menus."""
    assert _detect_tax_mode("All prices include tax") == "inclusive"


def test_inclusive_prices_include_vat_plural():
    assert _detect_tax_mode("Prices include VAT") == "inclusive"


def test_inclusive_of_gst():
    """IN/AU printers like ``Total inclusive of GST``."""
    assert _detect_tax_mode("Total inclusive of GST") == "inclusive"


def test_inclusive_of_hst():
    """CA province (HST = harmonized sales tax)."""
    assert _detect_tax_mode("Inclusive of HST") == "inclusive"


def test_inclusive_tax_included_with_amount():
    """Inclusive cue can sit anywhere in the line."""
    assert _detect_tax_mode("Tax included 1.50") == "inclusive"


def test_exclusive_plus_tax():
    assert _detect_tax_mode("Total 10.00 + tax") == "exclusive"


def test_exclusive_plus_vat():
    assert _detect_tax_mode("Subtotal 8.00 + VAT") == "exclusive"


def test_exclusive_plus_gst():
    assert _detect_tax_mode("Total $20 + GST") == "exclusive"


def test_exclusive_plus_word():
    """The word ``plus`` (no ``+`` sign) also tags exclusive."""
    assert _detect_tax_mode("Subtotal 12.00 plus tax") == "exclusive"


def test_exclusive_tax_extra():
    assert _detect_tax_mode("Subtotal 12.00 tax extra") == "exclusive"


def test_exclusive_tax_not_included():
    assert _detect_tax_mode("Total 30.00 tax not included") == "exclusive"


def test_exclusive_excl_vat():
    assert _detect_tax_mode("Subtotal 12.00 excl. VAT") == "exclusive"


def test_exclusive_excl_dot_gst():
    assert _detect_tax_mode("Subtotal $12.00 excl. GST") == "exclusive"


def test_exclusive_vat_excl():
    assert _detect_tax_mode("Subtotal 10.00 VAT excl.") == "exclusive"


def test_exclusive_ex_vat_short():
    """Common shorthand on UK invoices: ``Total 100.00 ex VAT``."""
    assert _detect_tax_mode("Total 100.00 ex VAT") == "exclusive"


def test_exclusive_ex_gst_short():
    assert _detect_tax_mode("Total $50 ex GST") == "exclusive"


def test_exclusive_prices_exclude_tax():
    assert _detect_tax_mode("Prices exclude tax") == "exclusive"


def test_exclusive_exclusive_of_gst():
    assert _detect_tax_mode("Subtotal exclusive of GST") == "exclusive"


def test_none_when_no_signal():
    """Plain receipt with no inclusive/exclusive cue returns None."""
    assert _detect_tax_mode("Subtotal 12.00\nTax 1.00\nTotal 13.00") is None


def test_none_for_empty_text():
    assert _detect_tax_mode("") is None
    assert _detect_tax_mode("   ") is None


def test_unrelated_tax_words_do_not_trigger():
    """``tax id`` / ``tax-deductible`` / ``federal tax`` must not tag.

    Only the explicit included/excluded/extra/+ vocabulary triggers
    a mode; words like ``tax id`` lack the trailing verb.
    """
    assert _detect_tax_mode("Tax ID: 12-345") is None
    assert _detect_tax_mode("Federal tax 5.00") is None
    assert _detect_tax_mode("Tax-deductible: yes") is None


def test_inclusive_wins_when_first_in_order():
    """When both signals appear, first-in-OCR-order wins."""
    text = "Total VAT included\nNote: prices exclude tax (legacy field)"
    assert _detect_tax_mode(text) == "inclusive"


def test_exclusive_wins_when_first_in_order():
    text = "Note: prices exclude tax\nTotal VAT included"
    assert _detect_tax_mode(text) == "exclusive"


def test_case_insensitive():
    assert _detect_tax_mode("TOTAL VAT INCLUDED") == "inclusive"
    assert _detect_tax_mode("Total + TAX") == "exclusive"


# ---- parse_receipt_text wiring ---------------------------------------


def _receipt(tax_note: str) -> str:
    return f"Cafe\nSubtotal 10.00\nTax 1.00\nTotal 11.00\n{tax_note}\n"


def test_parse_receipt_text_inclusive():
    fields = parse_receipt_text(_receipt("Prices include VAT"))
    assert fields.tax_mode == "inclusive"


def test_parse_receipt_text_exclusive():
    fields = parse_receipt_text(_receipt("Total + tax"))
    assert fields.tax_mode == "exclusive"


def test_parse_receipt_text_no_signal_defaults_none():
    fields = parse_receipt_text("Cafe\nSubtotal 10.00\nTax 1.00\nTotal 11.00\n")
    assert fields.tax_mode is None


# ---- enrich_receipt: caller-supplied value wins ----------------------


def test_enrich_receipt_caller_supplied_inclusive_wins():
    """LLM-supplied tax_mode is preserved; the heuristic only fills the gap."""
    existing = ReceiptFields(tax_mode="inclusive")
    # Even though the text screams exclusive, caller-supplied wins.
    ocr = OCRResult(text="Total 10.00 + tax")
    out = enrich_receipt(existing, ocr)
    assert out.tax_mode == "inclusive"


def test_enrich_receipt_fills_when_caller_absent():
    """No caller value -> heuristic fills it in."""
    ocr = OCRResult(text="Cafe\nSubtotal 10.00\nTotal 10.00 incl. VAT")
    out = enrich_receipt(None, ocr)
    assert out.tax_mode == "inclusive"


def test_enrich_receipt_none_when_no_signal():
    """Neither caller nor text supplies a cue -> stays None."""
    ocr = OCRResult(text="Cafe\nSubtotal 10.00\nTotal 11.00\n")
    out = enrich_receipt(None, ocr)
    assert out.tax_mode is None
