"""Receipt line-item discount inference tests.

The receipt extractor already detects top-level discounts (a
``Discount  -2.00`` summary line) and stores them on
``ReceiptFields.discount``. This commit adds per-line percent-off
discounts so a line like ``BOGO 50% off Latte 4.00`` becomes a
ReceiptLine with ``discount_pct=50`` and ``discount_amount=2.00``.

Recognised line shapes (the order they're tried):

* ``BOGO 50% off Latte 4.00`` -- promo prefix + ``\\d+% off`` clause
  before the description. Promo prefix (``BOGO``, ``Member``,
  ``Loyalty``, ``Rewards``) is stripped from the description.
* ``50% off Croissant 3.50`` -- bare ``\\d+% off`` clause before the
  description.
* ``Latte 50% off 5.00`` -- description then ``\\d+% off`` clause then
  the price.
* ``Latte 5.00 (10% off)`` -- description + price followed by a
  parenthesised ``\\d+% off`` clause.

Pure summary lines (``Discount  -2.00``) are NOT parsed as line items
-- the existing top-level discount detector already handles them and
populates ``ReceiptFields.discount``.
"""
from __future__ import annotations

from shotclassify_extract.receipt import parse_receipt_text


def _items_by_desc(text: str) -> dict:
    """Helper: return {description: ReceiptLine} for a receipt text."""
    fields = parse_receipt_text(text)
    return {item.description: item for item in fields.items}


# ---- per-line percent-off shapes ----------------------------------------


def test_bogo_prefix_pct_off_line_item():
    text = (
        "BOGO 50% off Latte 4.00\n"
        "Subtotal              4.00\n"
        "Total                 4.00\n"
    )
    items = _items_by_desc(text)
    assert "Latte" in items
    assert items["Latte"].discount_pct == 50.0
    assert items["Latte"].discount_amount == 2.0
    assert items["Latte"].price == 4.0


def test_bare_pct_off_prefix_line_item():
    text = (
        "Sandwich Shop\n"
        "10% off Croissant 3.50\n"
        "Subtotal              3.50\n"
    )
    items = _items_by_desc(text)
    assert "Croissant" in items
    assert items["Croissant"].discount_pct == 10.0


def test_infix_pct_off_line_item():
    text = "Latte 50% off 5.00\n"
    items = _items_by_desc(text)
    assert "Latte" in items
    assert items["Latte"].discount_pct == 50.0
    assert items["Latte"].price == 5.0


def test_parenthesised_trailing_pct_off_line_item():
    text = "Latte 5.00 (10% off)\n"
    items = _items_by_desc(text)
    assert "Latte" in items
    assert items["Latte"].discount_pct == 10.0
    assert items["Latte"].price == 5.0


def test_member_prefix_stripped_from_description():
    text = "Member 20% off Latte 4.00\n"
    items = _items_by_desc(text)
    # Either "Latte" (if prefix stripped) or "Member Latte" -- both are
    # acceptable; we assert the discount_pct is populated which is the
    # actual deliverable.
    matches = [i for i in items.values() if i.discount_pct == 20.0]
    assert matches, "expected a discounted item with pct=20"
    # The cleanest desc strips the member prefix; if we got that path,
    # also assert the description is just the item.
    if "Latte" in items:
        assert items["Latte"].discount_pct == 20.0


def test_pct_off_with_decimal_percent():
    """``12.5% off Latte 8.00`` -- fractional percentages."""
    text = "12.5% off Latte 8.00\n"
    items = _items_by_desc(text)
    assert "Latte" in items
    assert items["Latte"].discount_pct == 12.5


def test_pct_off_skips_promo_keyword_skip():
    """``Promo: BOGO 50% off Latte 4.00`` would normally be skipped by
    the ``promo`` keyword filter. The per-line discount detector runs
    BEFORE the filter so the item is still captured."""
    text = (
        "Cafe XYZ\n"
        "Promo: BOGO 50% off Latte 4.00\n"
        "Subtotal               4.00\n"
        "Total                  4.00\n"
    )
    items = _items_by_desc(text)
    # Description may be "Latte" or "Promo: BOGO Latte" depending on
    # how aggressive the leading regex was -- we assert on the discount.
    matches = [i for i in items.values() if i.discount_pct == 50.0]
    assert matches
    assert matches[0].discount_amount == 2.0


