"""Cross-category trading-position extractor tests.

raw["positions"] captures structured position notations from
trading-app screenshots. Each entry is a
{side, size, symbol, price, kind} dict.
"""
from __future__ import annotations

from shotclassify_extract.positions import extract_positions

# ---- Empty / no-position cases -----------------------------------


def test_empty_text():
    assert extract_positions("") == []


def test_none_text():
    assert extract_positions(None) == []  # type: ignore[arg-type]


def test_plain_prose_no_positions():
    text = "Just some prose without any trading positions."
    assert extract_positions(text) == []


def test_dollar_amounts_only_no_positions():
    text = "Charged $175.00 for service."
    assert extract_positions(text) == []


# ---- Stock long --------------------------------------------------


def test_basic_stock_long():
    text = "100 AAPL @ 175.00"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0] == {
        "side": "long",
        "size": 100.0,
        "symbol": "AAPL",
        "price": 175.0,
        "kind": "stock",
    }


def test_stock_long_with_dollar_price():
    text = "50 MSFT @ $410.50"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0]["symbol"] == "MSFT"
    assert out[0]["price"] == 410.50


def test_explicit_plus_qty_long():
    text = "+200 NVDA @ 925.00"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0]["side"] == "long"
    assert out[0]["size"] == 200.0


def test_thousand_grouped_price():
    text = "10 GOOG @ $2,750.50"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0]["price"] == 2750.50


# ---- Stock short -------------------------------------------------


def test_negative_qty_short():
    text = "-100 TSLA @ 250.50"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0]["side"] == "short"
    assert out[0]["size"] == 100.0


def test_explicit_short_keyword():
    text = "100 TSLA SHORT @ 250.50"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0]["side"] == "short"
    assert out[0]["symbol"] == "TSLA"


def test_explicit_short_trailing():
    text = "100 GME @ 25.00 short"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0]["side"] == "short"


def test_long_keyword_after_price():
    text = "5 AAPL @ 175.00 long"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0]["side"] == "long"


# ---- Crypto positions --------------------------------------------


def test_crypto_btc_long():
    text = "0.5 BTC @ 67000"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0]["symbol"] == "BTC"
    assert out[0]["kind"] == "crypto"


def test_crypto_eth_long_dollar():
    text = "5 ETH @ $3500"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0]["kind"] == "crypto"


def test_crypto_pair_form():
    text = "10 ETH/USDT @ 3500"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0]["symbol"] == "ETH/USDT"
    assert out[0]["kind"] == "crypto"


def test_crypto_dash_pair_form():
    text = "0.1 BTC-USD @ 67500"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0]["symbol"] == "BTC-USD"


def test_crypto_short_keyword():
    text = "1.5 ETH SHORT @ 3450"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0]["side"] == "short"
    assert out[0]["kind"] == "crypto"


def test_crypto_short_trailing():
    text = "+0.5 BTC short @ 67000"
    out = extract_positions(text)
    # The leading + implies long but trailing short keyword wins
    assert len(out) == 1
    # SHORT pattern matches first (trailing-side) -> side="short"
    assert out[0]["side"] == "short"
    assert out[0]["symbol"] == "BTC"


def test_solana_in_catalogue():
    text = "100 SOL @ 175.50"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0]["kind"] == "crypto"


def test_doge_meme_coin():
    text = "10000 DOGE @ 0.15"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0]["kind"] == "crypto"
    assert out[0]["symbol"] == "DOGE"


# ---- Options -----------------------------------------------------


def test_option_call_basic():
    text = "5 AAPL 175 CALL @ 2.50"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0]["kind"] == "option"
    assert out[0]["symbol"] == "AAPL 175 CALL"
    assert out[0]["price"] == 2.50


def test_option_put_basic():
    text = "100 SPY 450 PUT @ 1.20"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0]["kind"] == "option"
    assert "PUT" in str(out[0]["symbol"])


def test_option_c_short_form():
    text = "5 AAPL 175 C @ 2.50"
    out = extract_positions(text)
    assert len(out) == 1
    assert "CALL" in str(out[0]["symbol"])


def test_option_p_short_form():
    text = "5 SPY 450 P @ 1.20"
    out = extract_positions(text)
    assert len(out) == 1
    assert "PUT" in str(out[0]["symbol"])


def test_option_with_dollar_prices():
    text = "5 AAPL $175 CALL @ $2.50"
    out = extract_positions(text)
    assert len(out) == 1
    assert out[0]["kind"] == "option"


# ---- Multiple positions in one capture --------------------------


def test_multiple_positions():
    text = """Open Positions
100 AAPL @ 175.00
-50 TSLA @ 250.00
0.5 BTC @ 67000
"""
    out = extract_positions(text)
    assert len(out) == 3
    symbols = [p["symbol"] for p in out]
    assert "AAPL" in symbols
    assert "TSLA" in symbols
    assert "BTC" in symbols
    # TSLA is short
    tsla = next(p for p in out if p["symbol"] == "TSLA")
    assert tsla["side"] == "short"


