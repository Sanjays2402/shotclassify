"""Per-line SKU / barcode / UPC / EAN extraction.

A new ``ReceiptLine.sku`` slot captures the stock-keeping unit /
barcode / UPC / EAN / item-code / PLU printed alongside the line
item on most retail receipts. Two common shapes:

* **Inline**: "Latte SKU: 12345 5.00" -- the SKU keyword + value
  sits between the description and the price on the same line.
  The cleaned line ("Latte 5.00") is fed to the per-item parser
  and the SKU is attached to the resulting ReceiptLine.
* **Standalone**: "SKU: 12345" on its own line, immediately under
  the item description. Attaches to the most-recent item already
  in the items list (mirrors how retail printers commonly print
  the SKU on the line below the item).

Recognised wording (case-insensitive, ordered most-specific first):

  SKU / Barcode / UPC / EAN / GTIN / PLU / Item Code / Item No. /
  Item # / Item Number

Value charset: alphanumerics + dashes / underscores / dots /
slashes, bounded 3..32 chars. Original case preserved on the value
because alphanumeric IDs are case-meaningful on many systems.
"""
from __future__ import annotations

from shotclassify_common import OCRResult
from shotclassify_extract import enrich_receipt
from shotclassify_extract.receipt import (
    _extract_sku_from_line,
    _parse_items,
)

# ---- _extract_sku_from_line: bare SKU keyword + value --------------


def test_sku_colon_basic():
    assert _extract_sku_from_line("SKU: 1234567") == ("1234567", "")


def test_sku_space_only():
    assert _extract_sku_from_line("SKU 1234567") == ("1234567", "")


def test_sku_no_separator():
    """A printer that omits the colon entirely ("SKU1234567") should
    still match -- the regex permits the bare keyword + value with
    no separator between."""
    assert _extract_sku_from_line("SKU1234567") == ("1234567", "")


def test_sku_lowercase():
    assert _extract_sku_from_line("sku: 12345") == ("12345", "")


def test_sku_with_dash_in_value():
    assert _extract_sku_from_line("SKU: ABC-12345") == ("ABC-12345", "")


def test_sku_with_dots_in_value():
    assert _extract_sku_from_line("SKU: A.B.C.123") == ("A.B.C.123", "")


def test_sku_preserves_case():
    assert _extract_sku_from_line("SKU: ABC-12345-xyz") == (
        "ABC-12345-xyz", "",
    )


def test_barcode_form():
    assert _extract_sku_from_line("Barcode: 0123456789012") == (
        "0123456789012", "",
    )


def test_barcode_no_colon():
    assert _extract_sku_from_line("Barcode 0123456789012") == (
        "0123456789012", "",
    )


def test_upc_form():
    assert _extract_sku_from_line("UPC: 042100005264") == (
        "042100005264", "",
    )


def test_ean_form():
    assert _extract_sku_from_line("EAN: 5012345678900") == (
        "5012345678900", "",
    )


def test_gtin_form():
    assert _extract_sku_from_line("GTIN: 12345678901234") == (
        "12345678901234", "",
    )


def test_plu_form():
    assert _extract_sku_from_line("PLU: 4011") == ("4011", "")


def test_item_code_form():
    assert _extract_sku_from_line("Item Code: ABC-12345") == (
        "ABC-12345", "",
    )


def test_item_hash_form():
    assert _extract_sku_from_line("Item #ABC-12345") == (
        "ABC-12345", "",
    )


def test_item_no_form():
    assert _extract_sku_from_line("Item No. ABC-99") == ("ABC-99", "")


def test_item_no_dot_form():
    assert _extract_sku_from_line("Item No: ABC-99") == ("ABC-99", "")


def test_item_number_form():
    assert _extract_sku_from_line("Item Number: 12345") == ("12345", "")


def test_sku_no_match_returns_none_and_original_line():
    assert _extract_sku_from_line("Bread 3.50") == (None, "Bread 3.50")


def test_sku_empty_line():
    assert _extract_sku_from_line("") == (None, "")


def test_sku_too_short_rejected():
    """A 1- or 2-char "SKU" value is below the 3-char minimum."""
    out = _extract_sku_from_line("SKU: A1")
    assert out == (None, "SKU: A1")


def test_sku_word_boundary_left():
    """A 'SKU' substring inside another word ('CKUS-SKU') must NOT
    misfire -- the left-side lookbehind is alpha-blocking."""
    out = _extract_sku_from_line("askedSKU: 12345")
    # The alpha-letter immediately before "sku" blocks the match.
    assert out == (None, "askedSKU: 12345")


# ---- _extract_sku_from_line: SKU embedded in item line -------------


def test_sku_embedded_strips_keyword():
    assert _extract_sku_from_line("Latte SKU: 12345 5.00") == (
        "12345", "Latte 5.00",
    )


def test_sku_embedded_no_separator():
    assert _extract_sku_from_line("Latte UPC042100005264 5.00") == (
        "042100005264", "Latte 5.00",
    )


def test_sku_embedded_collapses_whitespace():
    """Removing the SKU substring leaves a double-space; we collapse
    it to a single space so the per-item parser re-parses cleanly."""
    assert _extract_sku_from_line("Bread   SKU: 999   3.50") == (
        "999", "Bread 3.50",
    )


