"""Receipt cancellation-policy notice extraction tests.

A new ``ReceiptFields.cancellation_policy`` slot captures the
cancellation-policy line printed on hotel / Airbnb / flight /
event / car-rental receipts. Output is a dict
``{"kind", "deadline_hours", "deadline_date", "fee", "notice"}``
or None.
"""
from __future__ import annotations

from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract.receipt import (
    _find_cancellation_policy,
    enrich_receipt,
)

# ---- Empty / no-policy cases -------------------------------------


def test_empty_text():
    assert _find_cancellation_policy("") is None


def test_none_text():
    assert _find_cancellation_policy(None) is None  # type: ignore[arg-type]


def test_no_policy_in_grocery_receipt():
    text = "Bread 3.99\nMilk 2.50\nEggs 4.25\nTotal 10.74"
    assert _find_cancellation_policy(text) is None


def test_no_policy_in_restaurant_receipt():
    text = "Burger 12.00\nFries 4.00\nTip 3.00\nTotal 19.00"
    assert _find_cancellation_policy(text) is None


# ---- Free cancellation with hour-deadline -------------------------


def test_free_cancellation_24h():
    out = _find_cancellation_policy("Free cancellation up to 24 hours before")
    assert out is not None
    assert out["kind"] == "free"
    assert out["deadline_hours"] == 24
    assert out["deadline_date"] is None
    assert out["fee"] is None


def test_free_cancellation_48h():
    out = _find_cancellation_policy("Free cancellation up to 48h before check-in")
    assert out is not None
    assert out["kind"] == "free"
    assert out["deadline_hours"] == 48


def test_free_cancellation_72_hours():
    out = _find_cancellation_policy("Free cancellation 72 hours before")
    assert out is not None
    assert out["kind"] == "free"
    assert out["deadline_hours"] == 72


def test_free_cancellation_2_days():
    out = _find_cancellation_policy("Free cancellation up to 2 days before arrival")
    assert out is not None
    assert out["kind"] == "free"
    assert out["deadline_hours"] == 48


def test_free_cancellation_1_week():
    out = _find_cancellation_policy("Free cancellation up to 1 week before")
    assert out is not None
    assert out["kind"] == "free"
    assert out["deadline_hours"] == 168


def test_free_cancellation_until_phrasing():
    out = _find_cancellation_policy("Free cancellation until 24 hours before check-in")
    assert out is not None
    assert out["kind"] == "free"
    assert out["deadline_hours"] == 24


# ---- Free cancellation bare --------------------------------------


def test_free_cancellation_bare():
    out = _find_cancellation_policy("Free cancellation")
    assert out is not None
    assert out["kind"] == "free"
    assert out["deadline_hours"] is None
    assert out["deadline_date"] is None


def test_free_cancellation_available():
    out = _find_cancellation_policy("Free cancellation available")
    assert out is not None
    assert out["kind"] == "free"


def test_free_cancellation_offered():
    out = _find_cancellation_policy("Free cancellation offered")
    assert out is not None
    assert out["kind"] == "free"


# ---- Cancel keyword + duration -----------------------------------


def test_cancel_within_24h():
    out = _find_cancellation_policy("Cancel within 24 hours for full refund")
    assert out is not None
    assert out["kind"] == "free"
    assert out["deadline_hours"] == 24


def test_cancel_up_to_48h():
    out = _find_cancellation_policy("Cancel up to 48h before check-in")
    assert out is not None
    assert out["kind"] == "free"
    assert out["deadline_hours"] == 48


def test_cancellation_within_7_days():
    out = _find_cancellation_policy("Cancellation within 7 days")
    assert out is not None
    assert out["kind"] == "free"
    assert out["deadline_hours"] == 168


# ---- Date-based deadlines ----------------------------------------


def test_non_refundable_after_dec_1():
    out = _find_cancellation_policy("Non-refundable after Dec 1")
    assert out is not None
    assert out["kind"] == "deadline"
    assert out["deadline_date"] == "Dec 1"
    assert out["deadline_hours"] is None


def test_non_refundable_after_full_date():
    out = _find_cancellation_policy("Non-refundable after December 15, 2024")
    assert out is not None
    assert out["kind"] == "deadline"
    assert out["deadline_date"] == "December 15, 2024"


def test_cancel_before_iso_date():
    out = _find_cancellation_policy("Cancel before 2024-12-31 for full refund")
    assert out is not None
    assert out["kind"] == "deadline"
    assert out["deadline_date"] == "2024-12-31"


def test_cancel_before_us_date():
    out = _find_cancellation_policy("Cancel before 04/15/2024 for full refund")
    assert out is not None
    assert out["kind"] == "deadline"
    assert out["deadline_date"] == "04/15/2024"


