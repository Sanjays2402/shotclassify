"""Receipt service_charge / delivery_fee extraction.

Two new ``ReceiptFields`` slots split a couple of bills the original
``tip`` / ``discount`` parsing intentionally collapsed:

* ``service_charge`` -- the mandatory auto-gratuity / platform fee
  printed as "Service Charge" / "Service Fee" / "Svc Fee". Distinct
  from ``tip`` because the customer cannot opt out -- restaurants
  with parties of 6+ add it automatically, food-delivery apps charge
  a platform fee on top of order + tax.
* ``delivery_fee`` -- the delivery / shipping fee printed on
  off-premise receipts. Recognised on food-delivery (UberEats /
  DoorDash / Deliveroo / Grubhub), e-commerce (Amazon / Shopify),
  and grocery-delivery (Instacart). Multi-word forms ("Delivery
  Fee" / "Shipping & Handling") beat the bare "Delivery" /
  "Shipping" aliases.

The two CAN coexist with the existing ``tip`` field on the same
receipt (a restaurant prints both "Service Charge 5.00" mandatory
and "Tip 4.00" voluntary). Last-occurrence semantics so a "Service
Fee suggested" header above a real "Service Fee 5.00" line resolves
to the line the customer paid.
"""
from __future__ import annotations

from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract import enrich_receipt
from shotclassify_extract.receipt import (
    _find_delivery_fee,
    _find_service_charge,
    parse_receipt_text,
)

# ---- _find_service_charge ------------------------------------------


def test_service_charge_basic():
    assert _find_service_charge("Service Charge 5.00\n") == 5.00


def test_service_charge_fee_phrasing():
    assert _find_service_charge("Service Fee: 2.99\n") == 2.99


def test_service_charge_svc_abbreviation():
    assert _find_service_charge("Svc Charge 3.50\n") == 3.50


def test_service_charge_svc_fee_abbreviation():
    assert _find_service_charge("Svc Fee 1.50\n") == 1.50


def test_service_charge_case_insensitive():
    assert _find_service_charge("SERVICE CHARGE 7.50\n") == 7.50


def test_service_charge_with_currency_symbol():
    assert _find_service_charge("Service Fee $4.50\n") == 4.50


def test_service_charge_with_dash_separator():
    assert _find_service_charge("Service Charge - 6.25\n") == 6.25


def test_service_charge_last_occurrence_wins():
    """A "Service Fee suggested" header must not override the real line."""
    text = (
        "Service Fee may apply\n"
        "Service Fee suggested: 3.00\n"
        "Service Fee 5.00\n"
    )
    assert _find_service_charge(text) == 5.00


def test_service_charge_none_when_absent():
    assert _find_service_charge("Subtotal 12.00\nTotal 13.00\n") is None


def test_service_charge_none_on_bare_service_keyword():
    """Bare "Service" is intentionally kept in the tip catalogue and
    should NOT also fire the service_charge matcher -- otherwise a UK
    bar tab "Service 1.20" would double-count as both tip and
    service_charge."""
    assert _find_service_charge("Service 1.20\n") is None


def test_service_charge_decimal_comma():
    """European receipts use comma as the decimal separator."""
    assert _find_service_charge("Service Charge 4,50\n") == 4.50


def test_service_charge_does_not_eat_unrelated_amounts():
    text = "Subtotal 10.00\nTax 1.00\nService Charge 2.00\nTotal 13.00\n"
    assert _find_service_charge(text) == 2.00


# ---- _find_delivery_fee --------------------------------------------


def test_delivery_fee_basic():
    assert _find_delivery_fee("Delivery Fee 3.99\n") == 3.99


def test_delivery_fee_charge_phrasing():
    assert _find_delivery_fee("Delivery Charge: 4.50\n") == 4.50


def test_delivery_fee_bare_delivery_keyword():
    assert _find_delivery_fee("Delivery 2.99\n") == 2.99


def test_delivery_fee_shipping_keyword():
    assert _find_delivery_fee("Shipping 4.99\n") == 4.99


def test_delivery_fee_shipping_fee():
    assert _find_delivery_fee("Shipping Fee 5.99\n") == 5.99


def test_delivery_fee_shipping_and_handling():
    assert _find_delivery_fee("Shipping & Handling 7.95\n") == 7.95


def test_delivery_fee_shipping_and_handling_no_ampersand():
    assert _find_delivery_fee("Shipping and Handling 7.95\n") == 7.95


def test_delivery_fee_shipping_charge():
    assert _find_delivery_fee("Shipping Charge 8.00\n") == 8.00


def test_delivery_fee_shipping_cost():
    assert _find_delivery_fee("Shipping Cost 6.50\n") == 6.50


def test_delivery_fee_case_insensitive():
    assert _find_delivery_fee("DELIVERY FEE 3.99\n") == 3.99


def test_delivery_fee_with_currency_symbol():
    assert _find_delivery_fee("Delivery Fee $4.99\n") == 4.99


