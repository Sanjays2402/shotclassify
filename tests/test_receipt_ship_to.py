"""Ship-To address-block extraction tests.

ReceiptFields.ship_to captures the customer-shipping address block
on e-commerce / shipping receipts (Amazon, Shopify, eBay, Etsy,
Square Online). Stored as a dict with name / lines / city / state /
postal_code / country.
"""
from __future__ import annotations

from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract.receipt import _find_ship_to, enrich_receipt


def test_empty_text():
    assert _find_ship_to("") is None


def test_none_text():
    assert _find_ship_to(None) is None  # type: ignore[arg-type]


def test_no_header_returns_none():
    """A receipt with NO Ship To: header returns None even with addresses."""
    text = "Some receipt\n123 Main St\nSpringfield, IL 62704\n"
    assert _find_ship_to(text) is None


def test_dine_in_restaurant_receipt_no_ship_to():
    text = (
        "Joe's Diner\n"
        "Table 4\n"
        "Burger 12.00\n"
        "Total 12.00\n"
    )
    assert _find_ship_to(text) is None


# ---- Basic Ship To header forms -----------------------------------


def test_basic_ship_to_us():
    text = (
        "Ship To:\n"
        "Alice Smith\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
        "United States\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["name"] == "Alice Smith"
    assert out["lines"] == [
        "123 Main St",
        "Springfield, IL 62704",
        "United States",
    ]
    assert out["city"] == "Springfield"
    assert out["state"] == "IL"
    assert out["postal_code"] == "62704"
    assert out["country"] == "United States"


def test_ship_to_no_country():
    text = (
        "Ship To:\n"
        "Alice Smith\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["country"] is None
    assert out["city"] == "Springfield"


def test_ship_to_with_apt():
    text = (
        "Ship To:\n"
        "Alice Smith\n"
        "123 Main St\n"
        "Apt 4B\n"
        "Springfield, IL 62704\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["lines"] == [
        "123 Main St",
        "Apt 4B",
        "Springfield, IL 62704",
    ]


def test_ship_to_zip_plus_4():
    text = (
        "Ship To:\n"
        "Alice Smith\n"
        "123 Main St\n"
        "Springfield, IL 62704-1234\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["postal_code"] == "62704-1234"


# ---- Header variations -------------------------------------------


def test_shipping_address_header():
    text = (
        "Shipping Address:\n"
        "Bob Jones\n"
        "221B Baker Street\n"
        "London NW1 6XE\n"
        "United Kingdom\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["name"] == "Bob Jones"
    assert out["country"] == "United Kingdom"


def test_shipped_to_header():
    text = (
        "Shipped To:\n"
        "Carol Adams\n"
        "10 Park Ave\n"
        "New York, NY 10001\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["name"] == "Carol Adams"


def test_deliver_to_header():
    text = (
        "Deliver To:\n"
        "Dave White\n"
        "555 Oak Rd\n"
        "Austin, TX 78701\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["name"] == "Dave White"


def test_delivery_address_header():
    text = (
        "Delivery Address:\n"
        "Eve Black\n"
        "1 Park Lane\n"
        "Boston, MA 02108\n"
    )
    out = _find_ship_to(text)
    assert out is not None


def test_recipient_header():
    text = (
        "Recipient:\n"
        "Frank Green\n"
        "200 Elm St\n"
        "Chicago, IL 60601\n"
    )
    out = _find_ship_to(text)
    assert out is not None


def test_mail_to_header():
    text = (
        "Mail To:\n"
        "Grace Hall\n"
        "100 Pine Ave\n"
        "Seattle, WA 98101\n"
    )
    out = _find_ship_to(text)
    assert out is not None


def test_lowercase_header():
    text = (
        "ship to:\n"
        "Alice Smith\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
    )
    out = _find_ship_to(text)
    assert out is not None


def test_uppercase_header():
    text = (
        "SHIP TO:\n"
        "Alice Smith\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
    )
    out = _find_ship_to(text)
    assert out is not None


def test_header_with_dash():
    text = (
        "Ship To-\n"
        "Alice Smith\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
    )
    out = _find_ship_to(text)
    assert out is not None


# ---- International postal-tail shapes ----------------------------


def test_uk_postcode_full():
    text = (
        "Ship To:\n"
        "Bob Jones\n"
        "221B Baker Street\n"
        "London NW1 6XE\n"
        "United Kingdom\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["city"] == "London"
    assert out["postal_code"] == "NW1 6XE"


def test_uk_postcode_short():
    text = (
        "Ship To:\n"
        "Bob Jones\n"
        "10 High St\n"
        "Manchester M1 1AE\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["postal_code"] == "M1 1AE"


def test_canadian_postal():
    text = (
        "Ship To:\n"
        "Alice Smith\n"
        "100 Yonge Street\n"
        "Toronto, ON M5C 2W1\n"
        "Canada\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["city"] == "Toronto"
    assert out["state"] == "ON"
    assert out["postal_code"] == "M5C 2W1"
    assert out["country"] == "Canada"


def test_australian_postal():
    text = (
        "Ship To:\n"
        "Helen Brown\n"
        "100 George St\n"
        "Sydney, 2000\n"
        "Australia\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["postal_code"] == "2000"
    assert out["country"] == "Australia"


def test_german_postal():
    text = (
        "Ship To:\n"
        "Ivan Karlsson\n"
        "Bismarckstrasse 12\n"
        "Berlin, 10625\n"
        "Germany\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["postal_code"] == "10625"
    assert out["country"] == "Germany"


# ---- Country catalogue --------------------------------------------


def test_country_usa_canonical():
    text = (
        "Ship To:\n"
        "Alice Smith\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
        "USA\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["country"] == "USA"


def test_country_dot_separated():
    text = (
        "Ship To:\n"
        "Alice Smith\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
        "U.S.A.\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["country"] == "U.S.A"  # trailing punctuation stripped


def test_country_brazil():
    text = (
        "Ship To:\n"
        "Joao Silva\n"
        "Rua Acai 100\n"
        "Sao Paulo, 01000\n"
        "Brazil\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["country"] == "Brazil"


def test_country_japan():
    text = (
        "Ship To:\n"
        "Takeshi Yamada\n"
        "Shibuya-ku 1-2-3\n"
        "Tokyo, 1500001\n"
        "Japan\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["country"] == "Japan"


# ---- Block terminator detection ---------------------------------


def test_bill_to_terminates_block():
    """Ship To block stops at the first 'Bill To' line."""
    text = (
        "Ship To:\n"
        "Alice Smith\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
        "\n"
        "Bill To:\n"
        "Bob Smith\n"
        "456 Oak Ave\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    # Bob Smith / Oak Ave should NOT be in lines
    full_text = " ".join(out["lines"] or [])
    assert "Bob Smith" not in full_text
    assert "Oak Ave" not in full_text


def test_subtotal_terminates_block():
    text = (
        "Ship To:\n"
        "Alice Smith\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
        "Subtotal: $100.00\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    full_text = " ".join(out["lines"] or [])
    assert "Subtotal" not in full_text


def test_order_terminates_block():
    text = (
        "Ship To:\n"
        "Alice Smith\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
        "Order #12345\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    full_text = " ".join(out["lines"] or [])
    assert "Order" not in full_text


def test_blank_line_terminates_block():
    text = (
        "Ship To:\n"
        "Alice Smith\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
        "\n"
        "Other Section\n"
        "Bob Other\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    full_text = " ".join(out["lines"] or [])
    assert "Bob Other" not in full_text
    assert "Other Section" not in full_text


# ---- Name detection / fallback ----------------------------------


def test_no_recipient_name_just_address():
    """Some receipts skip the recipient name -- first line IS the street."""
    text = (
        "Ship To:\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["name"] is None
    assert "123 Main St" in (out["lines"] or [])


def test_name_with_apostrophe():
    text = (
        "Ship To:\n"
        "Mary O'Brien\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["name"] == "Mary O'Brien"


def test_name_with_hyphen():
    text = (
        "Ship To:\n"
        "Mary-Jane Smith\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["name"] == "Mary-Jane Smith"


def test_three_word_name():
    text = (
        "Ship To:\n"
        "Alice Mary Smith\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["name"] == "Alice Mary Smith"


def test_company_name_as_recipient():
    text = (
        "Ship To:\n"
        "Acme Corporation\n"
        "456 Industrial Way\n"
        "Springfield, IL 62704\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["name"] == "Acme Corporation"


# ---- Address shape variations ------------------------------------


def test_address_with_unit():
    text = (
        "Ship To:\n"
        "Alice Smith\n"
        "123 Main St Unit 4B\n"
        "Springfield, IL 62704\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert "123 Main St Unit 4B" in (out["lines"] or [])


def test_po_box_address():
    text = (
        "Ship To:\n"
        "Alice Smith\n"
        "PO Box 1234\n"
        "Springfield, IL 62704\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert "PO Box 1234" in (out["lines"] or [])


def test_multi_word_city():
    text = (
        "Ship To:\n"
        "Alice Smith\n"
        "456 Oak Ave\n"
        "San Francisco, CA 94110\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["city"] == "San Francisco"
    assert out["state"] == "CA"
    assert out["postal_code"] == "94110"


def test_hyphenated_city():
    text = (
        "Ship To:\n"
        "Marie Dupont\n"
        "10 Rue de Paris\n"
        "Aix-en-Provence, 13100\n"
        "France\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    assert out["city"] == "Aix-en-Provence"


# ---- Cap and safety ----------------------------------------------


def test_max_6_address_lines():
    text = "Ship To:\n" + "\n".join(f"Line {i}" for i in range(20))
    out = _find_ship_to(text)
    assert out is not None
    # name + up to 6 lines
    assert len(out["lines"] or []) <= 6


def test_country_terminates_collection():
    """After a country line, no further lines bleed in."""
    text = (
        "Ship To:\n"
        "Alice Smith\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
        "United States\n"
        "Some other line\n"
    )
    out = _find_ship_to(text)
    assert out is not None
    full_text = " ".join(out["lines"] or [])
    assert "Some other line" not in full_text


# ---- enrich_receipt integration ---------------------------------


def test_enrich_receipt_no_existing():
    text = (
        "Ship To:\n"
        "Alice Smith\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
        "Subtotal: $100.00\n"
        "Total: $110.00\n"
    )
    out = enrich_receipt(None, OCRResult(text=text))
    assert out.ship_to is not None
    assert out.ship_to["name"] == "Alice Smith"


def test_enrich_receipt_caller_ship_to_preserved():
    """When caller supplies a ship_to, regex doesn't override."""
    text = (
        "Ship To:\n"
        "Alice Smith\n"
        "123 Main St\n"
        "Springfield, IL 62704\n"
    )
    existing = ReceiptFields(
        vendor="Amazon",
        ship_to={
            "name": "From LLM",
            "lines": ["LLM St"],
            "city": None,
            "state": None,
            "postal_code": None,
            "country": None,
        },
    )
    out = enrich_receipt(existing, OCRResult(text=text))
    assert out.ship_to is not None
    assert out.ship_to["name"] == "From LLM"


def test_enrich_receipt_no_ship_to_in_ocr():
    text = (
        "Joe's Diner\n"
        "Subtotal: $20.00\n"
        "Total: $22.00\n"
    )
    out = enrich_receipt(None, OCRResult(text=text))
    assert out.ship_to is None


# ---- Real-world Amazon-shaped capture ---------------------------


def test_real_world_amazon_order():
    text = """Amazon.com - Order Confirmation
Thank you for your order, Alice!

Order Number: 123-4567890-1234567
Order Date: January 15, 2024

Ship To:
Alice Smith
123 Main Street, Apt 4B
Springfield, IL 62704
United States

Items:
1x Echo Dot (5th Gen)            $49.99
1x USB-C Cable                    $12.99

Subtotal:                  $62.98
Shipping:                   $0.00
Tax:                        $4.41
Total:                     $67.39
"""
    out = _find_ship_to(text)
    assert out is not None
    assert out["name"] == "Alice Smith"
    assert "123 Main Street, Apt 4B" in (out["lines"] or [])
    assert out["city"] == "Springfield"
    assert out["state"] == "IL"
    assert out["postal_code"] == "62704"
    assert out["country"] == "United States"


def test_real_world_shopify_capture():
    text = """ShopGood
Order #SG-1234

Shipping Address:
Marie Dubois
15 Rue de la Paix
75002 Paris
France

Subtotal: 45.00 EUR
Shipping: 5.00 EUR
Total: 50.00 EUR
"""
    out = _find_ship_to(text)
    assert out is not None
    assert out["name"] == "Marie Dubois"
    assert out["country"] == "France"


def test_real_world_etsy_capture():
    text = """Etsy
Order receipt

Ship To:
Sarah Connor
1984 Cyberdyne Way
Los Angeles, CA 90028
USA

Items
Vintage typewriter         $85.00
Shipping                   $12.00
Total                      $97.00
"""
    out = _find_ship_to(text)
    assert out is not None
    assert out["name"] == "Sarah Connor"
    assert out["country"] == "USA"
    assert out["city"] == "Los Angeles"
    assert out["state"] == "CA"