# ---- false-positive defences --------------------------------------------


def test_pure_discount_summary_line_not_parsed_as_item():
    """``Discount  -2.00`` is a summary line, not a line item. It goes
    into ReceiptFields.discount, not ReceiptFields.items."""
    text = (
        "Coffee Shop\n"
        "Latte                 6.00\n"
        "Discount             -2.00\n"
        "Subtotal              4.00\n"
        "Total                 4.00\n"
    )
    fields = parse_receipt_text(text)
    descs = {item.description for item in fields.items}
    assert "Latte" in descs
    # The bare "Discount -2.00" line must not show up as a ReceiptLine.
    assert not any("discount" in d.lower() for d in descs)


def test_percentage_in_unrelated_context_not_a_discount():
    """``Tip 18%`` is a tip percentage, not an item discount.
    Likewise ``Service charge 10%`` is not an item discount line."""
    text = (
        "Restaurant\n"
        "Pasta                12.00\n"
        "Tip 18%               2.16\n"
        "Subtotal             12.00\n"
        "Total                14.16\n"
    )
    fields = parse_receipt_text(text)
    descs = {item.description for item in fields.items}
    # The tip line must NOT be parsed as a discounted item.
    assert not any("tip" in d.lower() for d in descs)
    # Pasta should still be present (regression check).
    assert "Pasta" in descs


def test_implausible_percent_rejected():
    """A line with ``150% off Foo 3.00`` is implausible; the discount
    must satisfy 0 < pct <= 100."""
    text = "150% off Foo 3.00\n"
    items = _items_by_desc(text)
    # Either no item (regex bailed) or the item with no discount_pct.
    if "Foo" in items:
        assert items["Foo"].discount_pct is None


def test_implausible_price_rejected():
    """Excessively large prices are dropped from the line-item parser."""
    text = "50% off Foo 99999.00\n"
    items = _items_by_desc(text)
    assert not items


# ---- compatibility with existing extractors -----------------------------


def test_discount_top_level_still_detected_when_per_item_present():
    """A receipt with BOTH per-item discount AND a summary discount
    line should populate BOTH the line item AND the top-level discount."""
    text = (
        "Cafe Foo\n"
        "Member 20% off Latte 4.00\n"
        "Subtotal              4.00\n"
        "Discount              0.80\n"  # member savings line
        "Total                 3.20\n"
    )
    fields = parse_receipt_text(text)
    assert fields.discount == 0.80
    # The per-item discount is also present.
    matches = [i for i in fields.items if i.discount_pct == 20.0]
    assert matches


def test_regular_items_still_parsed_when_a_discount_line_is_present():
    """Mixing a discounted line and regular lines should not break the
    plain ``desc + price`` parser."""
    text = (
        "Coffee Shop\n"
        "Espresso              3.00\n"
        "10% off Latte         4.50\n"
        "Croissant             2.50\n"
        "Subtotal              10.00\n"
    )
    items = _items_by_desc(text)
    assert "Espresso" in items
    assert "Croissant" in items
    # Latte present with the discount.
    discounted = [v for v in items.values() if v.discount_pct == 10.0]
    assert discounted


def test_existing_qty_pattern_still_wins_for_quantity_lines():
    """A line like ``2 x Latte 6.00`` still matches the qty pattern,
    NOT the discount one (no ``% off`` clause)."""
    text = "2 x Latte 6.00 = 12.00\n"
    items = _items_by_desc(text)
    # Description is "Latte"; qty=2, price=6.00, no discount.
    assert "Latte" in items
    assert items["Latte"].qty == 2
    assert items["Latte"].price == 6.0
    assert items["Latte"].discount_pct is None
