"""Loyalty / rewards points-earned extraction tests.

Receipts from point-issuing programmes (Starbucks Stars, Air Miles,
hotel reward points, supermarket clubcard, airline frequent-flyer
miles) print the per-transaction earn as a small footer line:

  Points Earned: 25
  Stars Awarded: 3
  Miles Earned: 100
  Rewards Points: 50
  Air Miles: 12

The new ``ReceiptFields.points_earned`` slot captures this as an int.

Distinct from ``loyalty_id`` (the customer's account identifier).

Balance-vs-earn distinction: lines that ALSO contain a
balance-vocabulary token (``balance`` / ``total points`` /
``current`` / ``remaining`` / ``available`` / ``lifetime`` /
``redeemable`` / ``accumulated`` / ``ytd``) are SKIPPED so a
``Total Points: 1245`` line never populates the earn slot.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult, ReceiptFields
from shotclassify_extract import enrich, parse_receipt_text
from shotclassify_extract.receipt import _find_points_earned

# ---- Multi-word earn keywords ---------------------------------


def test_points_earned_canonical():
    assert _find_points_earned("Points Earned: 25\n") == 25


def test_points_awarded():
    assert _find_points_earned("Points Awarded: 50\n") == 50


def test_points_added():
    assert _find_points_earned("Points Added: 10\n") == 10


def test_points_issued():
    assert _find_points_earned("Points Issued: 15\n") == 15


def test_stars_earned():
    assert _find_points_earned("Stars Earned: 2\n") == 2


def test_stars_awarded():
    assert _find_points_earned("Stars Awarded: 3\n") == 3


def test_stars_added():
    assert _find_points_earned("Stars Added: 1\n") == 1


def test_miles_earned():
    assert _find_points_earned("Miles Earned: 100\n") == 100


def test_miles_awarded():
    assert _find_points_earned("Miles Awarded: 250\n") == 250


def test_miles_added():
    assert _find_points_earned("Miles Added: 50\n") == 50


def test_rewards_earned():
    assert _find_points_earned("Rewards Earned: 5\n") == 5


def test_rewards_awarded():
    assert _find_points_earned("Rewards Awarded: 7\n") == 7


def test_rewards_points():
    assert _find_points_earned("Rewards Points: 50\n") == 50


def test_reward_points():
    assert _find_points_earned("Reward Points: 25\n") == 25


def test_bonus_points():
    assert _find_points_earned("Bonus Points: 10\n") == 10


def test_air_miles():
    assert _find_points_earned("Air Miles: 12\n") == 12


def test_frequent_flyer_miles():
    assert _find_points_earned("Frequent Flyer Miles: 500\n") == 500


def test_ff_miles():
    assert _find_points_earned("FF Miles: 250\n") == 250


def test_loyalty_points():
    assert _find_points_earned("Loyalty Points: 100\n") == 100


def test_member_points():
    assert _find_points_earned("Member Points: 75\n") == 75


def test_club_points():
    assert _find_points_earned("Club Points: 25\n") == 25


def test_avios():
    assert _find_points_earned("Avios: 200\n") == 200


# ---- Bare aliases (with balance-vocabulary guard) -------------


def test_bare_points():
    assert _find_points_earned("Points: 35\n") == 35


def test_bare_stars():
    assert _find_points_earned("Stars: 2\n") == 2


def test_bare_miles():
    assert _find_points_earned("Miles: 100\n") == 100


# ---- Balance-vocabulary disqualifiers -------------------------


def test_total_points_disqualified():
    assert _find_points_earned("Total Points: 1245\n") is None


def test_points_balance_disqualified():
    assert _find_points_earned("Points Balance: 1245\n") is None


def test_current_points_disqualified():
    assert _find_points_earned("Current Points: 800\n") is None


def test_remaining_points_disqualified():
    assert _find_points_earned("Remaining Points: 500\n") is None


def test_available_points_disqualified():
    assert _find_points_earned("Available Points: 1000\n") is None


def test_lifetime_points_disqualified():
    assert _find_points_earned("Lifetime Points: 50000\n") is None


def test_redeemable_points_disqualified():
    assert _find_points_earned("Redeemable Points: 250\n") is None


def test_accumulated_points_disqualified():
    assert _find_points_earned("Accumulated Points: 1500\n") is None


def test_ytd_points_disqualified():
    assert _find_points_earned("YTD Points: 750\n") is None


def test_year_to_date_disqualified():
    assert _find_points_earned("Year-to-date Points: 1000\n") is None


# ---- Earn + balance on same receipt -> earn wins --------------


def test_earn_and_balance_both_present():
    # When a receipt prints BOTH the earn AND the balance, the earn
    # keyword wins because the balance line is disqualified.
    text = (
        "Points Earned: 25\n"
        "Total Points: 1245\n"
    )
    assert _find_points_earned(text) == 25


def test_balance_first_then_earn():
    text = (
        "Points Balance: 1245\n"
        "Points Earned: 25\n"
    )
    assert _find_points_earned(text) == 25


def test_only_balance_returns_none():
    text = (
        "Points Balance: 1245\n"
    )
    assert _find_points_earned(text) is None


# ---- Bounds enforcement ----------------------------------------


def test_zero_rejected():
    # 0 is rejected because it's almost always "card not scanned"
    # not "true zero earn".
    assert _find_points_earned("Points Earned: 0\n") is None


def test_one_accepted():
    assert _find_points_earned("Points Earned: 1\n") == 1


def test_large_value_accepted():
    assert _find_points_earned("Points Earned: 999999\n") == 999999


def test_million_accepted():
    assert _find_points_earned("Points Earned: 1000000\n") == 1000000


def test_too_large_rejected():
    # 10_000_000 would be a misread; reject.
    # Our regex caps at 7 digits anyway so the regex won't match.
    assert _find_points_earned("Points Earned: 10000000\n") is None


# ---- Decimal values rejected (integer only) -------------------


def test_decimal_value_rejected():
    # Points are whole numbers; a decimal value rejects.
    assert _find_points_earned("Points Earned: 25.5\n") is None


def test_thousands_grouped_accepted():
    # "1,245" should parse as 1245.
    assert _find_points_earned("Points Earned: 1,245\n") == 1245


def test_thousands_grouped_large():
    assert _find_points_earned("Points Earned: 12,500\n") == 12500


# ---- Various separators ----------------------------------------


def test_colon_separator():
    assert _find_points_earned("Points Earned: 25\n") == 25


def test_space_separator():
    assert _find_points_earned("Points Earned 25\n") == 25


def test_hash_separator():
    assert _find_points_earned("Points Earned #25\n") == 25


def test_dash_separator():
    assert _find_points_earned("Points Earned - 25\n") == 25


# ---- Case insensitivity ----------------------------------------


def test_lowercase_keyword():
    assert _find_points_earned("points earned: 25\n") == 25


def test_uppercase_keyword():
    assert _find_points_earned("POINTS EARNED: 25\n") == 25


def test_mixed_case():
    assert _find_points_earned("Points EARNED: 25\n") == 25


# ---- Priority: specific keyword wins ---------------------------


def test_specific_wins_over_bare():
    # "Points Earned: 25" and "Points: 99" should pick the specific
    # earn keyword's value.
    text = (
        "Points Earned: 25\n"
        "Points: 99\n"
    )
    assert _find_points_earned(text) == 25


def test_last_occurrence_per_keyword_wins():
    # If the same keyword appears twice (echoed footer), the last
    # one wins.
    text = (
        "Points Earned: 10\n"
        "...\n"
        "Points Earned: 25\n"
    )
    assert _find_points_earned(text) == 25


# ---- False-positive defences -----------------------------------


def test_no_points_keyword_returns_none():
    text = "Subtotal: 12.00\nTax: 1.00\nTotal: 13.00\n"
    assert _find_points_earned(text) is None


def test_empty_returns_none():
    assert _find_points_earned("") is None


def test_keyword_inside_other_word_rejected():
    # "Earnings: 25" should not fire as "Earn" keyword because the
    # word boundary on the left rejects it.
    assert _find_points_earned("Earnings: 25\n") is None


def test_keyword_inside_other_word_2():
    # "Tractor Points" / "Endpoints" / etc. should not fire.
    assert _find_points_earned("Endpoints: 5\n") is None


def test_negative_value_not_captured():
    # A negative points line (refund / deduction) is not captured by
    # this slot; the field semantic is positive earn only.
    text = "Points Earned: -10\n"
    # The regex doesn't allow a leading minus on the digit, so the
    # match misses entirely.
    assert _find_points_earned(text) is None


# ---- Real-world contexts ---------------------------------------


def test_starbucks_style_receipt():
    text = (
        "STARBUCKS\n"
        "Grande Latte           4.95\n"
        "Subtotal               4.95\n"
        "Tax                    0.41\n"
        "Total                  5.36\n"
        "Stars Earned: 5\n"
        "Total Stars: 142\n"
        "Member ID: 12345\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.points_earned == 5


def test_grocery_clubcard_receipt():
    text = (
        "TESCO\n"
        "Groceries              45.20\n"
        "Clubcard Points: 45\n"
        "Lifetime Points: 12,500\n"
    )
    parsed = parse_receipt_text(text)
    # The bare "Points" alias matches "Clubcard Points: 45" because
    # the "Clubcard" prefix is not a balance disqualifier. The
    # "Lifetime Points: 12,500" line is correctly disqualified by
    # the "lifetime" balance token, so only the 45 lands.
    assert parsed.points_earned == 45


def test_airline_receipt():
    text = (
        "AIR FRANCE\n"
        "Flight CDG-JFK\n"
        "Frequent Flyer Miles: 3650\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.points_earned == 3650


def test_hotel_receipt():
    text = (
        "HILTON HONORS\n"
        "Room Charge        199.00\n"
        "Honors Points Earned: 1990\n"
    )
    parsed = parse_receipt_text(text)
    # "Honors Points Earned" -- the matcher looks for "Points Earned"
    # as a specific keyword; the "Honors " prefix is fine because
    # our regex allows preceding non-alpha context (a space is
    # "non-alpha" boundary).
    # Actually wait -- the negative-lookbehind is for [^A-Za-z], so
    # a preceding letter would block it. Let's verify behaviour.
    # The line is "Honors Points Earned: 1990" -- the "Points Earned"
    # is preceded by " " (a space) which is non-alpha, so it DOES
    # match.
    assert parsed.points_earned == 1990


def test_avios_receipt():
    text = (
        "BRITISH AIRWAYS\n"
        "Flight LHR-DXB\n"
        "Avios: 5000\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.points_earned == 5000


# ---- parse_receipt_text + enrich integration ------------------


def test_parse_receipt_text_no_points():
    text = "Subtotal: 12.00\nTotal: 14.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.points_earned is None


def test_enrich_pipeline_populates_points():
    text = (
        "Subtotal: 5.00\n"
        "Total: 5.36\n"
        "Stars Earned: 5\n"
    )
    fields = ExtractedFields()
    ocr = OCRResult(text=text)
    enriched = enrich(Category.receipt, fields, ocr)
    assert enriched.receipt is not None
    assert enriched.receipt.points_earned == 5


def test_enrich_pipeline_preserves_caller_points():
    text = (
        "Stars Earned: 5\n"
    )
    fields = ExtractedFields(receipt=ReceiptFields(points_earned=99))
    ocr = OCRResult(text=text)
    enriched = enrich(Category.receipt, fields, ocr)
    assert enriched.receipt is not None
    # Caller-supplied non-zero value wins (per the enrich merge logic).
    assert enriched.receipt.points_earned == 99


def test_enrich_pipeline_backfills_none():
    text = (
        "Stars Earned: 5\n"
    )
    fields = ExtractedFields(receipt=ReceiptFields(points_earned=None))
    ocr = OCRResult(text=text)
    enriched = enrich(Category.receipt, fields, ocr)
    assert enriched.receipt is not None
    # None gets backfilled.
    assert enriched.receipt.points_earned == 5


# ---- Schema default --------------------------------------------


def test_receipt_fields_default_none():
    rf = ReceiptFields()
    assert rf.points_earned is None


def test_receipt_fields_accepts_int():
    rf = ReceiptFields(points_earned=42)
    assert rf.points_earned == 42


# ---- Edge cases ------------------------------------------------


def test_tab_separated():
    assert _find_points_earned("Points Earned:\t25\n") == 25


def test_multiple_spaces():
    assert _find_points_earned("Points Earned:    25\n") == 25


def test_keyword_with_no_value_returns_none():
    assert _find_points_earned("Points Earned:\n") is None


def test_keyword_with_text_value_returns_none():
    assert _find_points_earned("Points Earned: pending\n") is None


def test_multiple_keywords_same_receipt():
    # When two different earn keywords are printed, the more-specific
    # priority order means the FIRST keyword in the catalogue that
    # matches wins.
    text = (
        "Stars Earned: 3\n"
        "Points Earned: 25\n"
    )
    # "Points Earned" comes first in catalogue.
    assert _find_points_earned(text) == 25


def test_inline_followed_by_more_text():
    # "Points Earned: 25 (will appear in 24h)" -- the regex captures
    # just the integer.
    text = "Points Earned: 25 (will appear in 24h)\n"
    assert _find_points_earned(text) == 25


def test_long_realistic_receipt():
    text = (
        "STARBUCKS RESERVE\n"
        "1912 PIKE PLACE\n"
        "Seattle, WA\n"
        "\n"
        "Date: 06/22/2026\n"
        "Cashier: Sarah\n"
        "Register #04\n"
        "\n"
        "Latte Grande            5.45\n"
        "Croissant               3.25\n"
        "\n"
        "Subtotal                8.70\n"
        "Tax                     0.72\n"
        "Total                   9.42\n"
        "\n"
        "Visa ending 1234        9.42\n"
        "\n"
        "Stars Earned: 9\n"
        "Total Stars: 142\n"
        "Member ID: SR-12345\n"
        "\n"
        "Thank you!\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.points_earned == 9
    # Verify other fields aren't broken.
    assert parsed.total == 9.42
    assert parsed.cashier == "Sarah"