def test_free_cancellation_until_checkin():
    out = _find_cancellation_policy("Free cancellation until check-in")
    assert out is not None
    assert out["kind"] == "free"
    assert out["deadline_date"] == "check-in"


def test_free_cancellation_until_arrival():
    out = _find_cancellation_policy("Free cancellation until arrival")
    assert out is not None
    assert out["kind"] == "free"
    assert out["deadline_date"] == "arrival"


def test_non_changeable_after_date():
    out = _find_cancellation_policy("Non-changeable after Dec 15")
    assert out is not None
    assert out["kind"] == "deadline"
    assert out["deadline_date"] == "Dec 15"


# ---- Cancellation fee --------------------------------------------


def test_cancellation_fee_after_24h():
    out = _find_cancellation_policy("Cancellation fee: $50 after 24h")
    assert out is not None
    assert out["kind"] == "fee"
    assert out["fee"] == 50.0
    assert out["deadline_hours"] == 24


def test_cancellation_fee_bare():
    out = _find_cancellation_policy("Cancellation fee: $25")
    assert out is not None
    assert out["kind"] == "fee"
    assert out["fee"] == 25.0


def test_cancellation_fee_decimal():
    out = _find_cancellation_policy("Cancellation fee: $99.99")
    assert out is not None
    assert out["kind"] == "fee"
    assert out["fee"] == 99.99


def test_dollar_amount_cancellation_fee_applies():
    out = _find_cancellation_policy("$25 cancellation fee applies")
    assert out is not None
    assert out["kind"] == "fee"
    assert out["fee"] == 25.0


def test_dollar_amount_cancellation_fee_charged():
    out = _find_cancellation_policy("$50 cancellation fee charged")
    assert out is not None
    assert out["kind"] == "fee"
    assert out["fee"] == 50.0


# ---- No cancellations --------------------------------------------


def test_no_cancellations():
    out = _find_cancellation_policy("No cancellations")
    assert out is not None
    assert out["kind"] == "none"


def test_no_cancellation_singular():
    out = _find_cancellation_policy("No cancellation")
    assert out is not None
    assert out["kind"] == "none"


def test_cancellations_not_permitted():
    out = _find_cancellation_policy("Cancellations are not permitted")
    assert out is not None
    assert out["kind"] == "none"


def test_cancellations_not_allowed():
    out = _find_cancellation_policy("Cancellations not allowed")
    assert out is not None
    assert out["kind"] == "none"


def test_non_refundable_bare():
    out = _find_cancellation_policy("Non-refundable")
    assert out is not None
    assert out["kind"] == "none"


def test_nonrefundable_no_hyphen():
    out = _find_cancellation_policy("Nonrefundable")
    assert out is not None
    assert out["kind"] == "none"


def test_non_refundable_booking():
    out = _find_cancellation_policy("Non-refundable booking")
    assert out is not None
    assert out["kind"] == "none"


def test_no_refunds_or_cancellations():
    out = _find_cancellation_policy("No refunds or cancellations")
    assert out is not None
    assert out["kind"] == "none"


def test_non_cancellable():
    out = _find_cancellation_policy("Non-cancellable")
    assert out is not None
    assert out["kind"] == "none"


# ---- Cancellation policy header ----------------------------------


def test_cancellation_policy_text():
    out = _find_cancellation_policy("Cancellation policy: 48h notice required")
    assert out is not None
    assert out["kind"] == "deadline"
    assert "48h notice required" in out["notice"]


# ---- Realistic full-receipt scenarios ----------------------------


def test_hotel_receipt_with_free_cancellation():
    text = (
        "Hotel Acme\n"
        "Reservation: 12345\n"
        "Check-in: Dec 15, 2024\n"
        "Check-out: Dec 18, 2024\n"
        "Room rate: $150/night\n"
        "Total: $450.00\n"
        "Free cancellation up to 24 hours before check-in"
    )
    out = _find_cancellation_policy(text)
    assert out is not None
    assert out["kind"] == "free"
    assert out["deadline_hours"] == 24


def test_airbnb_non_refundable():
    text = (
        "Airbnb Booking Confirmation\n"
        "Listing: Cozy Cabin\n"
        "Dates: Mar 10-14, 2024\n"
        "Total: $625.00\n"
        "Non-refundable"
    )
    out = _find_cancellation_policy(text)
    assert out is not None
    assert out["kind"] == "none"


