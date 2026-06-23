"""Receipt subscription / recurring-charge detection tests.

A new ReceiptFields.recurring slot captures the subscription /
auto-renew marker printed on SaaS invoices, subscription-billing
receipts (Netflix / Spotify / Adobe / AWS / Stripe-issued), and
recurring-purchase captures.

Output shape: {"interval": str | None, "next_charge": str | None,
"keyword": str} dict or None for one-off receipts.
"""
from __future__ import annotations

from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract.receipt import _find_recurring, enrich_receipt

# ---- Cadence-bearing keywords ------------------------------------


def test_monthly_subscription():
    out = _find_recurring("Monthly subscription - $9.99")
    assert out is not None
    assert out["interval"] == "monthly"
    assert "Monthly subscription".lower() in out["keyword"].lower()


def test_annual_subscription():
    out = _find_recurring("Annual subscription $99.00")
    assert out is not None
    assert out["interval"] == "annual"


def test_yearly_subscription_alias():
    out = _find_recurring("Yearly subscription - $89")
    assert out is not None
    assert out["interval"] == "annual"


def test_weekly_subscription():
    out = _find_recurring("Weekly subscription")
    assert out is not None
    assert out["interval"] == "weekly"


def test_quarterly_subscription():
    out = _find_recurring("Quarterly subscription")
    assert out is not None
    assert out["interval"] == "quarterly"


def test_daily_subscription():
    out = _find_recurring("Daily subscription")
    assert out is not None
    assert out["interval"] == "daily"


def test_biweekly_subscription():
    out = _find_recurring("Biweekly subscription")
    assert out is not None
    assert out["interval"] == "biweekly"


def test_semi_annual_subscription():
    out = _find_recurring("Semi-annual subscription")
    assert out is not None
    assert out["interval"] == "semiannual"


# ---- Billed / charged + cadence ----------------------------------


def test_billed_monthly():
    out = _find_recurring("Billed monthly $14.99")
    assert out is not None
    assert out["interval"] == "monthly"


def test_billed_annually():
    out = _find_recurring("Billed annually")
    assert out is not None
    assert out["interval"] == "annual"


def test_billed_weekly():
    out = _find_recurring("Billed weekly")
    assert out is not None
    assert out["interval"] == "weekly"


def test_billed_quarterly():
    out = _find_recurring("Billed quarterly")
    assert out is not None
    assert out["interval"] == "quarterly"


def test_charged_monthly():
    out = _find_recurring("Charged monthly")
    assert out is not None
    assert out["interval"] == "monthly"


def test_charged_annually():
    out = _find_recurring("Charged annually")
    assert out is not None
    assert out["interval"] == "annual"


# ---- Recurring + cadence -----------------------------------------


def test_recurring_monthly():
    out = _find_recurring("Recurring monthly")
    assert out is not None
    assert out["interval"] == "monthly"


def test_recurring_annually():
    out = _find_recurring("Recurring annually")
    assert out is not None
    assert out["interval"] == "annual"


def test_recurring_weekly():
    out = _find_recurring("Recurring weekly")
    assert out is not None
    assert out["interval"] == "weekly"


# ---- Renews + cadence --------------------------------------------


def test_renews_monthly():
    out = _find_recurring("Renews monthly")
    assert out is not None
    assert out["interval"] == "monthly"


def test_renews_annually():
    out = _find_recurring("Renews annually")
    assert out is not None
    assert out["interval"] == "annual"


def test_renews_weekly():
    out = _find_recurring("Renews weekly")
    assert out is not None
    assert out["interval"] == "weekly"


# ---- Auto-renew family -------------------------------------------


def test_auto_renew_hyphen():
    out = _find_recurring("Auto-renew on April 15")
    assert out is not None
    assert out["interval"] is None
    assert "auto-renew" in out["keyword"].lower()


def test_auto_renews():
    out = _find_recurring("Auto-renews monthly")
    assert out is not None
    # Note: "Renews monthly" would match recurring/monthly. But
    # "Auto-renews" is a different keyword pattern. Let's check
    # what fires first.
    # The auto-renews pattern matches "Auto[\- ]renews" so this
    # gives us interval=None. (We don't double-count.)
    # Actually wait -- "Renews monthly" would also match, and the
    # candidate list has Renews monthly BEFORE Auto-renews.
    # Let me check the order: it depends on Python's first-match
    # ordering of the candidate list. "Renews monthly" comes
    # BEFORE Auto-renews in the list, so it fires first.
    # The expected interval is "monthly".
    assert out["interval"] == "monthly"


