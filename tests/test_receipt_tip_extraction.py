"""Receipt tip / gratuity extraction.

Covers the field added in feature/autoship tick 1: ``ReceiptFields.tip``.
The parser must pick up "Tip", "Gratuity", "Service charge" and bare
"Service" lines, prefer the LAST occurrence so a suggestion table never
clobbers the line the customer paid, leave ``tip`` as ``None`` on a
receipt that genuinely has no gratuity line, and merge into an
``existing`` ReceiptFields without overwriting an LLM-provided value.
"""
from __future__ import annotations

from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract.receipt import enrich_receipt, parse_receipt_text


def _ocr(text: str) -> OCRResult:
    return OCRResult(text=text, language="eng", word_count=len(text.split()))


def test_tip_extracted_from_tip_line():
    text = "Acme Diner\nSubtotal 20.00\nTax 1.60\nTip 4.00\nTotal 25.60\n"
    parsed = parse_receipt_text(text)
    assert parsed.subtotal == 20.00
    assert parsed.tax == 1.60
    assert parsed.tip == 4.00
    assert parsed.total == 25.60


def test_tip_extracted_from_gratuity_line():
    text = "Bistro\nSubtotal 30.00\nGratuity: 5.50\nTotal 35.50\n"
    parsed = parse_receipt_text(text)
    assert parsed.tip == 5.50


def test_tip_extracted_from_service_charge():
    text = "Cafe\nSubtotal 12.00\nService charge 1.20\nTotal 13.20\n"
    parsed = parse_receipt_text(text)
    assert parsed.tip == 1.20


def test_tip_none_when_absent():
    text = "Grocery\nSubtotal 9.00\nTax 0.75\nTotal 9.75\n"
    parsed = parse_receipt_text(text)
    assert parsed.tip is None


def test_tip_prefers_last_occurrence_over_suggestion_table():
    """A receipt that prints a suggestion table (Tip 15% = 3.00, Tip 20% = 4.00)
    above the actual paid tip should still extract the paid value.
    """
    text = (
        "Diner\nSubtotal 20.00\nTax 1.60\n"
        "Tip 15%: 3.00\nTip 20%: 4.00\n"
        "Tip 5.00\nTotal 26.60\n"
    )
    parsed = parse_receipt_text(text)
    # _find_amount_after takes the LAST occurrence by design.
    assert parsed.tip == 5.00


def test_enrich_preserves_existing_tip():
    """An LLM-supplied tip survives enrichment even if the parser would
    have produced a different number."""
    text = "Diner\nSubtotal 20.00\nTip 4.00\nTotal 24.00\n"
    existing = ReceiptFields(vendor="Diner", tip=3.50)
    merged = enrich_receipt(existing, _ocr(text))
    assert merged.tip == 3.50  # not overwritten


def test_enrich_fills_in_missing_tip():
    text = "Diner\nSubtotal 20.00\nGratuity 6.00\nTotal 26.00\n"
    existing = ReceiptFields(vendor="Diner")  # no tip on the LLM side
    merged = enrich_receipt(existing, _ocr(text))
    assert merged.tip == 6.00


def test_tip_line_not_swallowed_into_items():
    """The items parser must skip tip / gratuity / service lines so the
    gratuity does not also appear as a $4.00 line item."""
    text = (
        "Diner\nBurger 12.00\nFries 3.00\nSubtotal 15.00\n"
        "Tax 1.20\nTip 4.00\nTotal 20.20\n"
    )
    parsed = parse_receipt_text(text)
    descriptions = [item.description.lower() for item in parsed.items]
    assert all("tip" not in d for d in descriptions)
    assert all("gratuity" not in d for d in descriptions)
