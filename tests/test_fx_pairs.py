"""Cross-category currency / crypto trading pair extractor tests.

The new ``extract_fx_pairs`` matcher pulls trading pairs from OCR
text and stashes them under ``ExtractedFields.raw["fx_pairs"]``.

Recognised shapes:
* Slash-separated: ``USD/EUR``, ``BTC/USDT``
* Dash-separated: ``BTC-USDT`` (Coinbase / Kraken style)
* With rate: ``EUR/JPY @ 158.40``, ``BTC/USD: 67000.00``, ``BTC/USDT 67000``

Safety properties:
* Both sides MUST be in the curated catalogue (40 ISO 4217 fiat
  codes + ~60 top-by-market-cap crypto tickers).
* Identical base+quote rejected.
* Filesystem paths and date ranges don't false-positive.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_fx_pairs

# ---- Slash-separated forex pairs ----------------------------


def test_basic_fiat_pair():
    result = extract_fx_pairs("USD/EUR")
    assert result == [{"base": "USD", "quote": "EUR", "rate": None}]


def test_major_forex_pair():
    result = extract_fx_pairs("EUR/JPY")
    assert len(result) == 1
    assert result[0]["base"] == "EUR"
    assert result[0]["quote"] == "JPY"


def test_minor_forex_pair():
    result = extract_fx_pairs("CAD/CHF")
    assert len(result) == 1


def test_emerging_market_pair():
    result = extract_fx_pairs("USD/TRY")
    assert result == [{"base": "USD", "quote": "TRY", "rate": None}]


# ---- Dash-separated crypto pairs ----------------------------


def test_crypto_pair_dash():
    result = extract_fx_pairs("BTC-USDT")
    assert result == [{"base": "BTC", "quote": "USDT", "rate": None}]


def test_crypto_pair_slash():
    result = extract_fx_pairs("BTC/USDT")
    assert result == [{"base": "BTC", "quote": "USDT", "rate": None}]


def test_eth_usd():
    result = extract_fx_pairs("ETH/USD")
    assert result == [{"base": "ETH", "quote": "USD", "rate": None}]


def test_btc_usd():
    result = extract_fx_pairs("BTC/USD")
    assert result == [{"base": "BTC", "quote": "USD", "rate": None}]


def test_eth_btc():
    result = extract_fx_pairs("ETH/BTC")
    assert result == [{"base": "ETH", "quote": "BTC", "rate": None}]


def test_4_letter_crypto():
    result = extract_fx_pairs("LINK/USDT")
    assert result == [{"base": "LINK", "quote": "USDT", "rate": None}]


def test_5_letter_crypto():
    result = extract_fx_pairs("1INCH/USD")
    assert result == [{"base": "1INCH", "quote": "USD", "rate": None}]


def test_6_letter_crypto():
    result = extract_fx_pairs("STETH/ETH")
    assert result == [{"base": "STETH", "quote": "ETH", "rate": None}]


def test_stablecoin_pair():
    result = extract_fx_pairs("USDC/USDT")
    assert result == [{"base": "USDC", "quote": "USDT", "rate": None}]


# ---- Pairs with rates ---------------------------------------


def test_pair_with_at_rate():
    result = extract_fx_pairs("EUR/JPY @ 158.40")
    assert len(result) == 1
    assert result[0]["base"] == "EUR"
    assert result[0]["quote"] == "JPY"
    assert result[0]["rate"] == 158.40


def test_pair_with_colon_rate():
    result = extract_fx_pairs("BTC/USD: 67000.00")
    assert len(result) == 1
    assert result[0]["rate"] == 67000.00


def test_pair_with_bare_whitespace_rate():
    result = extract_fx_pairs("BTC/USDT 67000")
    assert len(result) == 1
    assert result[0]["rate"] == 67000.0


def test_pair_with_thousands_separator():
    result = extract_fx_pairs("BTC/USD: 67,000.00")
    assert len(result) == 1
    assert result[0]["rate"] == 67000.0


def test_pair_with_high_precision_rate():
    result = extract_fx_pairs("EUR/USD @ 1.08745")
    assert len(result) == 1
    assert abs(result[0]["rate"] - 1.08745) < 0.00001


def test_pair_with_low_precision_yen_rate():
    result = extract_fx_pairs("USD/JPY @ 150")
    assert len(result) == 1
    assert result[0]["rate"] == 150.0


def test_dash_pair_with_rate():
    result = extract_fx_pairs("BTC-USDT @ 67000")
    assert len(result) == 1
    assert result[0]["rate"] == 67000.0


def test_pair_with_at_no_space():
    result = extract_fx_pairs("EUR/JPY @158.40")
    assert len(result) == 1
    assert result[0]["rate"] == 158.40


def test_pair_with_colon_no_space():
    result = extract_fx_pairs("BTC/USD:67000")
    assert len(result) == 1
    assert result[0]["rate"] == 67000.0


# ---- Multiple pairs in same text ----------------------------


def test_multiple_pairs():
    text = "Holdings: BTC/USD, ETH/USD, SOL/USDT"
    result = extract_fx_pairs(text)
    assert len(result) == 3
    bases = [r["base"] for r in result]
    assert "BTC" in bases
    assert "ETH" in bases
    assert "SOL" in bases


def test_multiple_pairs_with_rates():
    text = "BTC/USD @ 67000\nETH/USD @ 3500\nSOL/USDT @ 145"
    result = extract_fx_pairs(text)
    assert len(result) == 3
    rates = {r["base"]: r["rate"] for r in result}
    assert rates["BTC"] == 67000.0
    assert rates["ETH"] == 3500.0
    assert rates["SOL"] == 145.0


def test_duplicates_are_deduped():
    text = "BTC/USD @ 67000\nBTC/USD @ 67500"
    result = extract_fx_pairs(text)
    # First-seen rate wins on duplicate (base, quote).
    assert len(result) == 1
    assert result[0]["rate"] == 67000.0


def test_first_seen_order_preserved():
    text = "TRY/USD CHF/USD GBP/USD JPY/USD"
    result = extract_fx_pairs(text)
    bases = [r["base"] for r in result]
    assert bases == ["TRY", "CHF", "GBP", "JPY"]


# ---- Catalog gating defence ----------------------------------


def test_unknown_left_side_rejected():
    # ``RED`` is not in the catalogue.
    result = extract_fx_pairs("RED/USD")
    assert result == []


def test_unknown_right_side_rejected():
    # ``XYZ`` is not in the catalogue.
    result = extract_fx_pairs("USD/XYZ")
    assert result == []


def test_both_sides_unknown_rejected():
    result = extract_fx_pairs("ABC/DEF")
    assert result == []


def test_prose_uppercase_not_pairs():
    # English uppercase words sit next to slashes in prose -- e.g.
    # ``THE/AND`` should not register.
    text = "Pick THE/AND choose"
    result = extract_fx_pairs(text)
    assert result == []


def test_filesystem_path_not_pair():
    text = "/usr/bin/env"
    result = extract_fx_pairs(text)
    assert result == []


def test_date_range_not_pair():
    text = "2024/01/15"
    result = extract_fx_pairs(text)
    assert result == []


def test_generic_ratio_not_pair():
    text = "5/10 stars"
    result = extract_fx_pairs(text)
    assert result == []


def test_identical_sides_rejected():
    # USD/USD is meaningless.
    result = extract_fx_pairs("USD/USD")
    assert result == []


def test_url_does_not_steal_codes():
    # URL path containing uppercase letters shouldn't fire.
    text = "https://example.com/api/v1"
    result = extract_fx_pairs(text)
    assert result == []


# ---- Canonicalisation (RMB -> CNY) --------------------------


def test_rmb_canonicalised_to_cny_on_left():
    result = extract_fx_pairs("RMB/USD")
    assert len(result) == 1
    assert result[0]["base"] == "CNY"


def test_rmb_canonicalised_to_cny_on_right():
    result = extract_fx_pairs("USD/RMB")
    assert len(result) == 1
    assert result[0]["quote"] == "CNY"


def test_rmb_and_cny_dedupe_to_same_entry():
    text = "USD/RMB\nUSD/CNY"
    result = extract_fx_pairs(text)
    # Both should canonicalise to USD/CNY -- one entry.
    assert len(result) == 1
    assert result[0]["base"] == "USD"
    assert result[0]["quote"] == "CNY"


# ---- Pipeline integration ------------------------------------


def test_pipeline_writes_fx_pairs_key():
    fields = ExtractedFields()
    ocr = OCRResult(text="EUR/JPY @ 158.40\nBTC/USD @ 67000")
    out = enrich(Category.other, fields, ocr)
    assert "fx_pairs" in out.raw
    pairs = out.raw["fx_pairs"]
    assert len(pairs) == 2
    bases = [p["base"] for p in pairs]
    assert "EUR" in bases
    assert "BTC" in bases


def test_pipeline_no_pairs_no_key():
    fields = ExtractedFields()
    ocr = OCRResult(text="No trading pairs here.")
    out = enrich(Category.other, fields, ocr)
    assert "fx_pairs" not in out.raw


def test_pipeline_writes_under_receipt_category():
    # Fintech trading-app receipts might show pairs alongside the
    # transaction; the cross-category extractor still runs.
    fields = ExtractedFields()
    ocr = OCRResult(text="Bought BTC/USD @ 67000\nFee: 0.05 USD")
    out = enrich(Category.receipt, fields, ocr)
    assert "fx_pairs" in out.raw


def test_pipeline_writes_under_chat_category():
    fields = ExtractedFields()
    ocr = OCRResult(text="Alice: hey, EUR/USD looks good\nBob: yeah, @ 1.08")
    out = enrich(Category.chat_screenshot, fields, ocr)
    assert "fx_pairs" in out.raw


# ---- Empty / null input -------------------------------------


def test_empty_text_returns_empty_list():
    assert extract_fx_pairs("") == []


def test_none_text_returns_empty_list():
    assert extract_fx_pairs(None) == []  # type: ignore[arg-type]


def test_whitespace_only_returns_empty_list():
    assert extract_fx_pairs("   \n\t\n") == []


# ---- Cap enforcement ----------------------------------------


def test_cap_at_50():
    # Construct a text with more than 50 distinct pairs to verify
    # the cap kicks in. We use sequential fiat-fiat pairs that we
    # know are all in the catalogue.
    fiats = sorted({
        "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR",
        "MXN", "BRL", "ZAR", "SGD", "HKD", "NZD", "SEK", "NOK", "DKK",
        "KRW", "RUB", "TRY", "PLN", "CZK", "HUF", "THB", "IDR", "ILS",
    })
    # Create cartesian product pairs: that's 27*26 = 702 distinct pairs.
    lines: list[str] = []
    for a in fiats:
        for b in fiats:
            if a != b:
                lines.append(f"{a}/{b}")
    text = " ".join(lines)
    result = extract_fx_pairs(text)
    assert len(result) == 50


# ---- Slash with spaces around ---------------------------------


def test_slash_with_space_left():
    # ``BTC /USD`` (one space before slash) is acceptable.
    result = extract_fx_pairs("BTC /USD")
    assert result == [{"base": "BTC", "quote": "USD", "rate": None}]


def test_slash_with_space_right():
    result = extract_fx_pairs("BTC/ USD")
    assert result == [{"base": "BTC", "quote": "USD", "rate": None}]


def test_slash_with_spaces_both_sides():
    result = extract_fx_pairs("BTC / USD")
    assert result == [{"base": "BTC", "quote": "USD", "rate": None}]


# ---- Crypto-specific cases ----------------------------------


def test_doge_usd():
    result = extract_fx_pairs("DOGE/USD")
    assert result == [{"base": "DOGE", "quote": "USD", "rate": None}]


def test_pepe_usdt():
    result = extract_fx_pairs("PEPE/USDT")
    assert result == [{"base": "PEPE", "quote": "USDT", "rate": None}]


def test_shiba_usd():
    result = extract_fx_pairs("SHIB/USD @ 0.000023")
    assert len(result) == 1
    assert result[0]["rate"] == 0.000023


def test_wbtc_usdc():
    result = extract_fx_pairs("WBTC/USDC")
    assert result == [{"base": "WBTC", "quote": "USDC", "rate": None}]


# ---- Edge case: pair followed by non-numeric -----------------


def test_pair_followed_by_letter_no_rate():
    # ``BTC/USD a 67000`` -- ``a`` is letter, blocks rate extraction.
    result = extract_fx_pairs("BTC/USD abc")
    assert len(result) == 1
    assert result[0]["rate"] is None


def test_pair_followed_by_word_no_rate():
    result = extract_fx_pairs("BTC/USD position open")
    assert len(result) == 1
    assert result[0]["rate"] is None


def test_pair_at_eof_no_rate():
    result = extract_fx_pairs("Buy BTC/USD")
    assert len(result) == 1
    assert result[0]["rate"] is None


# ---- Rate parsing edge cases --------------------------------


def test_rate_must_be_positive():
    # Zero rate is rejected, treated as no rate.
    result = extract_fx_pairs("BTC/USD: 0")
    assert len(result) == 1
    assert result[0]["rate"] is None


def test_negative_rate_not_captured():
    # ``-1.50`` rate is rejected by leading-sign-blocking.
    result = extract_fx_pairs("BTC/USD: -1.50")
    assert len(result) == 1
    # Leading ``-`` is not part of the regex; the rate matcher
    # would skip it, leaving rate=None.
    assert result[0]["rate"] is None


def test_very_small_rate():
    # Stablecoins like SHIB have very small per-coin USD values.
    result = extract_fx_pairs("SHIB/USD @ 0.000023")
    assert len(result) == 1
    assert result[0]["rate"] == 0.000023


# ---- Sentence-level extraction -------------------------------


def test_pair_in_prose():
    text = "Today the EUR/USD pair traded sideways."
    result = extract_fx_pairs(text)
    assert len(result) == 1
    assert result[0]["base"] == "EUR"
    assert result[0]["quote"] == "USD"


def test_pair_in_sentence_with_rate():
    text = "EUR/USD @ 1.0825 closed up."
    result = extract_fx_pairs(text)
    assert len(result) == 1
    assert result[0]["rate"] == 1.0825


def test_pair_at_start_of_line():
    text = "BTC/USDT 67500.50 +1.2%"
    result = extract_fx_pairs(text)
    assert len(result) == 1
    assert result[0]["rate"] == 67500.50


# ---- Realistic trading dashboard sample ---------------------


def test_trading_dashboard_sample():
    text = """
    Watchlist
    BTC/USDT   67,234.50   +2.34%
    ETH/USDT   3,521.80    +1.78%
    SOL/USDT   145.20      +4.12%
    EUR/USD    1.0823      -0.12%
    GBP/USD    1.2645      +0.34%
    USD/JPY    150.42      -0.23%
    XRP/USDT   0.523       +5.67%
    """
    result = extract_fx_pairs(text)
    assert len(result) == 7
    bases = [r["base"] for r in result]
    assert "BTC" in bases
    assert "ETH" in bases
    assert "EUR" in bases
    assert "XRP" in bases
    # Verify rates parsed for fiat majors
    rates = {r["base"]: r["rate"] for r in result}
    assert rates["EUR"] == 1.0823
    assert rates["GBP"] == 1.2645
    assert rates["BTC"] == 67234.50