def test_mixed_kinds_in_one_capture():
    text = (
        "100 AAPL @ 175.00\n"
        "5 AAPL 180 CALL @ 3.50\n"
        "10 ETH @ 3500\n"
    )
    out = extract_positions(text)
    assert len(out) == 3
    kinds = [p["kind"] for p in out]
    assert "stock" in kinds
    assert "option" in kinds
    assert "crypto" in kinds


# ---- Safety / false-positive defences ---------------------------


def test_food_with_at_rejected_short_word():
    """`5 cookies @ 2.50` - cookies is 7 chars so it doesn't match
    the bare ticker pattern (which accepts 2-5 chars for non-crypto)."""
    text = "5 cookies @ 2.50"
    assert extract_positions(text) == []


def test_for_at_word_rejected():
    """`5 for @ 2.50` -- FOR is in reject list."""
    text = "5 FOR @ 2.50"
    assert extract_positions(text) == []


def test_at_word_alone_rejected():
    text = "100 AT @ 5.00"
    assert extract_positions(text) == []


def test_lowercase_symbol_rejected():
    """Lowercase symbol (prose word) rejects -- tickers are uppercase."""
    text = "100 aapl @ 175.00"
    assert extract_positions(text) == []


def test_single_char_ticker_rejected():
    """1-char tickers exist (T, F) but reject as too noisy."""
    text = "100 T @ 18.50"
    assert extract_positions(text) == []


def test_zero_qty_rejected():
    text = "0 AAPL @ 175.00"
    assert extract_positions(text) == []


def test_oversized_qty_rejected():
    text = "100000000 AAPL @ 175.00"
    assert extract_positions(text) == []


def test_oversized_price_rejected():
    text = "100 AAPL @ 99999999.00"
    assert extract_positions(text) == []


def test_zero_price_rejected():
    text = "100 AAPL @ 0"
    assert extract_positions(text) == []


def test_at_without_price_rejected():
    text = "100 AAPL @"
    assert extract_positions(text) == []


def test_price_without_at_rejected():
    text = "100 AAPL 175.00"
    assert extract_positions(text) == []


def test_no_symbol_rejected():
    text = "100 @ 175.00"
    assert extract_positions(text) == []


# ---- Real-world captures -----------------------------------------


def test_real_world_robinhood_positions():
    text = """Robinhood Portfolio
$50,234.50 -2.34% Today

Positions (5)
100 AAPL @ 175.00
50 MSFT @ 410.50
-25 TSLA @ 250.75
200 NVDA @ 925.00
5 AAPL 180 CALL @ 3.25
"""
    out = extract_positions(text)
    assert len(out) == 5
    tsla = next(p for p in out if p["symbol"] == "TSLA")
    assert tsla["side"] == "short"
    opt = next(p for p in out if p["kind"] == "option")
    assert "CALL" in str(opt["symbol"])


def test_real_world_coinbase_capture():
    text = """Coinbase Pro
Assets
0.5 BTC @ 67500
5 ETH @ 3500
1000 SOL @ 175
"""
    out = extract_positions(text)
    assert len(out) == 3
    for p in out:
        assert p["kind"] == "crypto"
        assert p["side"] == "long"


def test_real_world_thinkorswim_options():
    text = """TOS Options Chain
You are LONG
5 SPY 450 CALL @ 2.10
10 SPY 440 PUT @ 1.05

You are SHORT
-3 QQQ 380 CALL @ 1.85
"""
    out = extract_positions(text)
    assert len(out) == 3
    options = [p for p in out if p["kind"] == "option"]
    assert len(options) == 3


def test_real_world_trading_chat():
    text = """Mike: just opened 100 AAPL @ 175
Sara: nice, I went 5 ETH @ 3500 long
Joe: I'm staying short with -50 TSLA @ 250
"""
    out = extract_positions(text)
    assert len(out) == 3


# ---- Cap at 50 entries ------------------------------------------


def test_cap_at_50_entries():
    lines = []
    for i in range(60):
        lines.append(f"{i+1} AAPL @ {i+1}.00")
    text = "\n".join(lines)
    out = extract_positions(text)
    assert len(out) <= 50


# ---- Pipeline integration ---------------------------------------


def test_pipeline_writes_positions_for_chat_category():
    """When OCR contains positions, pipeline writes raw[positions]."""
    from shotclassify_common import Category, ExtractedFields, OCRResult
    from shotclassify_extract.pipeline import enrich

    text = "Trade: 100 AAPL @ 175.00 long\nSentence with no signal."
    ocr = OCRResult(text=text)
    out = enrich(Category.chat_screenshot, ExtractedFields(), ocr)
    assert "positions" in out.raw
    assert len(out.raw["positions"]) == 1
    assert out.raw["positions"][0]["symbol"] == "AAPL"


def test_pipeline_omits_positions_when_no_signal():
    from shotclassify_common import Category, ExtractedFields, OCRResult
    from shotclassify_extract.pipeline import enrich

    text = "Plain receipt with no positions"
    ocr = OCRResult(text=text)
    out = enrich(Category.receipt, ExtractedFields(), ocr)
    assert "positions" not in out.raw
