"""Receipt line-item modifier / customisation extraction tests.

Restaurant POS systems print add-ons / removes / substitutions on
indented lines beneath the item they belong to:

  Burger                12.00
    + Add bacon          2.00
    + Extra cheese       1.50
    - No onions
    * Substitute fries
  Latte                  5.00
    + Oat milk           0.75

The new ``ReceiptLine.modifiers`` slot captures each modifier line
as a ``{"kind", "text", "price"}`` dict where ``kind`` is one of
``add`` / ``remove`` / ``sub`` / ``note``.
"""
from __future__ import annotations

from shotclassify_common import ReceiptLine
from shotclassify_extract.receipt import _parse_modifier_line, parse_receipt_text

# ---- Sigil-prefix forms -------------------------------------


def test_add_sigil_with_price():
    text = "Burger 12.00\n  + Add bacon 2.00"
    fields = parse_receipt_text(text)
    assert len(fields.items) == 1
    assert fields.items[0].description == "Burger"
    assert len(fields.items[0].modifiers) == 1
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "add"
    assert mod["text"] == "Add bacon"
    assert mod["price"] == 2.00


def test_add_sigil_without_price():
    text = "Burger 12.00\n  + Extra cheese"
    fields = parse_receipt_text(text)
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "add"
    assert mod["text"] == "Extra cheese"
    assert mod["price"] is None


def test_remove_sigil():
    text = "Burger 12.00\n  - No onions"
    fields = parse_receipt_text(text)
    assert len(fields.items[0].modifiers) == 1
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "remove"
    assert mod["text"] == "No onions"
    assert mod["price"] is None


def test_sub_sigil():
    text = "Burger 12.00\n  * Substitute fries"
    fields = parse_receipt_text(text)
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "sub"
    assert "Substitute fries" in mod["text"]


def test_sub_sigil_with_price():
    text = "Burger 12.00\n  * Substitute sweet potato fries 1.50"
    fields = parse_receipt_text(text)
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "sub"
    assert mod["price"] == 1.50


# ---- Word-prefix forms (only when indented) -----------------


def test_add_word_indented():
    text = "Burger 12.00\n  Add bacon 2.00"
    fields = parse_receipt_text(text)
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "add"
    assert mod["text"] == "bacon"
    assert mod["price"] == 2.00


def test_extra_word_indented():
    text = "Burger 12.00\n  Extra cheese 1.50"
    fields = parse_receipt_text(text)
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "add"
    assert mod["price"] == 1.50


def test_with_word_indented():
    text = "Burger 12.00\n  With pickles"
    fields = parse_receipt_text(text)
    assert len(fields.items[0].modifiers) >= 1
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "add"


def test_no_word_indented():
    text = "Burger 12.00\n  No onions"
    fields = parse_receipt_text(text)
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "remove"
    assert "onions" in mod["text"].lower()


def test_without_word_indented():
    text = "Burger 12.00\n  Without mayo"
    fields = parse_receipt_text(text)
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "remove"


def test_hold_word_indented():
    text = "Burger 12.00\n  Hold the mayo"
    fields = parse_receipt_text(text)
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "remove"


def test_omit_word_indented():
    text = "Burger 12.00\n  Omit cheese"
    fields = parse_receipt_text(text)
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "remove"


def test_sub_word_indented():
    text = "Burger 12.00\n  Sub side salad"
    fields = parse_receipt_text(text)
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "sub"
    assert "side salad" in mod["text"]


def test_swap_word_indented():
    text = "Burger 12.00\n  Swap fries for salad"
    fields = parse_receipt_text(text)
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "sub"


# ---- Word-prefix without indentation -- NOT a modifier ------


def test_no_indent_word_not_modifier():
    # "Add bacon" without indent should be treated as a regular
    # item description -- not as a modifier on the previous item.
    text = "Burger 12.00\nAdd bacon 2.00"
    fields = parse_receipt_text(text)
    # "Add bacon" is treated as a fresh item OR a no-price modifier
    # candidate. In our implementation, the bare word-prefix without
    # indentation is rejected, so we expect two items.
    # When the modifier-with-price detection fires for the second
    # line, it sees an indented=False and falls through to bare item.
    # Verify Burger has zero modifiers and "Add bacon" is its own item.
    burger = next(i for i in fields.items if i.description == "Burger")
    assert burger.modifiers == []


