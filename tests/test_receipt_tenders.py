"""Receipt split-payment / multi-tender detection tests.

A new ReceiptFields.tenders list captures the per-component
breakdown when a receipt was paid with more than one tender (split
bill across cards, gift-card + card, cash + card, etc).

Output shape: list of ``{kind, amount}`` dicts where kind is one
of visa / mastercard / amex / discover / jcb / diners / unionpay /
cash / check / gift_card / store_credit / apple_pay / google_pay /
samsung_pay / paypal / venmo / cashapp / zelle / card / credit /
debit / ebt.

Safety: surfaces ONLY when 2+ distinct tender LINES are found so
dashboards can rely on ``len(tenders) > 0`` meaning a real
split-tender breakdown. Single-tender receipts use the existing
``payment_method`` / ``tendered`` slots instead.
"""
from __future__ import annotations

from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract import enrich_receipt
from shotclassify_extract.receipt import _find_tenders


def _enrich(text: str) -> ReceiptFields:
    return enrich_receipt(None, OCRResult(text=text))


# ---- Basic 2-tender splits ----------------------------------------


def test_visa_plus_cash():
    text = "Visa: 25.00\nCash: 10.00\nTotal: 35.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "visa", "amount": 25.00},
        {"kind": "cash", "amount": 10.00},
    ]


def test_mastercard_plus_amex():
    text = "Mastercard: 50.00\nAmex: 75.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "mastercard", "amount": 50.00},
        {"kind": "amex", "amount": 75.00},
    ]


def test_gift_card_plus_visa():
    """Gift Card multi-word form wins over bare Card."""
    text = "Gift Card: 15.00\nVisa: 10.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "gift_card", "amount": 15.00},
        {"kind": "visa", "amount": 10.00},
    ]


def test_apple_pay_plus_cash():
    text = "Apple Pay: 50.00\nCash: 5.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "apple_pay", "amount": 50.00},
        {"kind": "cash", "amount": 5.00},
    ]


def test_google_pay_plus_credit():
    text = "Google Pay: 30.00\nCredit: 15.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "google_pay", "amount": 30.00},
        {"kind": "credit", "amount": 15.00},
    ]


def test_store_credit_plus_visa():
    text = "Store Credit: 20.00\nVisa: 5.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "store_credit", "amount": 20.00},
        {"kind": "visa", "amount": 5.00},
    ]


# ---- Compound forms beat bare aliases -----------------------------


def test_american_express_beats_amex():
    """``American Express`` matches as ``amex``."""
    text = "American Express: 25.00\nCash: 10.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "amex", "amount": 25.00},
        {"kind": "cash", "amount": 10.00},
    ]


def test_master_card_spaced_form():
    text = "Master Card: 50.00\nCash: 25.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "mastercard", "amount": 50.00},
        {"kind": "cash", "amount": 25.00},
    ]


def test_diners_club_form():
    text = "Diners Club: 50.00\nCash: 10.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "diners", "amount": 50.00},
        {"kind": "cash", "amount": 10.00},
    ]


def test_union_pay_spaced_form():
    text = "Union Pay: 30.00\nCash: 5.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "unionpay", "amount": 30.00},
        {"kind": "cash", "amount": 5.00},
    ]


# ---- Modern payment apps ------------------------------------------


def test_paypal_plus_card():
    text = "PayPal: 40.00\nCard: 10.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "paypal", "amount": 40.00},
        {"kind": "card", "amount": 10.00},
    ]


def test_venmo_plus_cash():
    text = "Venmo: 30.00\nCash: 5.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "venmo", "amount": 30.00},
        {"kind": "cash", "amount": 5.00},
    ]


def test_zelle_plus_visa():
    text = "Zelle: 100.00\nVisa: 50.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "zelle", "amount": 100.00},
        {"kind": "visa", "amount": 50.00},
    ]


def test_cashapp_plus_cash():
    text = "Cash App: 25.00\nCash: 10.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "cashapp", "amount": 25.00},
        {"kind": "cash", "amount": 10.00},
    ]


def test_samsung_pay_plus_credit():
    text = "Samsung Pay: 30.00\nCredit: 15.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "samsung_pay", "amount": 30.00},
        {"kind": "credit", "amount": 15.00},
    ]


# ---- Restaurant split-bill multiple cards -------------------------


def test_three_card_split():
    text = (
        "Visa: 33.00\n"
        "Mastercard: 33.00\n"
        "Amex: 34.00\n"
        "Total: 100.00"
    )
    out = _find_tenders(text)
    assert out == [
        {"kind": "visa", "amount": 33.00},
        {"kind": "mastercard", "amount": 33.00},
        {"kind": "amex", "amount": 34.00},
    ]


def test_four_split_bill():
    text = (
        "Visa: 25.00\n"
        "Mastercard: 25.00\n"
        "Amex: 25.00\n"
        "Discover: 25.00"
    )
    out = _find_tenders(text)
    assert len(out) == 4
    kinds = [e["kind"] for e in out]
    assert kinds == ["visa", "mastercard", "amex", "discover"]


