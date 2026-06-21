"""Tests for receipt discount / coupon / promo extraction.

The new ``ReceiptFields.discount`` field captures the absolute
discount amount applied to the receipt. We accept "Discount",
"Coupon", "Promo", "Savings", "Loyalty", and "Rewards" labels
because every printer uses a different word. Last-occurrence wins so
a "Available coupons" header at the top of the receipt cannot
override the actual line the cashier rang up.
"""
from __future__ import annotations

import pytest
from shotclassify_extract.receipt import parse_receipt_text


def test_discount_basic_line():
    text = (
        "Sandwich            8.00\n"
        "Subtotal            8.00\n"
        "Discount            2.00\n"
        "Tax                 0.50\n"
        "Total               6.50\n"
    )
    r = parse_receipt_text(text)
    assert r.discount == 2.0


def test_coupon_label_is_accepted():
    text = "Subtotal 10.00\nCoupon 1.50\nTotal 8.50\n"
    r = parse_receipt_text(text)
    assert r.discount == 1.5


def test_promo_label_is_accepted():
    text = "Sub 5.00\nPromo: 0.75\nTotal 4.25\n"
    r = parse_receipt_text(text)
    assert r.discount == 0.75


def test_loyalty_and_rewards_labels():
    a = parse_receipt_text("Sub 5.00\nLoyalty 0.50\nTotal 4.50\n")
    b = parse_receipt_text("Sub 5.00\nRewards 0.25\nTotal 4.75\n")
    c = parse_receipt_text("Sub 5.00\nMember Savings 1.00\nTotal 4.00\n")
    assert a.discount == 0.5
    assert b.discount == 0.25
    assert c.discount == 1.0


def test_discount_negative_sign_is_not_captured():
    """The shared amount regex does not allow a sign character
    immediately before the digit run, so a line like
    ``Discount: -2.00`` is NOT captured. We document this here so a
    later change that broadens the regex does not regress silently."""
    text = "Sub 10.00\nDiscount: -2.00\nTotal 8.00\n"
    r = parse_receipt_text(text)
    assert r.discount is None


def test_discount_absent_returns_none():
    text = "Latte 6.00\nSubtotal 6.00\nTotal 6.00\n"
    r = parse_receipt_text(text)
    assert r.discount is None


def test_discount_last_occurrence_wins():
    """A header table of available coupons must not override the real line."""
    text = (
        "Available coupons (Discount 5.00 on next visit)\n"
        "Sub 12.00\n"
        "Discount 1.50\n"
        "Total 10.50\n"
    )
    r = parse_receipt_text(text)
    assert r.discount == 1.5


def test_discount_does_not_appear_as_item():
    """The discount line is skipped by the item parser so it does
    not also surface as a $2.00 line item."""
    text = (
        "Sandwich            8.00\n"
        "Discount            2.00\n"
        "Total               6.00\n"
    )
    r = parse_receipt_text(text)
    descs = [i.description.lower() for i in r.items]
    assert all("discount" not in d for d in descs)


@pytest.mark.parametrize(
    "keyword,amount",
    [
        ("Discount", 1.00),
        ("Coupon", 2.50),
        ("Promo", 0.99),
        ("Savings", 3.00),
        ("Loyalty", 0.50),
        ("Rewards", 1.25),
    ],
)
def test_discount_per_keyword(keyword, amount):
    text = f"Sub 10.00\n{keyword} {amount:.2f}\nTotal 7.50\n"
    r = parse_receipt_text(text)
    assert r.discount == amount


def test_full_receipt_with_tip_tax_and_discount():
    """All four optional adjustments coexist correctly."""
    text = (
        "Brewdog Pub\n"
        "2026-03-15\n"
        "Pint                6.00\n"
        "Pizza              12.00\n"
        "Subtotal           18.00\n"
        "Discount            2.00\n"
        "Tax                 1.60\n"
        "Tip                 3.00\n"
        "Total              20.60\n"
        "Visa **** 1234\n"
    )
    r = parse_receipt_text(text)
    assert r.subtotal == 18.0
    assert r.discount == 2.0
    assert r.tax == 1.6
    assert r.tip == 3.0
    assert r.total == 20.6
    assert r.payment_method == "visa"
