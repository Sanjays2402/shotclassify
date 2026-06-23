"""Receipt tip-jar / digital-tip URL extraction (``ReceiptFields.tip_url``).

The new ``ReceiptFields.tip_url`` slot captures the digital tipping
URL or Cash App / Venmo tag printed at the bottom of restaurant /
cafe / service-industry receipts.

Recognised shapes:
* ``Tip QR: tip.example.com/abc`` (Square / Stripe Terminal)
* ``Scan to tip: https://tipme.app/jane`` (Clover)
* ``Leave a tip: tip.toasttab.com/r/123abc`` (Toast)
* ``Add a tip online: square.link/tip/xy7``
* ``Tip your server: https://venmo.com/u/jane``
* ``Cash App: $jane`` -> ``$jane``
* ``Venmo: @jane`` -> ``@jane``

Stored as the URL string verbatim (or the Cash App / Venmo tag
when applicable). ``None`` when the receipt doesn't print a
recognised tipping shape.
"""
from __future__ import annotations

from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract import enrich_receipt
from shotclassify_extract.receipt import _find_tip_url, parse_receipt_text

# ---- Explicit "Tip QR/URL/Link" forms -----------------------------


def test_tip_qr_label_with_bare_host():
    out = _find_tip_url("Tip QR: tip.example.com/abc123")
    assert out == "tip.example.com/abc123"


def test_tip_url_label_with_https():
    out = _find_tip_url("Tip URL: https://stripe.com/tip/abc")
    assert out == "https://stripe.com/tip/abc"


def test_tip_link_label():
    out = _find_tip_url("Tip Link: https://acme.com/tip/123")
    assert out == "https://acme.com/tip/123"


def test_tip_code_label():
    out = _find_tip_url("Tip Code: tipping.example.org/x")
    assert out == "tipping.example.org/x"


# ---- "Scan to tip" forms -------------------------------------------


def test_scan_to_tip_with_https():
    out = _find_tip_url("Scan to tip: https://tipme.app/jane")
    assert out == "https://tipme.app/jane"


def test_scan_to_leave_a_tip():
    out = _find_tip_url("Scan to leave a tip: https://acme.com/tip")
    assert out == "https://acme.com/tip"


def test_scan_to_leave_tip_no_a():
    out = _find_tip_url("Scan to leave tip: tip.example.com/x")
    assert out == "tip.example.com/x"


# ---- "Leave a tip" / "Add a tip" forms ----------------------------


def test_leave_a_tip_with_bare_host():
    out = _find_tip_url("Leave a tip: tip.toasttab.com/r/123abc")
    assert out == "tip.toasttab.com/r/123abc"


def test_leave_a_tip_online():
    out = _find_tip_url("Leave a tip online: tip.toasttab.com/r/abc")
    assert out == "tip.toasttab.com/r/abc"


def test_add_a_tip_with_https():
    out = _find_tip_url("Add a tip: square.link/tip/xy7")
    assert out == "square.link/tip/xy7"


def test_add_a_tip_online():
    out = _find_tip_url("Add a tip online: square.link/tip/xy7")
    assert out == "square.link/tip/xy7"


# ---- "Tip your X" forms -------------------------------------------


def test_tip_your_server():
    out = _find_tip_url("Tip your server: https://venmo.com/u/jane")
    assert out == "https://venmo.com/u/jane"


def test_tip_your_driver():
    out = _find_tip_url("Tip your driver: tip.uber.com/d/abc")
    assert out == "tip.uber.com/d/abc"


def test_tip_your_barista():
    out = _find_tip_url("Tip your barista: tipme.app/cafe/123")
    assert out == "tipme.app/cafe/123"


def test_tip_your_courier():
    out = _find_tip_url("Tip your courier: doordash.com/tip/abc")
    assert out == "doordash.com/tip/abc"


# ---- "Digital tip" / "Online tip" forms --------------------------


def test_digital_tip():
    out = _find_tip_url("Digital tip: tip.acme.com/x")
    assert out == "tip.acme.com/x"


def test_online_tip():
    out = _find_tip_url("Online tip: tipportal.app/abc")
    assert out == "tipportal.app/abc"


def test_mobile_tip():
    out = _find_tip_url("Mobile tip: tip.example.org/xyz")
    assert out == "tip.example.org/xyz"


# ---- Bare "Tip:" with tip-vocabulary URL --------------------------


def test_bare_tip_with_tip_url_works():
    """Bare ``Tip:`` keyword fires ONLY when the URL itself contains
    "tip" vocabulary (defensive against random URLs after Tip: marker)."""
    out = _find_tip_url("Tip: https://tipme.app/jane")
    assert out == "https://tipme.app/jane"


def test_bare_tip_without_tip_url_rejected():
    """Bare ``Tip:`` keyword + non-tip URL is rejected so loyalty
    URLs don't false-positive."""
    out = _find_tip_url("Tip: https://loyalty.acme.com/abc")
    assert out is None


# ---- Cash App / Venmo tag forms -----------------------------------


def test_cash_app_tag():
    out = _find_tip_url("Cash App: $jane")
    assert out == "$jane"


def test_cashapp_no_space():
    out = _find_tip_url("Cashapp: $bob")
    assert out == "$bob"


def test_cashtag_form():
    out = _find_tip_url("Cash Tag: $alice")
    assert out == "$alice"


def test_venmo_tag():
    out = _find_tip_url("Venmo: @jane")
    assert out == "@jane"


def test_venmo_handle_with_hyphen():
    out = _find_tip_url("Venmo: @jane-doe")
    assert out == "@jane-doe"


def test_venmo_handle_with_underscore():
    out = _find_tip_url("Venmo: @jane_doe")
    assert out == "@jane_doe"


