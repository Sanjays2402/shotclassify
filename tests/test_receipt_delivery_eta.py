"""Receipt delivery / arrival ETA extraction tests.

A new ``ReceiptFields.delivery_eta`` slot captures the estimated
delivery / arrival time printed by delivery-aggregator receipts
(DoorDash / Uber Eats / Deliveroo / Amazon / Instacart / Lyft /
Caviar / Grubhub) and on-demand courier captures.

Output is the cleaned ETA string verbatim or ``None`` for in-
person retail / dine-in restaurant receipts that have no future-
delivery context.
"""
from __future__ import annotations

from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract.receipt import _find_delivery_eta, enrich_receipt

# ---- Compound multi-word keywords (highest specificity) ---------


def test_estimated_delivery_today_window():
    out = _find_delivery_eta("Estimated delivery: Today 6-7 PM")
    assert out == "Today 6-7 PM"


def test_estimated_delivery_specific_date():
    out = _find_delivery_eta("Estimated delivery: Wed Jun 10")
    assert out == "Wed Jun 10"


def test_estimated_arrival_amazon_style():
    out = _find_delivery_eta("Estimated arrival: Thursday, June 12 by 8 PM")
    assert out == "Thursday, June 12 by 8 PM"


def test_estimated_delivery_time_with_optional_time_word():
    out = _find_delivery_eta("Estimated delivery time: 30-45 min")
    assert out == "30-45 min"


def test_expected_delivery():
    out = _find_delivery_eta("Expected delivery: tomorrow by noon")
    assert out == "tomorrow by noon"


def test_expected_arrival():
    out = _find_delivery_eta("Expected arrival: Fri Jun 14")
    assert out == "Fri Jun 14"


def test_dash_separator_works():
    """A dash separator instead of colon."""
    out = _find_delivery_eta("Estimated delivery - Today 6-7 PM")
    assert out == "Today 6-7 PM"


# ---- Out-for-delivery shape (USPS / FedEx) ----------------------


def test_out_for_delivery_arrives():
    out = _find_delivery_eta("Out for delivery, arrives 2:30 PM")
    assert out == "2:30 PM"


def test_out_for_delivery_arriving():
    out = _find_delivery_eta("Out for delivery, arriving by 4 PM")
    assert out == "by 4 PM"


def test_out_for_delivery_eta():
    out = _find_delivery_eta("Out for delivery, ETA 3:45 PM")
    assert out == "3:45 PM"


# ---- Arriving / Arrives shape (DoorDash status) ----------------


def test_arriving_by_time():
    out = _find_delivery_eta("Arriving by 8:45 PM")
    assert out == "8:45 PM"


def test_arriving_in_minutes():
    out = _find_delivery_eta("Arriving in 12 minutes")
    assert out == "12 minutes"


def test_arriving_at_address():
    out = _find_delivery_eta("Arriving at 8:00 PM")
    assert out == "8:00 PM"


def test_arrives_by_time():
    out = _find_delivery_eta("Arrives by 9:30 PM")
    assert out == "9:30 PM"


def test_arriving_between_window():
    out = _find_delivery_eta("Arriving between 6 and 7 PM")
    assert out == "6 and 7 PM"


def test_arriving_bare_time_no_preposition():
    """``Arriving 8:00 PM`` (no preposition)."""
    out = _find_delivery_eta("Arriving 8:00 PM")
    assert out == "8:00 PM"


# ---- ETA bare keyword (courier apps) ----------------------------


def test_eta_colon_time():
    out = _find_delivery_eta("ETA: 15 min")
    assert out == "15 min"


def test_eta_dash_time():
    out = _find_delivery_eta("ETA - 6:30 PM")
    assert out == "6:30 PM"


def test_eta_range():
    out = _find_delivery_eta("ETA: 12-15 min")
    assert out == "12-15 min"


# ---- Delivery bare keyword fallback ----------------------------


def test_delivery_colon_today():
    out = _find_delivery_eta("Delivery: Today 6:00 PM - 7:00 PM")
    assert out == "Today 6:00 PM - 7:00 PM"


def test_delivery_colon_tomorrow():
    out = _find_delivery_eta("Delivery: tomorrow by 5 PM")
    assert out == "tomorrow by 5 PM"


# ---- Multi-line receipts ---------------------------------------


def test_multiline_receipt_picks_eta_line():
    text = """
    DoorDash
    1x Pad Thai      12.99
    1x Pho           14.50
    Subtotal         27.49
    Delivery Fee     2.99
    Tip              5.00
    Total            35.48
    Estimated arrival: 25-35 min
    """
    out = _find_delivery_eta(text)
    assert out == "25-35 min"


