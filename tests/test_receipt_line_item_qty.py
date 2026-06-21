"""Receipt line-item quantity inference.

Most receipts print multi-unit items in one of two shapes:

  * Quantity-prefixed: ``2 x Latte 6.00 = 12.00``
  * Trailing @-form:   ``Latte 2 @ 6.00``

The original `_parse_items` collapsed both into a single ReceiptLine
with qty=None, losing the quantity signal that downstream dashboards
need to compute per-item metrics. This version extracts ``qty`` and
``price`` (the unit price; the caller can multiply for the extended
total) without disturbing the bare ``desc price`` path that already
handled the single-unit case.

Design notes:
* When both an extended total ("= 12.00") and a unit price ("6.00")
  are present, we record the UNIT price -- multiplying restores the
  extended total and matches how downstream code expects the field.
* Quantity matches require the qty to be > 0 and the unit price to be
  in the same ``0.01..9999`` range as the bare path. A garbage line
  like ``0 x Latte 6.00`` falls through to the bare regex.
"""
from __future__ import annotations

from shotclassify_extract.receipt import parse_receipt_text


def _items(text: str):
    return parse_receipt_text(text).items


def test_x_prefixed_qty_with_extended_total():
    text = "Cafe\n2 x Latte 6.00 = 12.00\nSubtotal 12.00\nTotal 12.00\n"
    items = _items(text)
    assert len(items) == 1
    assert items[0].description == "Latte"
    assert items[0].qty == 2.0
    assert items[0].price == 6.00


def test_x_prefixed_qty_without_extended_total():
    """Most printers omit the ``= ext`` -- still extract qty + unit."""
    text = "Cafe\n3 x Espresso 3.50\nSubtotal 10.50\nTotal 10.50\n"
    items = _items(text)
    assert len(items) == 1
    assert items[0].description == "Espresso"
    assert items[0].qty == 3.0
    assert items[0].price == 3.50


def test_capital_x_separator():
    text = "Cafe\n4 X Donut 1.25\nSubtotal 5.00\nTotal 5.00\n"
    items = _items(text)
    assert items[0].qty == 4.0
    assert items[0].description == "Donut"


def test_asterisk_separator():
    """Some POS printers use ``*`` instead of ``x``."""
    text = "Cafe\n2 * Croissant 3.00\nSubtotal 6.00\nTotal 6.00\n"
    items = _items(text)
    assert items[0].qty == 2.0
    assert items[0].description == "Croissant"
    assert items[0].price == 3.00


def test_at_form_after_description():
    text = "Cafe\nLatte 2 @ 6.00\nSubtotal 12.00\nTotal 12.00\n"
    items = _items(text)
    assert items[0].description == "Latte"
    assert items[0].qty == 2.0
    assert items[0].price == 6.00


def test_at_form_with_currency_symbol():
    text = "Cafe\nLatte 2 @ $6.00\nSubtotal 12.00\nTotal 12.00\n"
    items = _items(text)
    assert items[0].description == "Latte"
    assert items[0].qty == 2.0
    assert items[0].price == 6.00


def test_bare_desc_price_still_works_without_qty():
    """Regression: single-unit items remain qty=None, price=<n>."""
    text = "Cafe\nLatte 6.00\nSubtotal 6.00\nTotal 6.00\n"
    items = _items(text)
    assert len(items) == 1
    assert items[0].qty is None
    assert items[0].price == 6.00


def test_qty_zero_falls_through_to_bare_path():
    """0 qty is suspicious -- the qty branch rejects it. The line still
    falls through to the bare ``desc price`` regex, which captures the
    second number (``6.00``) as the price; the description picks up
    everything before it ("0 x Latte"), which is at least somewhat
    discoverable in dashboards."""
    text = "Cafe\n0 x Latte 6.00\nSubtotal 0.00\nTotal 0.00\n"
    items = _items(text)
    assert len(items) == 1
    assert items[0].qty is None
    assert items[0].price == 6.00


def test_decimal_qty_supported():
    """Weighed items like produce print fractional quantities."""
    text = "Grocery\n1.5 x Apples 2.00\nSubtotal 3.00\nTotal 3.00\n"
    items = _items(text)
    assert items[0].qty == 1.5
    assert items[0].description == "Apples"
    assert items[0].price == 2.00


def test_multiple_items_mixed_qty_and_bare():
    text = (
        "Restaurant\n"
        "2 x Latte 6.00 = 12.00\n"
        "Sandwich 9.50\n"
        "3 x Cookie 1.50\n"
        "Subtotal 26.00\n"
        "Total 26.00\n"
    )
    items = _items(text)
    assert len(items) == 3
    descs = [i.description for i in items]
    assert descs == ["Latte", "Sandwich", "Cookie"]
    assert items[0].qty == 2.0 and items[0].price == 6.00
    assert items[1].qty is None and items[1].price == 9.50
    assert items[2].qty == 3.0 and items[2].price == 1.50


def test_qty_lines_are_not_misclassified_as_subtotal():
    """A line beginning with a number must still get the keyword
    rejection treatment for subtotal/tax/etc. (it doesn't currently,
    because qty regex only matches digit + x; but we add this here as
    a guard in case a future receipt prints `1 x Subtotal 10.00`)."""
    text = "Cafe\n1 x Subtotal 10.00\n"
    items = _items(text)
    # 'Subtotal' triggers the keyword skip BEFORE the qty regex runs,
    # so the line is dropped entirely.
    assert items == []


def test_comma_decimal_in_qty_or_price():
    """European receipts use ``,`` as the decimal separator."""
    text = "Cafe\n2 x Latte 6,00\nSubtotal 12,00\nTotal 12,00\n"
    items = _items(text)
    assert items[0].qty == 2.0
    assert items[0].price == 6.00


def test_qty_caps_at_30_items():
    """Pathological menu cannot balloon items past the existing cap."""
    lines = ["Cafe"] + [f"2 x Item{i} 1.00" for i in range(60)]
    lines += ["Subtotal 60.00", "Total 60.00"]
    items = _items("\n".join(lines) + "\n")
    assert len(items) == 30