def test_sku_first_match_wins_on_multiple_keywords():
    """If a line has both 'SKU: X' and 'Barcode: Y' the FIRST match
    is the one that wins -- per-item SKUs are normally printed
    exactly once per line."""
    sku, cleaned = _extract_sku_from_line("Latte SKU: 12345 Barcode: 0123456789 5.00")
    assert sku == "12345"
    # The barcode keyword + value stays in the cleaned line because
    # we only strip the first match.
    assert "Barcode" in cleaned


# ---- _parse_items integration: inline SKU --------------------------


def test_parse_items_with_inline_sku():
    items = _parse_items("Latte SKU: 12345 5.00\n")
    assert len(items) == 1
    assert items[0].description == "Latte"
    assert items[0].price == 5.00
    assert items[0].sku == "12345"


def test_parse_items_with_inline_barcode():
    items = _parse_items("Bread Barcode: 0123456789012 3.50\n")
    assert len(items) == 1
    assert items[0].description == "Bread"
    assert items[0].price == 3.50
    assert items[0].sku == "0123456789012"


def test_parse_items_with_inline_qty_and_sku():
    items = _parse_items("2 x Latte SKU: 12345 6.00\n")
    assert len(items) == 1
    assert items[0].description == "Latte"
    assert items[0].qty == 2
    assert items[0].price == 6.00
    assert items[0].sku == "12345"


def test_parse_items_with_at_form_and_sku():
    items = _parse_items("Latte SKU: 12345 2 @ 6.00\n")
    assert len(items) == 1
    assert items[0].description == "Latte"
    assert items[0].qty == 2
    assert items[0].price == 6.00
    assert items[0].sku == "12345"


def test_parse_items_with_pct_off_and_sku():
    items = _parse_items("BOGO 50% off Latte SKU: 12345 4.00\n")
    assert len(items) == 1
    assert items[0].description == "Latte"
    assert items[0].discount_pct == 50.0
    assert items[0].sku == "12345"


# ---- _parse_items integration: standalone SKU line -----------------


def test_parse_items_standalone_sku_attaches_to_previous_item():
    """A SKU-only line ("SKU: 12345" on its own) attaches to the
    LAST item already parsed -- common pattern on retail printers
    that print the SKU on the line below the item description."""
    items = _parse_items(
        "Latte 5.00\n"
        "SKU: 12345\n"
    )
    assert len(items) == 1
    assert items[0].description == "Latte"
    assert items[0].price == 5.00
    assert items[0].sku == "12345"


def test_parse_items_standalone_sku_multiple_items():
    items = _parse_items(
        "Latte 5.00\n"
        "SKU: 12345\n"
        "Bread 3.50\n"
        "SKU: 99999\n"
    )
    assert len(items) == 2
    assert items[0].description == "Latte"
    assert items[0].sku == "12345"
    assert items[1].description == "Bread"
    assert items[1].sku == "99999"


def test_parse_items_standalone_sku_with_no_prior_item():
    """A SKU line at the very top with no item to attach to is
    silently dropped (not a crash)."""
    items = _parse_items(
        "SKU: 12345\n"
        "Latte 5.00\n"
    )
    assert len(items) == 1
    assert items[0].description == "Latte"
    # No SKU attached because the SKU line had no prior item.
    assert items[0].sku is None


def test_parse_items_standalone_upc_after_item():
    items = _parse_items(
        "Bread 3.50\n"
        "UPC 042100005264\n"
    )
    assert len(items) == 1
    assert items[0].sku == "042100005264"


def test_parse_items_standalone_plu_after_item():
    items = _parse_items(
        "Banana 1.20\n"
        "PLU 4011\n"
    )
    assert len(items) == 1
    assert items[0].sku == "4011"


# ---- _parse_items: backward compatibility --------------------------


def test_parse_items_no_sku_field_stays_none():
    """A receipt with no SKU keywords should leave every item's sku
    field at None (backward compatibility)."""
    items = _parse_items(
        "Latte 5.00\n"
        "Bread 3.50\n"
    )
    assert len(items) == 2
    assert items[0].sku is None
    assert items[1].sku is None


def test_parse_items_no_sku_in_qty_form():
    items = _parse_items("2 x Latte 6.00 = 12.00\n")
    assert len(items) == 1
    assert items[0].sku is None


# ---- enrich_receipt: LLM-supplied SKU survives ----------------


def test_enrich_preserves_existing_item_sku():
    """An item supplied by the LLM with sku=ABC should NOT be
    overwritten by the OCR pass."""
    from shotclassify_common import ReceiptFields, ReceiptLine
    existing = ReceiptFields(
        vendor="Cafe",
        items=[ReceiptLine(description="Latte", price=5.00, sku="ABC")],
    )
    ocr = OCRResult(text="Latte SKU: XYZ 5.00\n")
    merged = enrich_receipt(existing, ocr)
    # Existing items list is preserved verbatim (the merge logic
    # only fills items if existing.items is empty).
    assert merged.items[0].sku == "ABC"


def test_enrich_fills_in_items_with_sku_from_ocr():
    from shotclassify_common import ReceiptFields
    existing = ReceiptFields(vendor="Cafe")  # no items
    ocr = OCRResult(text="Latte SKU: 12345 5.00\nBread 3.50\nSKU: 99999\n")
    merged = enrich_receipt(existing, ocr)
    assert merged.items[0].sku == "12345"
    assert merged.items[1].sku == "99999"