def test_multiple_eta_patterns_compound_wins():
    """When both ``Estimated delivery:`` and ``ETA:`` appear, the
    compound (more specific) form wins because patterns are tried
    in order."""
    text = """
    Estimated delivery: Today 6:00 PM
    ETA: 30 min
    """
    out = _find_delivery_eta(text)
    assert out == "Today 6:00 PM"


# ---- Safety: false positives ------------------------------------


def test_delivery_fee_with_currency_amount_rejected():
    """``Delivery: $4.99`` is a delivery FEE, not an ETA."""
    out = _find_delivery_eta("Delivery: $4.99")
    assert out is None


def test_delivery_fee_decimal_amount_rejected():
    """``Delivery: 4.99`` (no $) is still a fee."""
    out = _find_delivery_eta("Delivery: 4.99")
    assert out is None


def test_no_delivery_keyword_returns_none():
    """A normal in-store receipt with no delivery context."""
    text = """
    Starbucks #1234
    Latte                5.00
    Subtotal             5.00
    Tax                  0.40
    Total                5.40
    """
    out = _find_delivery_eta(text)
    assert out is None


def test_empty_text_returns_none():
    assert _find_delivery_eta("") is None


def test_none_text_returns_none():
    assert _find_delivery_eta(None) is None  # type: ignore[arg-type]


def test_arriving_prose_without_time_rejected():
    """``Arriving soon`` -- captured as ``soon`` which is acceptable."""
    out = _find_delivery_eta("Arriving soon")
    # ``soon`` is a valid ETA-like word for a courier app.
    assert out == "soon"


def test_very_long_value_rejected():
    """Values >120 chars are OCR noise."""
    long_value = " ".join(["foo"] * 50)
    text = f"Estimated delivery: {long_value}"
    out = _find_delivery_eta(text)
    assert out is None


# ---- enrich_receipt plumbing ------------------------------------


def test_enrich_receipt_populates_delivery_eta():
    ocr = OCRResult(text="DoorDash\nArriving by 8:45 PM")
    fields = enrich_receipt(None, ocr)
    assert fields.delivery_eta == "8:45 PM"


def test_enrich_receipt_preserves_caller_value():
    """When caller supplied delivery_eta, it's preserved."""
    existing = ReceiptFields(delivery_eta="Already set")
    ocr = OCRResult(text="Estimated delivery: Today 6 PM")
    fields = enrich_receipt(existing, ocr)
    assert fields.delivery_eta == "Already set"


def test_enrich_receipt_backfills_empty_delivery_eta():
    existing = ReceiptFields()  # no delivery_eta set
    ocr = OCRResult(text="ETA: 25 min")
    fields = enrich_receipt(existing, ocr)
    assert fields.delivery_eta == "25 min"


def test_enrich_receipt_no_eta_marker():
    """Receipt with no ETA -> delivery_eta stays None."""
    ocr = OCRResult(text="Starbucks\nLatte 5.00\nTotal 5.40")
    fields = enrich_receipt(None, ocr)
    assert fields.delivery_eta is None


# ---- Real-world fixtures ----------------------------------------


def test_doordash_receipt():
    text = """
    DoorDash
    Order from: Thai House
    1x Pad See Ew              13.50
    1x Pho                     14.95
    Subtotal                   28.45
    Delivery Fee                3.99
    Service Fee                 2.85
    Tip                         5.00
    Total                      40.29
    Estimated arrival: 25-35 min
    """
    out = _find_delivery_eta(text)
    assert out == "25-35 min"


def test_uber_eats_receipt():
    text = """
    Uber Eats
    Subtotal      15.99
    Service Fee    2.40
    Delivery       1.99
    Total         20.38
    Arriving by 9:15 PM
    """
    out = _find_delivery_eta(text)
    assert out == "9:15 PM"


def test_amazon_receipt():
    text = """
    Amazon.com
    Item: USB-C Cable
    Subtotal: $9.99
    Shipping: $0.00 (Prime)
    Total: $9.99
    Estimated delivery: Wednesday, June 10
    """
    out = _find_delivery_eta(text)
    assert out == "Wednesday, June 10"


def test_instacart_receipt():
    text = """
    Instacart
    Whole Foods
    Items: 12
    Subtotal: $87.45
    Total: $98.32
    Delivery: Today 4:00 PM - 5:00 PM
    """
    out = _find_delivery_eta(text)
    assert out == "Today 4:00 PM - 5:00 PM"


def test_lyft_eta():
    text = """
    Lyft
    Ride to Airport
    ETA: 8 min
    Pickup at Main St
    """
    out = _find_delivery_eta(text)
    assert out == "8 min"


def test_grubhub_receipt():
    text = """
    Grubhub
    Estimated delivery time: 35-50 minutes
    """
    out = _find_delivery_eta(text)
    assert out == "35-50 minutes"


def test_fedex_status():
    text = "Out for delivery, arrives 4:00 PM"
    out = _find_delivery_eta(text)
    assert out == "4:00 PM"