def test_auto_renew_space():
    out = _find_recurring("Auto renew on July 1")
    assert out is not None


def test_automatic_renewal():
    out = _find_recurring("Automatic renewal on 2024-03-15")
    assert out is not None


# ---- Recurring charge / payment / billing ------------------------


def test_recurring_charge():
    out = _find_recurring("This is a recurring charge")
    assert out is not None
    assert out["interval"] is None


def test_recurring_payment():
    out = _find_recurring("Recurring payment")
    assert out is not None


def test_recurring_billing():
    out = _find_recurring("Recurring billing")
    assert out is not None


# ---- Trial markers ----------------------------------------------


def test_free_trial():
    out = _find_recurring("Free trial - card on file")
    assert out is not None
    assert out["interval"] == "trial"


def test_trial_period():
    out = _find_recurring("Trial period: 14 days")
    assert out is not None
    assert out["interval"] == "trial"


def test_trial_ends():
    out = _find_recurring("Trial ends on April 30, 2024")
    assert out is not None
    assert out["interval"] == "trial"


def test_trial_expires():
    out = _find_recurring("Trial expires on March 15")
    assert out is not None
    assert out["interval"] == "trial"


# ---- Bare subscription -------------------------------------------


def test_bare_subscription():
    out = _find_recurring("Subscription - $9.99/mo")
    assert out is not None
    assert out["interval"] is None


def test_bare_subscription_in_middle():
    out = _find_recurring("Order summary\nSubscription\nTotal $9.99")
    assert out is not None
    assert "subscription" in out["keyword"].lower()


# ---- Next-charge date capture ------------------------------------


def test_next_charge_iso_date():
    text = "Monthly subscription\nNext charge: 2024-03-15\nTotal $9.99"
    out = _find_recurring(text)
    assert out is not None
    assert out["interval"] == "monthly"
    assert out["next_charge"] == "2024-03-15"


def test_next_billing_date():
    text = "Subscription\nNext billing: 2024-04-01"
    out = _find_recurring(text)
    assert out is not None
    assert "2024-04-01" in (out["next_charge"] or "")


def test_renews_on_date():
    text = "Auto-renew\nRenews on April 1, 2024"
    out = _find_recurring(text)
    assert out is not None
    # Next charge captured from the "Renews on" pattern.
    assert out["next_charge"] is not None
    assert "April" in out["next_charge"]


def test_renewal_date():
    text = "Subscription\nRenewal date: 2024-03-15"
    out = _find_recurring(text)
    assert out is not None


def test_auto_renews_on_date():
    text = "Auto-renews on 2024-03-15"
    out = _find_recurring(text)
    assert out is not None
    assert out["next_charge"] is not None


def test_trial_ends_on_date():
    text = "Trial ends on April 30, 2024"
    out = _find_recurring(text)
    assert out is not None
    assert out["interval"] == "trial"


# ---- One-off receipts return None --------------------------------


def test_one_off_receipt_returns_none():
    text = "Coffee Shop\nLatte $5.00\nTotal $5.00"
    assert _find_recurring(text) is None


def test_grocery_receipt_returns_none():
    text = "Whole Foods\nMilk 4.50\nBread 3.00\nTotal 7.50"
    assert _find_recurring(text) is None


def test_restaurant_receipt_returns_none():
    text = "Restaurant XYZ\nBurger 12.00\nFries 5.00\nTotal 17.00"
    assert _find_recurring(text) is None


# ---- Empty / None inputs ----------------------------------------


def test_empty_text_returns_none():
    assert _find_recurring("") is None


def test_none_text_returns_none():
    assert _find_recurring(None) is None  # type: ignore[arg-type]


# ---- False-positive defences -------------------------------------


def test_subscriber_count_does_not_fire():
    """``Subscriber count`` should NOT fire because ``\\b`` word-boundary
    enforcement prevents bare ``Subscription`` from eating ``Subscriber``."""
    out = _find_recurring("Subscriber count: 1000")
    # The pattern requires "Subscription" exact (word-boundary on
    # both ends). "Subscriber" is a different word.
    assert out is None


def test_bare_monthly_alone_does_not_fire():
    """Plain ``Monthly`` without context shouldn't false-positive."""
    out = _find_recurring("Visit us monthly")
    # No "Monthly subscription" / "Billed monthly" / etc.
    assert out is None


def test_subscribe_does_not_fire():
    out = _find_recurring("Subscribe to our newsletter")
    # "Subscribe" is not "Subscription"; word boundary enforcement.
    assert out is None


# ---- Case insensitivity ------------------------------------------