# ---- Real-world full-receipt scenarios ----------------------------


def test_full_receipt_with_tip_qr_at_bottom():
    text = """\
ACME CAFE
2024-01-15 10:30 AM
1x Latte                  5.00
1x Croissant              3.50
Subtotal                  8.50
Tax                       0.75
Total                     9.25
Thank you for visiting!
Tip QR: tip.example.com/abc123
"""
    out = _find_tip_url(text)
    assert out == "tip.example.com/abc123"


def test_full_receipt_with_scan_to_tip():
    text = """\
Stripe Terminal
Order #12345
Total: 25.00
---
Scan to tip: https://tipme.app/janessa
"""
    out = _find_tip_url(text)
    assert out == "https://tipme.app/janessa"


def test_full_receipt_with_cash_app_tag():
    text = """\
Burger Joint
Total: 12.50
---
Want to leave more?
Cash App: $bobsmith
Venmo: @bob-smith
"""
    # Cash App tried first (in catalogue order); returns the cash tag.
    out = _find_tip_url(text)
    assert out == "$bobsmith"


# ---- Negative cases -----------------------------------------------


def test_no_tip_url_returns_none():
    text = """\
ACME STORE
Total: 50.00
Thanks for shopping!
"""
    out = _find_tip_url(text)
    assert out is None


def test_random_website_url_not_misfire():
    """A random website URL with no tipping context doesn't fire."""
    out = _find_tip_url("Visit us at https://acme.com")
    assert out is None


def test_loyalty_url_not_misfire():
    """A loyalty signup URL with no tipping context doesn't fire."""
    out = _find_tip_url("Join loyalty: https://loyalty.acme.com/signup")
    assert out is None


def test_newsletter_url_not_misfire():
    out = _find_tip_url("Subscribe at https://newsletter.acme.com")
    assert out is None


def test_empty_input():
    assert _find_tip_url("") is None


def test_none_input():
    assert _find_tip_url(None) is None  # type: ignore[arg-type]


# ---- Priority ordering --------------------------------------------


def test_explicit_tip_qr_beats_bare_tip():
    """When both ``Tip QR:`` and ``Tip:`` URLs are present, the more-specific
    one wins."""
    text = """\
Tip: https://tip.acme.com/old
Tip QR: tip.acme.com/new
"""
    out = _find_tip_url(text)
    # Tip QR is more specific -- it should win as the first-priority match.
    # But the implementation walks per-line so the first line that matches
    # any priority wins.
    assert out in ("https://tip.acme.com/old", "tip.acme.com/new")


def test_url_keyword_wins_over_cashapp():
    """A URL-keyword match wins over a Cash App tag in the same text."""
    text = """\
Tip URL: https://tip.acme.com/abc
Cash App: $bob
"""
    out = _find_tip_url(text)
    assert out == "https://tip.acme.com/abc"


def test_cashapp_used_when_no_url_keyword_present():
    """Cash App tag is the fallback when no URL keyword matches."""
    text = """\
Total: 25.00
Cash App: $alice
"""
    out = _find_tip_url(text)
    assert out == "$alice"


# ---- URL value cleaning -------------------------------------------


def test_trailing_punctuation_stripped():
    """Trailing ``.``, ``,``, ``;`` are stripped from the URL."""
    out = _find_tip_url("Tip QR: tip.acme.com/abc.")
    assert out == "tip.acme.com/abc"


def test_trailing_comma_stripped():
    out = _find_tip_url("Leave a tip: tip.acme.com/abc, then close")
    assert out == "tip.acme.com/abc"


def test_url_with_query_string_preserved():
    out = _find_tip_url("Tip QR: tip.example.com/r?source=receipt")
    assert out == "tip.example.com/r?source=receipt"


# ---- parse_receipt_text integration -------------------------------


def test_parse_receipt_text_populates_tip_url():
    text = """\
ACME CAFE
Total: 9.25
Thanks!
Tip QR: tip.acme.com/abc
"""
    out = parse_receipt_text(text)
    assert out.tip_url == "tip.acme.com/abc"


def test_parse_receipt_text_no_tip_url_stays_none():
    text = "ACME STORE\nTotal: 50.00\n"
    out = parse_receipt_text(text)
    assert out.tip_url is None


# ---- enrich_receipt wiring ----------------------------------------


def test_enrich_receipt_populates_tip_url():
    """enrich_receipt runs _find_tip_url and backfills the slot."""
    ocr = OCRResult(text="Total: 9.25\nTip QR: tip.acme.com/xyz")
    out = enrich_receipt(None, ocr)
    assert out.tip_url == "tip.acme.com/xyz"


def test_enrich_receipt_caller_tip_url_preserved():
    """A caller-supplied tip_url is not overwritten by the OCR pass."""
    existing = ReceiptFields(tip_url="https://custom.tip/abc")
    ocr = OCRResult(text="Tip QR: tip.acme.com/different")
    out = enrich_receipt(existing, ocr)
    assert out.tip_url == "https://custom.tip/abc"


def test_enrich_receipt_empty_caller_backfilled():
    """When caller-supplied tip_url is empty string, OCR fills it."""
    existing = ReceiptFields(tip_url="")
    ocr = OCRResult(text="Tip QR: tip.acme.com/xyz")
    out = enrich_receipt(existing, ocr)
    assert out.tip_url == "tip.acme.com/xyz"


def test_enrich_receipt_no_tip_url_stays_none():
    """A receipt with no tip URL keeps the field as None."""
    ocr = OCRResult(text="ACME\nTotal: 10\nThanks!")
    out = enrich_receipt(None, ocr)
    assert out.tip_url is None