def test_no_indent_no_word_treated_as_item():
    text = "Burger 12.00\nNo soup 5.00"
    fields = parse_receipt_text(text)
    burger = next(i for i in fields.items if i.description == "Burger")
    assert burger.modifiers == []


# ---- Note kind (bare indented text) -------------------------


def test_bare_indented_text_is_note():
    text = "Steak 25.00\n  Well done"
    fields = parse_receipt_text(text)
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "note"
    assert mod["text"] == "Well done"


def test_bare_text_with_price_is_not_note():
    # Lines with a price tail go through the item parser, not modifier.
    text = "Steak 25.00\n  Wine 8.00"
    fields = parse_receipt_text(text)
    # The "Wine 8.00" line has a price so it parses as an item.
    descriptions = {i.description for i in fields.items}
    assert "Wine" in descriptions


def test_note_with_indented_internal_punctuation():
    text = "Steak 25.00\n  Cut in halves, please"
    fields = parse_receipt_text(text)
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "note"
    assert "Cut in halves" in mod["text"]


# ---- Multiple modifiers per item ----------------------------


def test_multiple_modifiers_per_item():
    text = """Burger 12.00
  + Add bacon 2.00
  + Extra cheese 1.50
  - No onions"""
    fields = parse_receipt_text(text)
    assert len(fields.items[0].modifiers) == 3
    kinds = [m["kind"] for m in fields.items[0].modifiers]
    assert kinds == ["add", "add", "remove"]


def test_modifiers_first_seen_order_preserved():
    text = """Burger 12.00
  - No onions
  + Extra cheese
  * Substitute fries"""
    fields = parse_receipt_text(text)
    kinds = [m["kind"] for m in fields.items[0].modifiers]
    assert kinds == ["remove", "add", "sub"]


def test_modifiers_attach_to_most_recent_item():
    text = """Burger 12.00
  + Add bacon 2.00
Latte 5.00
  + Oat milk 0.75"""
    fields = parse_receipt_text(text)
    burger = next(i for i in fields.items if i.description == "Burger")
    latte = next(i for i in fields.items if i.description == "Latte")
    assert len(burger.modifiers) == 1
    assert burger.modifiers[0]["text"] == "Add bacon"
    assert len(latte.modifiers) == 1
    assert latte.modifiers[0]["text"] == "Oat milk"


def test_modifier_cap_at_10():
    lines = ["Burger 12.00"]
    for i in range(15):
        lines.append(f"  + Extra topping {i}")
    text = "\n".join(lines)
    fields = parse_receipt_text(text)
    assert len(fields.items[0].modifiers) == 10


# ---- Items without modifiers --------------------------------


def test_items_without_modifiers_have_empty_list():
    text = "Burger 12.00\nLatte 5.00"
    fields = parse_receipt_text(text)
    for item in fields.items:
        assert item.modifiers == []


def test_no_first_item_means_no_modifier_attached():
    # A modifier-shaped line at the top with no preceding item just
    # gets dropped (nothing to attach to).
    text = """  + Add bacon 2.00
Burger 12.00"""
    fields = parse_receipt_text(text)
    # The "+ Add bacon 2.00" line has no preceding item to attach to,
    # so it's dropped. Burger has no modifiers.
    burger = next((i for i in fields.items if i.description == "Burger"), None)
    assert burger is not None
    assert burger.modifiers == []


# ---- _parse_modifier_line directly --------------------------


def test_parse_modifier_add_sigil_direct():
    result = _parse_modifier_line("+ Bacon 2.00", indented=False)
    assert result == {"kind": "add", "text": "Bacon", "price": 2.00}


def test_parse_modifier_remove_sigil_direct():
    result = _parse_modifier_line("- No onions", indented=False)
    assert result == {"kind": "remove", "text": "No onions", "price": None}