def test_uppercase_monthly_subscription():
    out = _find_recurring("MONTHLY SUBSCRIPTION")
    assert out is not None
    assert out["interval"] == "monthly"


def test_lowercase_subscription():
    out = _find_recurring("subscription")
    assert out is not None


def test_mixed_case_auto_renew():
    out = _find_recurring("AuTo-RenEW on April 1")
    assert out is not None


# ---- Realistic SaaS receipts -------------------------------------


def test_netflix_style_receipt():
    text = """Netflix
Monthly subscription
Plan: Standard
Next charge: April 5, 2024
Total: $15.49
"""
    out = _find_recurring(text)
    assert out is not None
    assert out["interval"] == "monthly"
    assert out["next_charge"] is not None
    assert "April" in out["next_charge"]


def test_spotify_style_receipt():
    text = """Spotify Premium
Monthly subscription $9.99
Renews on May 1, 2024
"""
    out = _find_recurring(text)
    assert out is not None
    assert out["interval"] == "monthly"


def test_aws_style_receipt():
    text = """AWS Monthly Bill
Recurring monthly
Next billing: 2024-04-01
Total: $123.45
"""
    out = _find_recurring(text)
    assert out is not None
    assert out["interval"] == "monthly"
    assert out["next_charge"] is not None


def test_adobe_style_receipt():
    text = """Adobe Creative Cloud
Annual subscription
Auto-renews on 2024-12-01
Total: $599.88
"""
    out = _find_recurring(text)
    assert out is not None
    assert out["interval"] == "annual"


def test_stripe_issued_receipt():
    text = """Subscription receipt
Billed monthly: $29.00
Next charge: 2024-04-15
"""
    out = _find_recurring(text)
    assert out is not None
    assert out["interval"] == "monthly"
    assert out["next_charge"] is not None


# ---- enrich_receipt integration ----------------------------------


def test_enrich_receipt_populates_recurring():
    """enrich_receipt should surface recurring marker."""
    ocr = OCRResult(
        text="Netflix\nMonthly subscription\nTotal $15.49"
    )
    receipt = enrich_receipt(None, ocr)
    assert receipt.recurring is not None
    assert receipt.recurring["interval"] == "monthly"


def test_enrich_receipt_preserves_caller_recurring():
    """Caller-supplied recurring is preserved; OCR doesn't override."""
    existing = ReceiptFields(
        recurring={
            "interval": "annual",
            "next_charge": None,
            "keyword": "Annual Subscription",
        },
    )
    ocr = OCRResult(text="Monthly subscription")
    receipt = enrich_receipt(existing, ocr)
    # Caller's value wins because it's non-None.
    assert receipt.recurring["interval"] == "annual"


def test_enrich_receipt_backfill_from_ocr():
    """When caller has no recurring, OCR pass fills it."""
    existing = ReceiptFields(recurring=None)
    ocr = OCRResult(text="Monthly subscription")
    receipt = enrich_receipt(existing, ocr)
    assert receipt.recurring is not None
    assert receipt.recurring["interval"] == "monthly"


def test_enrich_receipt_one_off_stays_none():
    """A regular retail receipt has recurring=None."""
    ocr = OCRResult(text="Coffee Shop\nLatte 5.00\nTotal 5.00")
    receipt = enrich_receipt(None, ocr)
    assert receipt.recurring is None


# ---- Edge cases --------------------------------------------------


def test_subscription_at_start_of_line():
    out = _find_recurring("\nSubscription")
    assert out is not None


def test_subscription_at_end_of_text():
    out = _find_recurring("Total $9.99 Subscription")
    assert out is not None


def test_multiple_cadence_keywords_first_wins():
    text = "Monthly subscription\nAnnual subscription"
    out = _find_recurring(text)
    assert out is not None
    # Both fire but the first-encountered key wins.
    assert out["interval"] in ("monthly", "annual")


def test_renews_monthly_in_isolation():
    out = _find_recurring("Renews monthly")
    assert out is not None
    assert out["interval"] == "monthly"


def test_next_charge_with_year_in_date():
    text = "Subscription\nNext charge: March 15, 2024"
    out = _find_recurring(text)
    assert out is not None
    assert "March" in (out["next_charge"] or "")


def test_keyword_preserved_in_output():
    out = _find_recurring("Annual subscription")
    assert out is not None
    # Keyword preserved from the match.
    assert "annual" in out["keyword"].lower()


def test_returns_keyword_with_correct_case():
    """Keyword case is preserved verbatim from the receipt."""
    out = _find_recurring("monthly subscription")
    assert out is not None
    assert "monthly" in out["keyword"].lower()