# ---- Masked-PAN form (common on restaurant slips) -----------------


def test_visa_masked_pan_with_amount():
    text = (
        "Visa **** 1234: 25.00\n"
        "Cash: 10.00"
    )
    out = _find_tenders(text)
    assert out == [
        {"kind": "visa", "amount": 25.00},
        {"kind": "cash", "amount": 10.00},
    ]


def test_mastercard_masked_pan_with_dash():
    text = (
        "Mastercard ** 5678 - 50.00\n"
        "Amex **** 1234 - 25.00"
    )
    out = _find_tenders(text)
    assert out == [
        {"kind": "mastercard", "amount": 50.00},
        {"kind": "amex", "amount": 25.00},
    ]


def test_amex_xxxx_masked_pan():
    text = (
        "Amex XXXX 1234: 33.00\n"
        "Visa XXXX 5678: 67.00"
    )
    out = _find_tenders(text)
    assert out == [
        {"kind": "amex", "amount": 33.00},
        {"kind": "visa", "amount": 67.00},
    ]


def test_dotted_masked_pan():
    text = (
        "Visa ....1234: 50.00\n"
        "Cash: 10.00"
    )
    out = _find_tenders(text)
    assert out == [
        {"kind": "visa", "amount": 50.00},
        {"kind": "cash", "amount": 10.00},
    ]


# ---- Currency / decimal handling ----------------------------------


def test_currency_symbol_dollar():
    text = "Visa: $25.00\nCash: $10.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "visa", "amount": 25.00},
        {"kind": "cash", "amount": 10.00},
    ]


def test_currency_symbol_euro():
    text = "Visa: €25,00\nCash: €10,00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "visa", "amount": 25.00},
        {"kind": "cash", "amount": 10.00},
    ]


def test_thousands_separator_us():
    text = "Visa: 1,234.56\nMastercard: 500.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "visa", "amount": 1234.56},
        {"kind": "mastercard", "amount": 500.00},
    ]


def test_thousands_separator_eu():
    text = "Visa: 1.234,56\nMastercard: 500,00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "visa", "amount": 1234.56},
        {"kind": "mastercard", "amount": 500.00},
    ]


def test_negative_sign_stripped():
    """Field semantic is positive amount; leading - is stripped."""
    text = "Visa: -25.00\nCash: 10.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "visa", "amount": 25.00},
        {"kind": "cash", "amount": 10.00},
    ]


# ---- Single-tender returns empty ----------------------------------


def test_single_visa_returns_empty():
    """Single tender doesn't surface -- payment_method/tendered slot
    already handles single-tender receipts."""
    text = "Visa: 25.00\nTotal: 25.00"
    out = _find_tenders(text)
    assert out == []


def test_single_cash_returns_empty():
    text = "Cash: 100.00\nTotal: 100.00"
    out = _find_tenders(text)
    assert out == []


def test_single_apple_pay_returns_empty():
    text = "Apple Pay: 30.00"
    out = _find_tenders(text)
    assert out == []


# ---- Duplicate dedupe ---------------------------------------------


def test_dedupe_same_kind_same_amount():
    """Same (kind, amount) printed twice (header + footer echo)
    collapses to one entry; net result is 1 tender so list is
    empty because we require 2+ distinct."""
    text = "Visa: 25.00\n... summary ...\nVisa: 25.00"
    out = _find_tenders(text)
    assert out == []  # dedupe -> 1 entry -> rejected


def test_same_kind_different_amount_both_kept():
    """Two distinct visa charges (different amounts) both surface."""
    text = "Visa: 25.00\nVisa: 50.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "visa", "amount": 25.00},
        {"kind": "visa", "amount": 50.00},
    ]


# ---- Catalogue ordering (multi-word wins) -------------------------


def test_gift_card_not_card():
    """``Gift Card`` matches as gift_card, NOT as bare card."""
    text = "Gift Card: 15.00\nVisa: 10.00"
    out = _find_tenders(text)
    assert out[0]["kind"] == "gift_card"


def test_credit_card_matches_credit():
    """``Credit Card`` matches as credit (multi-word catch)."""
    text = "Credit Card: 50.00\nCash: 10.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "credit", "amount": 50.00},
        {"kind": "cash", "amount": 10.00},
    ]


def test_debit_card_matches_debit():
    text = "Debit Card: 30.00\nCash: 10.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "debit", "amount": 30.00},
        {"kind": "cash", "amount": 10.00},
    ]


# ---- Cap enforcement ----------------------------------------------


def test_cap_at_10_entries():
    """Output is capped at 10 entries even when more tenders are
    present (unlikely but safety guarantee)."""
    lines = [f"Visa: {i + 1}.00" for i in range(15)]
    text = "\n".join(lines)
    out = _find_tenders(text)
    assert len(out) <= 10


# ---- Prose / non-receipt rejection --------------------------------