def test_parse_modifier_sub_sigil_direct():
    result = _parse_modifier_line("* Substitute fries", indented=False)
    assert result == {"kind": "sub", "text": "Substitute fries", "price": None}


def test_parse_modifier_word_form_requires_indent():
    # Not indented -> bare word form is rejected.
    result = _parse_modifier_line("Add bacon", indented=False)
    assert result is None
    # Indented -> word form fires.
    result = _parse_modifier_line("Add bacon", indented=True)
    assert result == {"kind": "add", "text": "bacon", "price": None}


def test_parse_modifier_empty_text_rejected():
    assert _parse_modifier_line("", indented=True) is None
    assert _parse_modifier_line("   ", indented=True) is None


def test_parse_modifier_overly_long_text_rejected():
    long_text = "a" * 200
    result = _parse_modifier_line(long_text, indented=True)
    assert result is None


def test_parse_modifier_with_price_tail_not_note():
    # "Wine 8.00" looks like a regular item, not a modifier note.
    result = _parse_modifier_line("Wine 8.00", indented=True)
    assert result is None


# ---- Realistic restaurant receipt ---------------------------


def test_realistic_restaurant_receipt():
    text = """ACME BURGERS
==========================
Table 4
Server: Bob

Cheeseburger              12.00
  + Add bacon              2.00
  + Extra cheese           1.50
  - No onions
  - Hold pickles
French Fries               5.00
Coke                       2.50
  + Add ice
Strawberry Shake           6.50
  + Whipped cream          0.50
  * Substitute almond milk 1.00

Subtotal                  29.50
Tax                        2.65
Tip                        5.00
Total                     37.15"""
    fields = parse_receipt_text(text)
    # 4 items: Cheeseburger, French Fries, Coke, Strawberry Shake.
    item_names = [i.description for i in fields.items]
    assert "Cheeseburger" in item_names
    assert "French Fries" in item_names
    assert "Coke" in item_names
    assert "Strawberry Shake" in item_names

    cheeseburger = next(i for i in fields.items if i.description == "Cheeseburger")
    # bacon + extra cheese + no onions + hold pickles = 4 modifiers
    assert len(cheeseburger.modifiers) == 4

    coke = next(i for i in fields.items if i.description == "Coke")
    assert len(coke.modifiers) == 1
    assert coke.modifiers[0]["kind"] == "add"

    shake = next(i for i in fields.items if i.description == "Strawberry Shake")
    assert len(shake.modifiers) == 2
    sub_mods = [m for m in shake.modifiers if m["kind"] == "sub"]
    assert len(sub_mods) == 1


# ---- Coffee shop receipt ------------------------------------


def test_coffee_shop_customisations():
    text = """Cafe Mocha
============
Latte Grande              5.50
  + Oat milk              0.75
  + Vanilla syrup         0.50
  + Extra shot            1.00

Cappuccino Small          4.00
  No foam

Total                    11.75"""
    fields = parse_receipt_text(text)
    latte = next(i for i in fields.items if "Latte" in i.description)
    cappuccino = next(i for i in fields.items if "Cappuccino" in i.description)
    assert len(latte.modifiers) == 3
    assert all(m["kind"] == "add" for m in latte.modifiers)
    assert len(cappuccino.modifiers) == 1
    assert cappuccino.modifiers[0]["kind"] == "remove"


# ---- Tab-indented lines (for OCR captures with tabs) --------


def test_tab_indented_modifier():
    text = "Burger 12.00\n\t+ Bacon 2.00"
    fields = parse_receipt_text(text)
    assert len(fields.items[0].modifiers) == 1
    assert fields.items[0].modifiers[0]["kind"] == "add"


def test_tab_indented_word_form():
    text = "Burger 12.00\n\tAdd bacon 2.00"
    fields = parse_receipt_text(text)
    assert len(fields.items[0].modifiers) == 1


# ---- Negative regression: percent-off discount ---------------