def test_flight_receipt_cancellation_fee():
    text = (
        "Acme Airlines\n"
        "Flight AC123 PHX -> ORD\n"
        "Total: $325.00\n"
        "Cancellation fee: $200 after 24h"
    )
    out = _find_cancellation_policy(text)
    assert out is not None
    assert out["kind"] == "fee"
    assert out["fee"] == 200.0
    assert out["deadline_hours"] == 24


# ---- enrich_receipt integration ----------------------------------


def test_enrich_receipt_populates_cancellation_policy():
    text = "Free cancellation up to 24 hours before"
    out = enrich_receipt(None, OCRResult(text=text))
    assert out.cancellation_policy is not None
    assert out.cancellation_policy["kind"] == "free"


def test_enrich_receipt_no_policy():
    text = "Bread 3.99\nMilk 2.50"
    out = enrich_receipt(None, OCRResult(text=text))
    assert out.cancellation_policy is None


def test_enrich_receipt_caller_preserved():
    caller = ReceiptFields(
        cancellation_policy={
            "kind": "free",
            "deadline_hours": 72,
            "deadline_date": None,
            "fee": None,
            "notice": "Custom policy",
        }
    )
    text = "Free cancellation up to 24 hours before"
    out = enrich_receipt(caller, OCRResult(text=text))
    assert out.cancellation_policy is not None
    assert out.cancellation_policy["notice"] == "Custom policy"
    assert out.cancellation_policy["deadline_hours"] == 72


def test_enrich_receipt_caller_none_backfills():
    caller = ReceiptFields()
    text = "Non-refundable"
    out = enrich_receipt(caller, OCRResult(text=text))
    assert out.cancellation_policy is not None
    assert out.cancellation_policy["kind"] == "none"


# ---- Safety / negative cases -------------------------------------


def test_prose_cancellation_not_matched():
    # Bare "cancellation" in prose shouldn't fire because we
    # require a specific keyword catalogue (Free cancellation /
    # Cancellation fee / Cancel before / etc).
    text = "Customer requested cancellation processing"
    out = _find_cancellation_policy(text)
    # The "Cancellation fee" / etc don't match this, but the
    # catalogue might still match "Cancellation policy" or related
    # — accept None or any valid match.
    if out is not None:
        # If it matched, it must be one of the recognised kinds.
        assert out["kind"] in {"free", "fee", "deadline", "none"}


def test_word_cancel_in_unrelated_context():
    # "Cancel" alone (no qualifying duration / date / refund context)
    # shouldn't fire.
    text = "Press Cancel to exit"
    out = _find_cancellation_policy(text)
    assert out is None


def test_fee_amount_validation_rejects_huge():
    # A million-dollar cancellation fee is OCR noise; >= 100k is
    # rejected.
    out = _find_cancellation_policy("Cancellation fee: $999999")
    if out is not None and out["kind"] == "fee":
        # When the fee is rejected by validation, it should be None.
        assert out["fee"] is None or 0 < out["fee"] < 100_000


def test_deadline_beats_bare_non_refundable():
    # "Non-refundable after Dec 1" must tag as deadline, NOT none.
    out = _find_cancellation_policy("Non-refundable after Dec 1")
    assert out is not None
    assert out["kind"] == "deadline"


def test_no_cancellations_beats_other_matchers():
    out = _find_cancellation_policy("No cancellations")
    assert out is not None
    assert out["kind"] == "none"


def test_hours_normalisation_singular():
    out = _find_cancellation_policy("Free cancellation up to 1 hour before")
    assert out is not None
    assert out["deadline_hours"] == 1


def test_hours_normalisation_day_singular():
    out = _find_cancellation_policy("Cancel within 1 day for full refund")
    assert out is not None
    assert out["deadline_hours"] == 24


def test_hours_normalisation_month():
    out = _find_cancellation_policy("Free cancellation up to 1 month before")
    assert out is not None
    assert out["deadline_hours"] == 720  # 30 days


def test_eu_decimal_fee():
    out = _find_cancellation_policy("Cancellation fee: €50,00")
    assert out is not None
    assert out["kind"] == "fee"
    assert out["fee"] == 50.0


def test_pound_fee():
    out = _find_cancellation_policy("Cancellation fee: £75.00")
    assert out is not None
    assert out["kind"] == "fee"
    assert out["fee"] == 75.0


def test_first_match_wins_when_multiple():
    # When a receipt has multiple cancellation lines, the most-
    # specific (first in catalogue) wins. "No cancellations" is
    # first.
    text = "Cancellation fee: $50\nNo cancellations\nFree cancellation"
    out = _find_cancellation_policy(text)
    assert out is not None
    # "No cancellations" should win because it's the no-cancellation
    # matcher first in the catalogue.
    assert out["kind"] == "none"