def test_bare_prose_with_keyword_rejected():
    """``I lost my visa card today`` -- no amount, no tender."""
    text = "I lost my visa card today and called the bank"
    out = _find_tenders(text)
    assert out == []


def test_keyword_without_amount_rejected():
    """``Visa\\nThanks for shopping`` -- keyword without amount on
    SAME line doesn't fire."""
    text = "Visa\nThanks for shopping"
    out = _find_tenders(text)
    assert out == []


def test_two_keywords_without_amounts_rejected():
    """Even multiple keywords without amounts on same line don't
    fire because we require keyword+amount on the same line."""
    text = "Visa\nMastercard\nThanks"
    out = _find_tenders(text)
    assert out == []


# ---- Real-world realistic content --------------------------------


def test_realistic_restaurant_split_bill():
    text = (
        "Restaurant Receipt\n"
        "Server: Alice\n"
        "Date: 2024-02-15\n"
        "Subtotal: 100.00\n"
        "Tax: 8.00\n"
        "Total: 108.00\n"
        "\n"
        "Split Payment:\n"
        "Visa **** 1234: 54.00\n"
        "Mastercard **** 5678: 54.00\n"
    )
    out = _find_tenders(text)
    assert out == [
        {"kind": "visa", "amount": 54.00},
        {"kind": "mastercard", "amount": 54.00},
    ]


def test_realistic_grocery_split():
    """Grocery store: gift card + EBT + cash."""
    text = (
        "Whole Foods Market\n"
        "Total: 87.50\n"
        "Gift Card: 50.00\n"
        "EBT: 25.00\n"
        "Cash: 12.50\n"
    )
    out = _find_tenders(text)
    assert out == [
        {"kind": "gift_card", "amount": 50.00},
        {"kind": "ebt", "amount": 25.00},
        {"kind": "cash", "amount": 12.50},
    ]


def test_realistic_chinese_restaurant():
    """Common in Asia: UnionPay + cash."""
    text = (
        "Bill Total: 120.00\n"
        "UnionPay: 80.00\n"
        "Cash: 40.00\n"
    )
    out = _find_tenders(text)
    assert out == [
        {"kind": "unionpay", "amount": 80.00},
        {"kind": "cash", "amount": 40.00},
    ]


def test_realistic_apple_pay_split():
    """Modern split: Apple Pay + Cash for a group bill."""
    text = (
        "Total: 65.50\n"
        "Apple Pay: 50.00\n"
        "Cash: 15.50\n"
    )
    out = _find_tenders(text)
    assert out == [
        {"kind": "apple_pay", "amount": 50.00},
        {"kind": "cash", "amount": 15.50},
    ]


# ---- Field integration on ReceiptFields ---------------------------


def test_receipt_fields_populated():
    text = (
        "Visa: 25.00\n"
        "Cash: 10.00\n"
        "Total: 35.00"
    )
    fields = _enrich(text)
    assert fields.tenders == [
        {"kind": "visa", "amount": 25.00},
        {"kind": "cash", "amount": 10.00},
    ]


def test_receipt_fields_empty_when_single_tender():
    """ReceiptFields.tenders is empty list when only one tender."""
    text = "Visa: 25.00\nTotal: 25.00"
    fields = _enrich(text)
    assert fields.tenders == []


def test_receipt_fields_backfill_when_caller_empty():
    """When the LLM supplied no tenders, the regex backfills."""
    existing = ReceiptFields()
    merged = enrich_receipt(
        existing,
        OCRResult(text="Visa: 25.00\nCash: 10.00\nTotal: 35.00"),
    )
    assert len(merged.tenders) == 2


def test_receipt_fields_preserve_caller_tenders():
    """When the LLM supplied tenders, the regex must NOT overwrite."""
    existing = ReceiptFields(
        tenders=[{"kind": "visa", "amount": 50.00}],
    )
    merged = enrich_receipt(
        existing,
        OCRResult(text="Visa: 25.00\nCash: 10.00\nTotal: 35.00"),
    )
    # Caller's single-tender preserved -- regex doesn't overwrite.
    assert merged.tenders == [{"kind": "visa", "amount": 50.00}]


def test_visa_plus_paypal_with_payment_method_coexist():
    """tenders and payment_method CAN coexist -- one carries the
    breakdown, the other carries the dominant tender."""
    text = (
        "Order Total: 35.00\n"
        "PayPal: 25.00\n"
        "Visa: 10.00\n"
        "Paid by Visa"
    )
    fields = _enrich(text)
    assert len(fields.tenders) == 2
    assert fields.payment_method == "visa"


# ---- Check / cheque normalisation --------------------------------


def test_check_us_form():
    text = "Check: 100.00\nCash: 50.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "check", "amount": 100.00},
        {"kind": "cash", "amount": 50.00},
    ]


def test_cheque_uk_form_normalised_to_check():
    text = "Cheque: 100.00\nCash: 50.00"
    out = _find_tenders(text)
    assert out == [
        {"kind": "check", "amount": 100.00},
        {"kind": "cash", "amount": 50.00},
    ]
