"""Cross-category Stripe ID extractor.

Stripe assigns each object (customer, charge, payment intent, invoice,
subscription, product, price, account, refund, ...) a typed
"object ID" that surfaces on API responses, dashboard URLs, error
logs, webhook payloads, and (sometimes) chat conversations between
developers. We surface these IDs found in the OCR text under
``ExtractedFields.raw["stripe_ids"]`` so dashboards, routing rules,
and downstream agents have a single place to look for Stripe context.

Output shape: a list of ``{"kind": str, "id": str}`` dicts. The
``kind`` tag is the long-form name of the prefix (``customer`` /
``charge`` / ``payment_intent`` / ``invoice`` / ``subscription`` /
``product`` / ``price`` / ``account`` / ``refund`` / ``payment_method``
/ ``setup_intent`` / ``checkout_session`` / ``transfer`` / ``payout``
/ ``balance_transaction`` / ``file`` / ``coupon`` / ``promotion_code``
/ ``invoice_item`` / ``credit_note`` / ``tax_rate`` / ``subscription_item``
/ ``source`` / ``token``). The list preserves first-seen order and is
capped at 50 entries.

Recognised prefixes (per Stripe's typed-ID convention):

* ``cus_``      -- Customer
* ``ch_``       -- Charge (legacy)
* ``pi_``       -- PaymentIntent
* ``inv_``      -- Invoice
* ``sub_``      -- Subscription
* ``prod_``     -- Product
* ``price_``    -- Price
* ``acct_``     -- Connect account
* ``re_``       -- Refund
* ``pm_``       -- PaymentMethod
* ``seti_``     -- SetupIntent
* ``cs_``       -- Checkout Session
* ``tr_``       -- Transfer
* ``po_``       -- Payout
* ``txn_``      -- Balance transaction
* ``file_``     -- File
* ``coupon_``   -- Coupon (the underscore is part of the prefix)
* ``promo_``    -- PromotionCode
* ``ii_``       -- InvoiceItem
* ``cn_``       -- CreditNote
* ``txr_``      -- TaxRate
* ``si_``       -- SubscriptionItem
* ``src_``      -- Source (legacy charge source)
* ``tok_``      -- Token (legacy single-use payment token)

Shape rules:

* Lowercase prefix from the catalogue, followed by underscore, then
  16..32 alphanumeric chars. Stripe IDs are case-mixed and case-
  significant.
* Word-boundary on both ends so a code-fenced ``foo_cus_abc123``
  embedded inside a longer ID doesn't misfire.
* Test-mode prefix (``cus_test_...``) is accepted -- Stripe uses
  ``_test_`` infix and the ``test_`` segment counts toward the
  alphanumeric tail.
"""
from __future__ import annotations

import re

# Map prefix (without trailing underscore) to the long-form kind tag
# emitted in the output. Order matters for the regex priority pass --
# longer prefixes MUST be tried first so ``promo_`` wins over ``pm_``
# (and ``promo_`` is not a prefix of ``pm_`` either, but the principle
# matters for ``seti_`` vs ``si_`` -- a ``seti_`` would otherwise match
# the ``si_`` prefix and lose the ``et`` suffix).
_KIND_NAMES: dict[str, str] = {
    "cus": "customer",
    "ch": "charge",
    "pi": "payment_intent",
    "inv": "invoice",
    "sub": "subscription",
    "prod": "product",
    "price": "price",
    "acct": "account",
    "re": "refund",
    "pm": "payment_method",
    "seti": "setup_intent",
    "cs": "checkout_session",
    "tr": "transfer",
    "po": "payout",
    "txn": "balance_transaction",
    "file": "file",
    "coupon": "coupon",
    "promo": "promotion_code",
    "ii": "invoice_item",
    "cn": "credit_note",
    "txr": "tax_rate",
    "si": "subscription_item",
    "src": "source",
    "tok": "token",
}

# Build the prefix alternation sorted LONGEST-FIRST so the regex
# engine prefers ``seti`` over ``si``, ``promo`` over ``pm``, etc.
# Python's ``re`` engine uses first-match-wins on alternations so the
# order here is the whole defence against the short prefix stealing a
# longer one.
_PREFIXES_LONGEST_FIRST = sorted(_KIND_NAMES.keys(), key=len, reverse=True)

# Lowercase prefix from the catalogue, then underscore, an optional
# ``test_`` infix segment (Stripe inserts ``test_`` between the type
# prefix and the alphanumeric tail when the object is in test mode),
# then 14..32 alphanumeric chars. Stripe IDs are usually 24 chars in
# the tail; the range absorbs the small variation across object
# types (and legacy short IDs like 14-char customer / product /
# refund IDs). Word-boundary on both sides so a substring inside a
# longer hex/base64 blob doesn't misfire.
_STRIPE_ID_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?P<kind>" + "|".join(_PREFIXES_LONGEST_FIRST) + r")"
    r"_(?P<rest>(?:test_)?[A-Za-z0-9]{14,40})"
    r"(?![A-Za-z0-9_])"
)


_MAX_STRIPE_IDS = 50


def extract_stripe_ids(text: str) -> list[dict[str, str]]:
    """Return unique Stripe IDs found in ``text``.

    Output is a list of ``{"kind", "id"}`` dicts, preserving
    first-seen order across the OCR text. De-duplicates on the
    ``id`` value so the same customer ID printed multiple times in
    the same screenshot collapses to one entry. Caps the output at
    50 entries.

    The matcher requires the canonical lowercase Stripe prefix from
    the catalogue (longest-first to keep ``seti_`` distinct from
    ``si_``) followed by underscore + an optional ``test_`` infix +
    14..40 alphanumeric chars, with word-boundary isolation on both
    ends so a substring inside a longer ID doesn't misfire. Test-mode
    IDs (``cus_test_xyz``) are accepted because the ``test_`` infix
    is recognised explicitly.
    """
    if not text or not isinstance(text, str):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _STRIPE_ID_RE.finditer(text):
        kind_prefix = m.group("kind")
        rest = m.group("rest")
        ident = f"{kind_prefix}_{rest}"
        if ident in seen:
            continue
        seen.add(ident)
        out.append({"kind": _KIND_NAMES[kind_prefix], "id": ident})
        if len(out) >= _MAX_STRIPE_IDS:
            break
    return out


__all__ = ["extract_stripe_ids"]