def test_no_modifier_interference_with_percent_off():
    text = """Burger 12.00
50% off Latte 4.00"""
    fields = parse_receipt_text(text)
    descriptions = [i.description for i in fields.items]
    # Both should be items, not modifiers.
    assert any("Burger" in d for d in descriptions)
    assert any("Latte" in d for d in descriptions)


# ---- Negative regression: SKU-only lines --------------------


def test_no_modifier_interference_with_sku_line():
    text = """Latte 5.00
  SKU: 12345"""
    fields = parse_receipt_text(text)
    latte = fields.items[0]
    assert latte.sku == "12345"
    # The SKU-only line should NOT also be picked up as a modifier.
    assert latte.modifiers == []


# ---- Edge cases ---------------------------------------------


def test_minus_followed_by_digit_not_remove():
    # "- 5.00" looks like a negative number, not a modifier.
    # The _MOD_REMOVE_PREFIX_RE explicitly excludes this case.
    result = _parse_modifier_line("- 5.00", indented=True)
    # Should fall through to note OR be rejected. The price-tail
    # rejection catches it.
    assert result is None or result["kind"] == "note"


def test_special_characters_in_text():
    text = "Burger 12.00\n  + Add ham & cheese 2.00"
    fields = parse_receipt_text(text)
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "add"
    assert "ham" in mod["text"]
    assert mod["price"] == 2.00


def test_unicode_text_preserved():
    text = "Croissant 4.00\n  + Beurre supplémentaire"
    fields = parse_receipt_text(text)
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "add"
    assert "supplémentaire" in mod["text"]


# ---- ReceiptLine field default ------------------------------


def test_receipt_line_modifiers_defaults_to_empty():
    item = ReceiptLine(description="Burger")
    assert item.modifiers == []


def test_receipt_line_with_modifiers_field():
    item = ReceiptLine(
        description="Burger",
        price=12.00,
        modifiers=[
            {"kind": "add", "text": "Bacon", "price": 2.00},
            {"kind": "remove", "text": "No onions", "price": None},
        ],
    )
    assert len(item.modifiers) == 2


# ---- LLM wire format ----------------------------------------


def test_llm_wire_format_modifiers():
    from shotclassify_classify.client import _parse_llm_payload
    payload = {
        "primary": "receipt",
        "confidences": [],
        "rationale": "",
        "fields": {
            "receipt": {
                "items": [
                    {
                        "description": "Burger",
                        "price": 12.00,
                        "modifiers": [
                            {"kind": "add", "text": "Bacon", "price": 2.00},
                        ],
                    }
                ]
            }
        },
    }
    _, fields = _parse_llm_payload(payload)
    assert fields.receipt is not None
    assert len(fields.receipt.items) == 1
    assert len(fields.receipt.items[0].modifiers) == 1
    assert fields.receipt.items[0].modifiers[0]["kind"] == "add"


# ---- Less keyword for removes -------------------------------


def test_less_word_for_remove():
    text = "Burger 12.00\n  Less mayo"
    fields = parse_receipt_text(text)
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "remove"
    assert "mayo" in mod["text"].lower()


# ---- Replace keyword for sub --------------------------------


def test_replace_word_for_sub():
    text = "Burger 12.00\n  Replace fries with salad"
    fields = parse_receipt_text(text)
    mod = fields.items[0].modifiers[0]
    assert mod["kind"] == "sub"


# ---- Realistic order ticket ---------------------------------


def test_pos_ticket_simulation():
    text = """ITEM                     PRICE
------------------------------
Whopper                   8.99
  + Extra Patty           1.50
  - No Pickles
  - No Lettuce
  + Bacon                 2.00
Fries Large               3.99
Drink Large               2.99
  + Ice"""
    fields = parse_receipt_text(text)
    whopper = next(i for i in fields.items if i.description == "Whopper")
    assert len(whopper.modifiers) == 4
    add_count = sum(1 for m in whopper.modifiers if m["kind"] == "add")
    remove_count = sum(1 for m in whopper.modifiers if m["kind"] == "remove")
    assert add_count == 2
    assert remove_count == 2
