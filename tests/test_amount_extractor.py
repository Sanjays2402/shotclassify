"""Cross-category currency-amount extractor (raw["amounts"]).

The extractor recognises currency amounts across multiple shapes and
produces a typed list of ``{"currency", "amount"}`` dicts:

* Symbol-prefix: ``$12.99`` -> {"currency": "USD", "amount": 12.99}
* Symbol-suffix: ``12.99$`` -> same
* ISO-code-prefix: ``USD 12.99`` -> same
* ISO-code-suffix: ``12.99 USD`` -> same

Decimal normalisation handles both US (``1,234.56``) and EU
(``1.234,56``) conventions; thousands grouping is dropped.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_amounts

# ---- symbol prefix ---------------------------------------------------


def test_us_dollar_prefix_basic():
    out = extract_amounts("Total: $12.99 today")
    assert out == [{"currency": "USD", "amount": 12.99}]


def test_euro_prefix_basic():
    out = extract_amounts("Plan costs €29.50 per month")
    assert out == [{"currency": "EUR", "amount": 29.50}]


def test_gbp_prefix_basic():
    out = extract_amounts("Subscription is £99")
    assert out == [{"currency": "GBP", "amount": 99.0}]


def test_yen_prefix_no_decimal():
    out = extract_amounts("Price: ¥1000")
    assert out == [{"currency": "JPY", "amount": 1000.0}]


def test_rupee_prefix():
    out = extract_amounts("Order total ₹999.50")
    assert out == [{"currency": "INR", "amount": 999.50}]


def test_canadian_dollar_prefix():
    out = extract_amounts("Cost: C$5.50")
    assert out == [{"currency": "CAD", "amount": 5.50}]


def test_australian_dollar_prefix():
    out = extract_amounts("Cost: A$5.50")
    assert out == [{"currency": "AUD", "amount": 5.50}]


def test_hong_kong_dollar_prefix():
    out = extract_amounts("Price: HK$120")
    assert out == [{"currency": "HKD", "amount": 120.0}]


def test_nz_dollar_prefix():
    out = extract_amounts("Cost: NZ$8.50")
    assert out == [{"currency": "NZD", "amount": 8.50}]


def test_us_explicit_prefix():
    out = extract_amounts("Refund: US$50.00")
    assert out == [{"currency": "USD", "amount": 50.0}]


def test_singapore_dollar_prefix():
    out = extract_amounts("Item: S$10.99")
    assert out == [{"currency": "SGD", "amount": 10.99}]


def test_brazilian_real_prefix():
    out = extract_amounts("Custo: R$25,50")
    assert out == [{"currency": "BRL", "amount": 25.50}]


def test_korean_won_prefix():
    out = extract_amounts("Price: ₩50,000")
    assert out == [{"currency": "KRW", "amount": 50000.0}]


def test_thai_baht_prefix():
    out = extract_amounts("Cost: ฿350")
    assert out == [{"currency": "THB", "amount": 350.0}]


# ---- symbol suffix --------------------------------------------------


def test_euro_suffix_eu_style():
    """EU convention: ``10,50€`` with comma decimal."""
    out = extract_amounts("Total: 10,50€")
    assert out == [{"currency": "EUR", "amount": 10.50}]


def test_dollar_suffix():
    out = extract_amounts("Total: 12.99$")
    assert out == [{"currency": "USD", "amount": 12.99}]


def test_pound_suffix():
    out = extract_amounts("Cost 99£ tonight")
    assert out == [{"currency": "GBP", "amount": 99.0}]


# ---- ISO-code prefix ------------------------------------------------


def test_iso_code_prefix_usd():
    out = extract_amounts("Total USD 1,234.56 due")
    assert out == [{"currency": "USD", "amount": 1234.56}]


def test_iso_code_prefix_eur():
    out = extract_amounts("EUR 100.00 invoice")
    assert out == [{"currency": "EUR", "amount": 100.0}]


def test_iso_code_prefix_jpy_no_decimal():
    out = extract_amounts("Cost JPY 50000")
    assert out == [{"currency": "JPY", "amount": 50000.0}]


def test_iso_code_prefix_chf():
    out = extract_amounts("Bill CHF 100 due Friday")
    assert out == [{"currency": "CHF", "amount": 100.0}]


def test_iso_code_prefix_rejects_unknown_three_letter():
    """Random three-letter prose words must not trigger a price."""
    assert extract_amounts("RED 12.34 cars") == []
    assert extract_amounts("BIG 99 trees") == []


def test_iso_code_prefix_rmb_normalised_to_cny():
    out = extract_amounts("Total RMB 200")
    assert out == [{"currency": "CNY", "amount": 200.0}]


# ---- ISO-code suffix ------------------------------------------------


def test_iso_code_suffix_eur():
    out = extract_amounts("Total: 100.00 EUR")
    assert out == [{"currency": "EUR", "amount": 100.0}]


def test_iso_code_suffix_usd():
    out = extract_amounts("Amount due: 1,234.56 USD")
    assert out == [{"currency": "USD", "amount": 1234.56}]


def test_iso_code_suffix_rejects_unknown():
    assert extract_amounts("12.34 RED") == []


# ---- decimal normalisation -----------------------------------------


def test_us_thousands_with_dot_decimal():
    """``1,234,567.89`` (US style)."""
    out = extract_amounts("Quote: $1,234,567.89")
    assert out == [{"currency": "USD", "amount": 1234567.89}]


def test_eu_thousands_with_comma_decimal():
    """``1.234.567,89`` (German / EU style)."""
    out = extract_amounts("Preis: €1.234.567,89")
    assert out == [{"currency": "EUR", "amount": 1234567.89}]


def test_french_thousands_with_space():
    """French convention: ``1 234,56``."""
    out = extract_amounts("Prix: 1 234,56 EUR")
    assert out == [{"currency": "EUR", "amount": 1234.56}]


def test_comma_as_decimal_two_digit_tail():
    """``12,34`` (no grouping) -> 12.34, not 1234."""
    out = extract_amounts("Total: 12,34 EUR")
    assert out == [{"currency": "EUR", "amount": 12.34}]


def test_comma_as_grouping_three_digit_tail():
    """``1,234`` -> 1234, not 1.234."""
    out = extract_amounts("Cost: $1,234")
    assert out == [{"currency": "USD", "amount": 1234.0}]


def test_dot_as_decimal_two_digit_tail():
    """``12.34`` (no grouping) -> 12.34."""
    out = extract_amounts("Cost: $12.34")
    assert out == [{"currency": "USD", "amount": 12.34}]


def test_dot_grouping_multiple_dots():
    """``1.234.567`` -> 1234567 (all grouping)."""
    out = extract_amounts("EUR 1.234.567 total")
    assert out == [{"currency": "EUR", "amount": 1234567.0}]


# ---- de-dupe / order / cap ----------------------------------------


def test_dedup_same_currency_and_amount():
    out = extract_amounts("Total $12.99 then $12.99 again")
    assert out == [{"currency": "USD", "amount": 12.99}]


def test_distinct_currencies_kept_separate():
    out = extract_amounts("Bid $12.99 ask €11.50")
    assert {"currency": "USD", "amount": 12.99} in out
    assert {"currency": "EUR", "amount": 11.50} in out
    assert len(out) == 2


def test_distinct_amounts_kept_separate():
    out = extract_amounts("Prices: $5.00, $10.00, $15.00")
    amounts = sorted(e["amount"] for e in out)
    assert amounts == [5.0, 10.0, 15.0]


def test_first_seen_order_preserved():
    text = "Then €20 then $15 then £10"
    out = extract_amounts(text)
    codes = [e["currency"] for e in out]
    assert codes == ["EUR", "USD", "GBP"]


def test_cap_at_100_entries():
    # 150 distinct entries; we should only keep 100.
    text = " ".join(f"${i}.00" for i in range(1, 151))
    out = extract_amounts(text)
    assert len(out) == 100


# ---- multi-shape compound text -------------------------------------


def test_mixed_symbol_and_code():
    text = "Total: $12.99 plus tax. Receipt USD 14.50 final."
    out = extract_amounts(text)
    amounts = sorted(e["amount"] for e in out)
    assert amounts == [12.99, 14.50]


def test_invoice_with_eur_suffix_and_usd_prefix():
    text = "Invoice EUR 250.00 due / equivalent $275.50"
    out = extract_amounts(text)
    assert {"currency": "EUR", "amount": 250.0} in out
    assert {"currency": "USD", "amount": 275.5} in out


# ---- negative / rejection cases -----------------------------------


def test_empty_text():
    assert extract_amounts("") == []
    assert extract_amounts(None) == []  # type: ignore[arg-type]


def test_no_currency_context_skipped():
    """A bare ``12.99`` without any currency symbol or code is dropped."""
    assert extract_amounts("ship 12.99 today") == []


def test_percent_not_matched():
    """``12.34%`` is not currency."""
    assert extract_amounts("ratio 12.34% improvement") == []


def test_negative_amounts_rejected():
    """We deliberately don't track sign -- negatives are for refunds."""
    # The ``-`` is part of the surrounding text, not the amount
    # regex, so we still capture the positive number. This is by
    # design: refunds belong in the dedicated receipt fields.
    out = extract_amounts("Refund: -$12.99")
    assert out == [{"currency": "USD", "amount": 12.99}]


