"""Currency inference from locale codes (CAD, CHF, AUD, etc.).

The original `_detect_currency` only recognised four symbols ($, €, £,
¥) plus bare "USD" / "EUR" word matches. Real receipts routinely
print three-letter ISO codes near the total (``Total in CAD``,
``Subtotal CHF 12.50``, ``GST AUD 4.00``); this widening covers the
common locales without inventing a heavy locale dependency.

Behaviour:
* Unambiguous symbols win first (``€`` -> EUR, ``£`` -> GBP, ``¥`` -> JPY).
* Three-letter ISO codes match with word boundaries so an embedded
  string like ``scAUDio`` never triggers.
* When multiple ISO codes appear, the LAST one wins (header USD ->
  closing CAD on a tourist receipt is the more meaningful signal).
* ``RMB`` -> normalised to ``CNY`` (CNY is the ISO code; RMB is the
  colloquial Chinese term and many receipts use it interchangeably).
* ``$`` with no explicit ISO code remains USD as a fallback.
"""
from __future__ import annotations

import pytest
from shotclassify_extract.receipt import parse_receipt_text


def _receipt(currency_snippet: str) -> str:
    return f"Cafe\nSubtotal 10.00\nTotal 10.00\n{currency_snippet}\n"


@pytest.mark.parametrize(
    "snippet,expected",
    [
        ("Total in CAD 12.00", "CAD"),
        ("Subtotal CHF 8.50", "CHF"),
        ("Total AUD 22.00", "AUD"),
        ("NZD 5.00", "NZD"),
        ("SEK 100.00", "SEK"),
        ("NOK 99.00", "NOK"),
        ("DKK 50.00", "DKK"),
        ("INR 250.00", "INR"),
        ("MXN 300.00", "MXN"),
        ("BRL 75.00", "BRL"),
        ("ZAR 80.00", "ZAR"),
        ("SGD 17.00", "SGD"),
        ("HKD 89.00", "HKD"),
        ("KRW 12000", "KRW"),
        ("CNY 88.00", "CNY"),
        ("RMB 88.00", "CNY"),  # normalised
    ],
)
def test_iso_currency_codes_recognised(snippet, expected):
    parsed = parse_receipt_text(_receipt(snippet))
    assert parsed.currency == expected


def test_iso_code_case_insensitive():
    assert parse_receipt_text(_receipt("total cad 5.00")).currency == "CAD"
    assert parse_receipt_text(_receipt("Total Cad 5.00")).currency == "CAD"


def test_last_iso_code_wins():
    """A header printed in USD followed by a closing total in CAD is
    the tourist-receipt pattern: the latter code is the receipt's
    actual currency, so it must win."""
    text = (
        "International Cafe (USD)\n"
        "Subtotal 8.00\n"
        "Total 8.00\n"
        "Total in CAD 10.40\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.currency == "CAD"


def test_word_boundary_avoids_embedded_letters():
    """``scAUDio`` is embedded inside a longer word; the ``\\b`` regex
    boundary correctly refuses to match it. (We do NOT also test
    ``btn-aud`` because Python's ``\\b`` treats ``-`` as a word
    boundary, which would legitimately match — receipts rarely contain
    HTML class names anyway.)"""
    text = "Vendor\nscAUDio playback notes\nSubtotal 1.00\nTotal 1.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.currency is None


def test_dollar_sign_with_no_iso_remains_usd():
    """The fallback path stays in place: a bare ``$10.00`` receipt
    with no explicit ISO code still classifies as USD."""
    text = "Vendor\nSubtotal $10.00\nTotal $10.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.currency == "USD"


def test_euro_symbol_still_wins():
    text = "Cafe\nSubtotal €5.00\nTotal €5.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.currency == "EUR"


def test_pound_symbol_still_wins():
    text = "Pub\nSubtotal £4.00\nTotal £4.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.currency == "GBP"


def test_yen_symbol_still_wins():
    text = "Ramen\nSubtotal ¥800\nTotal ¥800\n"
    parsed = parse_receipt_text(text)
    assert parsed.currency == "JPY"


def test_no_currency_at_all_returns_none():
    text = "Vendor\nSubtotal 1.00\nTotal 1.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.currency is None


def test_eur_iso_word_match_still_works():
    """Regression for the original bare-word path."""
    text = "Cafe\nTotal EUR 10.00\n"
    parsed = parse_receipt_text(text)
    assert parsed.currency == "EUR"


def test_usd_with_cad_in_body_resolves_to_cad():
    """A receipt that prints both 'USD' once and 'CAD' twice (header +
    total) lands on CAD via last-match. Confirms intent of the new
    locale-code path: explicit ISO code beats the dollar-sign fallback."""
    text = (
        "USD Conversion Cafe\n"
        "Subtotal 7.00\n"
        "CAD Total 9.10\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.currency == "CAD"