def test_delivery_fee_last_occurrence_wins():
    """A "Free shipping over $50" header must not steal the real line."""
    text = (
        "Free shipping over $50\n"
        "Shipping Fee 0.00\n"
        "Delivery Fee 4.99\n"
    )
    assert _find_delivery_fee(text) == 4.99


def test_delivery_fee_none_when_absent():
    assert _find_delivery_fee("Subtotal 12.00\nTotal 13.00\n") is None


def test_delivery_fee_decimal_comma():
    assert _find_delivery_fee("Delivery Fee 3,99\n") == 3.99


def test_delivery_fee_multiword_beats_bare():
    """"Delivery Fee 4.99" should be matched by the most-specific
    keyword first; ordering within the catalogue means the bare
    "Delivery" alias never fires on a line that already matched."""
    # Two distinct lines: bare "Delivery 1.00" earlier, "Delivery
    # Fee 4.99" later. Last-match-wins because both keywords land --
    # but it's the multi-word catalogue entry that wins on its own
    # line.
    text = "Delivery 1.00\nDelivery Fee 4.99\n"
    assert _find_delivery_fee(text) == 4.99


# ---- parse_receipt_text integration --------------------------------


def test_parse_receipt_with_service_charge_and_delivery_fee():
    text = (
        "Pho 1 12.00\n"
        "Subtotal 12.00\n"
        "Tax 1.20\n"
        "Service Charge 3.00\n"
        "Delivery Fee 4.99\n"
        "Total 21.19\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.service_charge == 3.00
    assert parsed.delivery_fee == 4.99
    assert parsed.total == 21.19


def test_parse_receipt_service_and_tip_coexist():
    """A restaurant receipt prints BOTH a mandatory service charge
    and a voluntary tip -- they should both populate distinct fields."""
    text = (
        "Subtotal 100.00\n"
        "Service Charge 18.00\n"
        "Tax 8.00\n"
        "Tip 10.00\n"
        "Total 136.00\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.service_charge == 18.00
    assert parsed.tip == 10.00


def test_parse_receipt_no_service_charge_no_delivery_fee():
    text = "Subtotal 12.00\nTax 1.00\nTotal 13.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.service_charge is None
    assert parsed.delivery_fee is None


def test_parse_receipt_ubereats_style():
    text = (
        "Burger 12.99\n"
        "Fries 4.99\n"
        "Subtotal 17.98\n"
        "Service Fee 2.99\n"
        "Delivery Fee 3.99\n"
        "Tax 1.80\n"
        "Tip 4.00\n"
        "Total 30.76\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.service_charge == 2.99
    assert parsed.delivery_fee == 3.99
    assert parsed.tip == 4.00


def test_parse_receipt_amazon_style():
    """E-commerce receipts: Shipping & Handling, no service charge."""
    text = (
        "Book 24.99\n"
        "Subtotal 24.99\n"
        "Shipping & Handling 4.99\n"
        "Tax 2.50\n"
        "Total 32.48\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.delivery_fee == 4.99
    assert parsed.service_charge is None


# ---- enrich_receipt: LLM-supplied values survive ----------------


def test_enrich_preserves_existing_service_charge():
    existing = ReceiptFields(vendor="Cafe", service_charge=3.50)
    ocr = OCRResult(text="Service Charge 5.00\n")
    merged = enrich_receipt(existing, ocr)
    assert merged.service_charge == 3.50  # not overwritten


def test_enrich_fills_in_missing_service_charge():
    existing = ReceiptFields(vendor="Cafe")
    ocr = OCRResult(text="Service Charge 5.00\n")
    merged = enrich_receipt(existing, ocr)
    assert merged.service_charge == 5.00


def test_enrich_preserves_existing_delivery_fee():
    existing = ReceiptFields(vendor="UberEats", delivery_fee=3.99)
    ocr = OCRResult(text="Delivery Fee 4.99\n")
    merged = enrich_receipt(existing, ocr)
    assert merged.delivery_fee == 3.99  # not overwritten


def test_enrich_fills_in_missing_delivery_fee():
    existing = ReceiptFields(vendor="UberEats")
    ocr = OCRResult(text="Delivery Fee 4.99\n")
    merged = enrich_receipt(existing, ocr)
    assert merged.delivery_fee == 4.99


def test_enrich_both_at_once():
    existing = ReceiptFields(vendor="DoorDash")
    ocr = OCRResult(text="Service Fee 2.99\nDelivery Fee 4.99\n")
    merged = enrich_receipt(existing, ocr)
    assert merged.service_charge == 2.99
    assert merged.delivery_fee == 4.99


def test_enrich_zero_value_treated_as_unset():
    """The merge helper treats 0 as "unset" for legacy reasons -- a
    parsed value from OCR should overwrite it."""
    existing = ReceiptFields(vendor="X", service_charge=0)
    ocr = OCRResult(text="Service Charge 5.00\n")
    merged = enrich_receipt(existing, ocr)
    assert merged.service_charge == 5.00