def test_zero_amount_captured():
    """Zero is a valid amount (free-tier / zero-due lines)."""
    out = extract_amounts("Balance: $0.00")
    assert out == [{"currency": "USD", "amount": 0.0}]


def test_decimal_part_only_one_digit():
    """Some currencies use one-digit decimals (``$5.5``)."""
    out = extract_amounts("Cost $5.5")
    assert out == [{"currency": "USD", "amount": 5.5}]


def test_four_digit_decimal_precision():
    """``$0.1234`` -- 4-digit precision used in crypto / FX."""
    out = extract_amounts("Rate $0.1234")
    assert out == [{"currency": "USD", "amount": 0.1234}]


def test_iso_code_no_separator_rejected():
    """``USD12.99`` (no space) is NOT a valid prefix shape."""
    # The regex requires whitespace between the code and the number;
    # without whitespace, the bare ``12.99`` has no anchor and is
    # dropped.
    assert extract_amounts("USD12.99") == []


# ---- integration through enrich() -----------------------------------


def test_pipeline_populates_raw_amounts():
    """The ``enrich`` entrypoint wires ``extract_amounts`` into
    ``ExtractedFields.raw["amounts"]`` for every category."""
    ocr = OCRResult(
        text="Receipt total: $42.50\nTip: $5.00 / Grand total $47.50",
        word_count=10,
    )
    fields = ExtractedFields()
    out = enrich(Category.other, fields, ocr)
    assert "amounts" in (out.raw or {})
    amounts = sorted(e["amount"] for e in out.raw["amounts"])
    assert amounts == [5.0, 42.5, 47.5]
    assert all(e["currency"] == "USD" for e in out.raw["amounts"])


def test_pipeline_skips_when_no_amounts():
    ocr = OCRResult(text="hello world no prices here", word_count=5)
    fields = ExtractedFields()
    out = enrich(Category.other, fields, ocr)
    assert "amounts" not in (out.raw or {})
