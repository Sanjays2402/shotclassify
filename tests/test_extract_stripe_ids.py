"""Cross-category Stripe ID extractor tests.

A new cross-category extractor surfaces Stripe object IDs
(customer / charge / payment_intent / invoice / subscription /
product / price / account / refund / payment_method / setup_intent /
checkout_session / transfer / payout / balance_transaction / file /
coupon / promotion_code / invoice_item / credit_note / tax_rate /
subscription_item / source / token) found in the OCR text under
``ExtractedFields.raw["stripe_ids"]``.

Output shape: list of ``{"kind", "id"}`` dicts. The kind tag is the
long-form name of the prefix so downstream consumers don't need to
maintain their own prefix-to-name table.

Shape rules:

* Lowercase Stripe prefix from the recognised catalogue, followed by
  underscore, then 16..32 alphanumeric chars. Word-boundary isolation
  on both ends so an embedded substring inside a longer ID does not
  misfire.
* Test-mode IDs (``cus_test_xyz``) are accepted because ``test_``
  counts toward the alphanumeric tail.
* Output preserves first-seen order, dedupes on ``id`` value, capped
  at 50.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_stripe_ids

# ---- Basic kind detection -----------------------------------------


def test_customer_id():
    out = extract_stripe_ids("Customer cus_NffrFeUfNV2Hib in dashboard")
    assert out == [{"kind": "customer", "id": "cus_NffrFeUfNV2Hib"}]


def test_charge_id():
    out = extract_stripe_ids("See ch_3MtwBwLkdIwHu7ix28a3tqPa")
    assert out == [{"kind": "charge", "id": "ch_3MtwBwLkdIwHu7ix28a3tqPa"}]


def test_payment_intent_id():
    out = extract_stripe_ids("pi_3MtwBwLkdIwHu7ix28a3tqPa")
    assert out == [{"kind": "payment_intent", "id": "pi_3MtwBwLkdIwHu7ix28a3tqPa"}]


def test_invoice_id():
    out = extract_stripe_ids("Invoice inv_1MtAUgLkdIwHu7ixIeoYxXJK")
    assert out == [{"kind": "invoice", "id": "inv_1MtAUgLkdIwHu7ixIeoYxXJK"}]


def test_subscription_id():
    out = extract_stripe_ids("Subscription sub_1MtwBwLkdIwHu7ixaBcDeFGh")
    assert out == [{"kind": "subscription", "id": "sub_1MtwBwLkdIwHu7ixaBcDeFGh"}]


def test_product_id():
    out = extract_stripe_ids("prod_NWjsdLjVUyTW8R")
    assert out == [{"kind": "product", "id": "prod_NWjsdLjVUyTW8R"}]


def test_price_id():
    out = extract_stripe_ids("price_1MoBy5LkdIwHu7ixZhnattbH")
    assert out == [{"kind": "price", "id": "price_1MoBy5LkdIwHu7ixZhnattbH"}]


def test_account_id():
    out = extract_stripe_ids("Connect account acct_1Hh5xJLkdIwHu7ix")
    assert out == [{"kind": "account", "id": "acct_1Hh5xJLkdIwHu7ix"}]


def test_refund_id():
    out = extract_stripe_ids("Refund re_1MtwBwLkdIwHu7ixaBcDeFGh")
    assert out == [{"kind": "refund", "id": "re_1MtwBwLkdIwHu7ixaBcDeFGh"}]


def test_payment_method_id():
    out = extract_stripe_ids("PaymentMethod pm_1MtwBwLkdIwHu7ixaBcDeFGh")
    assert out == [{"kind": "payment_method", "id": "pm_1MtwBwLkdIwHu7ixaBcDeFGh"}]


def test_setup_intent_id():
    out = extract_stripe_ids("SetupIntent seti_1MtwBwLkdIwHu7ixaBcDeFGh")
    assert out == [{"kind": "setup_intent", "id": "seti_1MtwBwLkdIwHu7ixaBcDeFGh"}]


def test_checkout_session_id():
    out = extract_stripe_ids("Checkout cs_test_a1MtwBwLkdIwHu7ixaBcDeFGh")
    assert out == [
        {"kind": "checkout_session", "id": "cs_test_a1MtwBwLkdIwHu7ixaBcDeFGh"}
    ]


def test_transfer_id():
    out = extract_stripe_ids("Transfer tr_1MtwBwLkdIwHu7ixaBcDeFGh")
    assert out == [{"kind": "transfer", "id": "tr_1MtwBwLkdIwHu7ixaBcDeFGh"}]


def test_payout_id():
    out = extract_stripe_ids("Payout po_1MtwBwLkdIwHu7ixaBcDeFGh")
    assert out == [{"kind": "payout", "id": "po_1MtwBwLkdIwHu7ixaBcDeFGh"}]


def test_balance_transaction_id():
    out = extract_stripe_ids("Balance txn_1MtwBwLkdIwHu7ixaBcDeFGh")
    assert out == [{"kind": "balance_transaction", "id": "txn_1MtwBwLkdIwHu7ixaBcDeFGh"}]


def test_file_id():
    out = extract_stripe_ids("Uploaded file_1MtwBwLkdIwHu7ixaBcDeFGh")
    assert out == [{"kind": "file", "id": "file_1MtwBwLkdIwHu7ixaBcDeFGh"}]


def test_coupon_id():
    out = extract_stripe_ids("Apply coupon_1MtwBwLkdIwHu7ixaBc")
    assert out == [{"kind": "coupon", "id": "coupon_1MtwBwLkdIwHu7ixaBc"}]


def test_promotion_code_id():
    out = extract_stripe_ids("Use promo_1MtwBwLkdIwHu7ixaBcDeFGh")
    assert out == [{"kind": "promotion_code", "id": "promo_1MtwBwLkdIwHu7ixaBcDeFGh"}]


def test_invoice_item_id():
    out = extract_stripe_ids("LineItem ii_1MtAUgLkdIwHu7ixIeoYxXJK")
    assert out == [{"kind": "invoice_item", "id": "ii_1MtAUgLkdIwHu7ixIeoYxXJK"}]


def test_credit_note_id():
    out = extract_stripe_ids("CreditNote cn_1MtAUgLkdIwHu7ixIeoYxXJK")
    assert out == [{"kind": "credit_note", "id": "cn_1MtAUgLkdIwHu7ixIeoYxXJK"}]


def test_tax_rate_id():
    out = extract_stripe_ids("TaxRate txr_1MtAUgLkdIwHu7ixIeoYxXJK")
    assert out == [{"kind": "tax_rate", "id": "txr_1MtAUgLkdIwHu7ixIeoYxXJK"}]


def test_subscription_item_id():
    out = extract_stripe_ids("SubItem si_NffrFeUfNV2HibcdEFgh")
    assert out == [{"kind": "subscription_item", "id": "si_NffrFeUfNV2HibcdEFgh"}]


def test_source_id():
    out = extract_stripe_ids("LegacySource src_1MtwBwLkdIwHu7ixaBcDeFGh")
    assert out == [{"kind": "source", "id": "src_1MtwBwLkdIwHu7ixaBcDeFGh"}]


def test_token_id():
    out = extract_stripe_ids("Token tok_1MtwBwLkdIwHu7ixaBcDeFGh")
    assert out == [{"kind": "token", "id": "tok_1MtwBwLkdIwHu7ixaBcDeFGh"}]


# ---- Longest-prefix wins -----------------------------------------


def test_seti_wins_over_si_prefix():
    # ``seti_`` must NOT be misclassified as ``si_`` (subscription_item)
    # plus stray ``et`` in the tail. The longest-first prefix table
    # in the matcher is the defence.
    out = extract_stripe_ids("SetupIntent seti_1NABCDefGhiJkLmnOpQrStUv")
    assert out == [
        {"kind": "setup_intent", "id": "seti_1NABCDefGhiJkLmnOpQrStUv"}
    ]


def test_promo_wins_over_pm_prefix():
    # ``promo_`` must NOT be misclassified as ``pm_`` (payment_method)
    # plus stray ``romo_`` -- the underscore boundary protects this
    # naturally because the regex requires the underscore AT the
    # prefix end. The longest-first table is still belt-and-braces.
    out = extract_stripe_ids("PromoCode promo_1MtwBwLkdIwHu7ixaBc")
    assert out == [{"kind": "promotion_code", "id": "promo_1MtwBwLkdIwHu7ixaBc"}]


def test_prod_wins_over_pi_prefix_substring():
    # ``prod_`` matches first because the regex matches the full
    # prefix-with-underscore + alphanumeric tail in one shot.
    out = extract_stripe_ids("Product prod_NWjsdLjVUyTW8R")
    assert out == [{"kind": "product", "id": "prod_NWjsdLjVUyTW8R"}]


# ---- Test-mode IDs accepted --------------------------------------


def test_test_mode_customer():
    out = extract_stripe_ids("Test cus_test_NffrFeUfNV2Hib")
    assert out == [{"kind": "customer", "id": "cus_test_NffrFeUfNV2Hib"}]


def test_test_mode_charge():
    out = extract_stripe_ids("Test ch_test_3MtwBwLkdIwHu7ix28a3tqPa")
    assert out == [{"kind": "charge", "id": "ch_test_3MtwBwLkdIwHu7ix28a3tqPa"}]


def test_test_mode_payment_intent():
    out = extract_stripe_ids("Test pi_test_3MtwBwLkdIwHu7ix28a3tqPa")
    assert out == [{"kind": "payment_intent", "id": "pi_test_3MtwBwLkdIwHu7ix28a3tqPa"}]


# ---- Word-boundary defence ---------------------------------------


def test_embedded_substring_rejected():
    # An ID embedded inside a longer alphanumeric blob without a
    # word boundary on the left should NOT misfire.
    out = extract_stripe_ids("XXXcus_NffrFeUfNV2HibAAA")
    assert out == []


def test_underscore_prefix_breaks_word_boundary():
    # ``_cus_NffrFeUfNV2Hib`` has a leading underscore which counts
    # as non-word for our boundary -- but we also forbid leading
    # underscore on the left because Stripe IDs don't sit inside
    # other typed prefixes.
    out = extract_stripe_ids("foo_cus_NffrFeUfNV2HibQRS")
    assert out == []


def test_trailing_alphanumeric_breaks_boundary():
    # Trailing alphanumerics extend the tail (so it may exceed the 32
    # cap and reject); we test the boundary defence specifically.
    out = extract_stripe_ids("cus_NffrFeUfNV2Hib_extra")
    assert out == []


def test_too_short_rejected():
    # 13 chars in the tail is below our 14-char minimum.
    out = extract_stripe_ids("cus_NffrFeUfNV2H")
    assert out == []


def test_too_long_rejected():
    # 41 chars in the tail is above our 40-char maximum.
    out = extract_stripe_ids("cus_" + "a" * 41)
    assert out == []


# ---- Multiple IDs in one text -----------------------------------


def test_multiple_kinds_one_line():
    text = (
        "Customer cus_NffrFeUfNV2Hib charged via "
        "pi_3MtwBwLkdIwHu7ix28a3tqPa generated "
        "inv_1MtAUgLkdIwHu7ixIeoYxXJK"
    )
    out = extract_stripe_ids(text)
    assert {x["kind"] for x in out} == {"customer", "payment_intent", "invoice"}
    assert len(out) == 3


def test_preserves_first_seen_order():
    text = (
        "inv_1MtAUgLkdIwHu7ixIeoYxXJK\n"
        "cus_NffrFeUfNV2Hib\n"
        "pi_3MtwBwLkdIwHu7ix28a3tqPa\n"
    )
    out = extract_stripe_ids(text)
    assert [x["id"] for x in out] == [
        "inv_1MtAUgLkdIwHu7ixIeoYxXJK",
        "cus_NffrFeUfNV2Hib",
        "pi_3MtwBwLkdIwHu7ix28a3tqPa",
    ]


def test_dedupes_same_id():
    text = (
        "Customer cus_NffrFeUfNV2Hib paid.\n"
        "Refund issued to cus_NffrFeUfNV2Hib.\n"
    )
    out = extract_stripe_ids(text)
    assert out == [{"kind": "customer", "id": "cus_NffrFeUfNV2Hib"}]


def test_cap_at_50():
    # 60 distinct customer IDs; output must cap at 50.
    text = " ".join(
        f"cus_{i:04d}abcdefghij{i:06d}" for i in range(60)
    )
    out = extract_stripe_ids(text)
    assert len(out) == 50


# ---- Rejection tests ---------------------------------------------


def test_uppercase_prefix_rejected():
    # Stripe prefixes are lowercase by convention; uppercase rejected.
    out = extract_stripe_ids("CUS_NffrFeUfNV2HibQRSTU")
    assert out == []


def test_missing_underscore_rejected():
    # ``cusNffrFeUfNV2Hib`` (no underscore) doesn't satisfy the
    # prefix + underscore shape.
    out = extract_stripe_ids("cusNffrFeUfNV2HibQRSTU")
    assert out == []


def test_unknown_prefix_rejected():
    # ``foo_`` is not in our catalogue and must not appear in output.
    out = extract_stripe_ids("foo_1MtwBwLkdIwHu7ixaBcDeFGh")
    assert out == []


def test_empty_text():
    assert extract_stripe_ids("") == []
    assert extract_stripe_ids("   ") == []
    assert extract_stripe_ids(None) == []  # type: ignore[arg-type]


def test_no_stripe_ids():
    text = "Just some prose with email user@example.com and url https://x.io"
    assert extract_stripe_ids(text) == []


# ---- Pipeline integration ----------------------------------------


def test_pipeline_writes_raw_stripe_ids():
    text = "Customer cus_NffrFeUfNV2Hib charged $50"
    ocr = OCRResult(text=text)
    out = enrich(Category.receipt, ExtractedFields(), ocr)
    assert out.raw is not None
    assert "stripe_ids" in out.raw
    assert out.raw["stripe_ids"] == [
        {"kind": "customer", "id": "cus_NffrFeUfNV2Hib"}
    ]


def test_pipeline_no_raw_key_when_no_ids():
    text = "Just an email user@example.com"
    ocr = OCRResult(text=text)
    out = enrich(Category.receipt, ExtractedFields(), ocr)
    # No Stripe IDs present, so raw["stripe_ids"] should not be set
    if out.raw is not None:
        assert "stripe_ids" not in out.raw


def test_pipeline_writes_for_every_category():
    text = "PaymentIntent pi_3MtwBwLkdIwHu7ix28a3tqPa failed"
    ocr = OCRResult(text=text)
    for cat in Category:
        out = enrich(cat, ExtractedFields(), ocr)
        assert out.raw is not None
        assert "stripe_ids" in out.raw
        assert out.raw["stripe_ids"] == [
            {"kind": "payment_intent", "id": "pi_3MtwBwLkdIwHu7ix28a3tqPa"}
        ]


# ---- Real-world contexts -----------------------------------------


def test_url_context():
    text = "https://dashboard.stripe.com/customers/cus_NffrFeUfNV2Hib"
    out = extract_stripe_ids(text)
    assert out == [{"kind": "customer", "id": "cus_NffrFeUfNV2Hib"}]


def test_json_payload_context():
    text = '{"id": "pi_3MtwBwLkdIwHu7ix28a3tqPa", "status": "succeeded"}'
    out = extract_stripe_ids(text)
    assert out == [
        {"kind": "payment_intent", "id": "pi_3MtwBwLkdIwHu7ix28a3tqPa"}
    ]


def test_error_log_context():
    text = (
        "ERROR: Customer cus_NffrFeUfNV2Hib has no default source\n"
        "WARN: payment pi_3MtwBwLkdIwHu7ix28a3tqPa declined\n"
    )
    out = extract_stripe_ids(text)
    assert len(out) == 2
    ids = {x["id"] for x in out}
    assert "cus_NffrFeUfNV2Hib" in ids
    assert "pi_3MtwBwLkdIwHu7ix28a3tqPa" in ids
