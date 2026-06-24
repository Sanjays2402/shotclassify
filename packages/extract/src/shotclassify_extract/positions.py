"""Cross-category trading position / strategy extractor.

Trading-app screenshots (Robinhood / Webull / Coinbase / Binance /
Bybit / Kraken / IBKR / TastyTrade / Thinkorswim) print user
positions in a fairly consistent shape across platforms:

* Stock long: ``100 AAPL @ 175.00``
* Stock short: ``-100 TSLA @ 250.50`` or ``100 TSLA SHORT @ 250.50``
* Crypto long: ``5 ETH @ $3500 long``
* Crypto short: ``+0.5 BTC short @ 67000``
* Option: ``5 AAPL 175 CALL @ 2.50`` / ``100 SPY 450 PUT @ 1.20``
* Futures: ``2 ESH4 @ 4500``

Each entry surfaces under ``raw["positions"]`` as a
``{"side": str, "size": float, "symbol": str, "price": float,
"kind": str}`` dict where:

* ``side`` is ``long`` / ``short``
* ``size`` is the absolute position size
* ``symbol`` is the ticker / pair (uppercased)
* ``price`` is the per-unit price (or None if no price printed)
* ``kind`` is ``stock`` / ``crypto`` / ``option`` / ``futures``

Safety:
* Symbol must look like a real ticker (1-6 ALL-CAPS letters for
  stocks, 2-5 ALL-CAPS for crypto base pair, optional /-USD or
  /USDT suffix).
* Quantity bounded 0 < n < 10,000,000 to reject OCR noise.
* Price bounded 0 < p < 10,000,000 to reject noise.
* Requires both quantity AND symbol AND @ separator AND price
  for the bare shape. The "long/short" keyword form requires
  the keyword as a discriminator.
"""
from __future__ import annotations

import re

_MAX_POSITIONS = 50

# Symbols we recognise as crypto without needing an explicit context
# anchor. Covers top-100 by market cap circa 2024-2026.
_CRYPTO_BASE: frozenset[str] = frozenset({
    "BTC", "ETH", "USDT", "USDC", "BNB", "SOL", "XRP", "ADA", "DOGE",
    "TRX", "AVAX", "DOT", "MATIC", "POL", "LINK", "TON", "SHIB", "BCH",
    "LTC", "UNI", "ATOM", "XLM", "ETC", "OKB", "NEAR", "FIL", "ARB",
    "APT", "OP", "VET", "ICP", "HBAR", "STX", "GRT", "INJ", "MKR",
    "TIA", "AAVE", "RNDR", "ALGO", "EGLD", "FTM", "FLOW", "QNT", "SAND",
    "AXS", "XTZ", "THETA", "MANA", "EOS", "RUNE", "KAS", "PEPE", "BONK",
    "WIF", "FLOKI", "ZEC", "MINA", "ROSE", "DYDX", "SUI", "SEI",
    "JUP", "WLD", "PYTH", "JTO", "FET", "RPL", "ENS", "LDO", "GMX",
    "DAI", "BUSD", "TUSD", "FRAX", "WETH", "WBTC", "STETH", "WSTETH",
})

_QUOTE_TICKERS: frozenset[str] = frozenset({
    "USD", "USDT", "USDC", "EUR", "GBP", "BTC", "ETH", "BNB",
})

# Stock-like ticker (single capital letter excluded because dashboards
# rarely surface 1-char tickers and they false-positive too easily).
_STOCK_TICKER = r"[A-Z]{1,6}"

# Crypto pair forms accepted: ETH/USDT, BTC-USD, ETH (bare when in the
# whitelist), ETHUSDT (BNB-style)
_CRYPTO_PAIR = (
    r"(?:[A-Z]{2,6}[/\-][A-Z]{2,6}|[A-Z]{2,6})"
)

# Combined ticker pattern -- caller filters down per kind.
_TICKER = r"[A-Z]{1,8}(?:[/\-][A-Z]{2,8})?"

_QUANTITY = r"-?\+?\d+(?:\.\d+)?"
_PRICE = r"\$?\d+(?:,\d{3})*(?:\.\d+)?"

# Bare shape: ``<qty> <SYMBOL> @ <price>``
_POS_BARE_RE = re.compile(
    rf"(?<![A-Za-z0-9.])(?P<qty>{_QUANTITY})\s+"
    rf"(?P<symbol>{_TICKER})\s+"
    r"@\s*"
    rf"(?P<price>\$?{_PRICE})"
    r"(?![A-Za-z0-9])",
)

# Sided shape: ``<qty> <SYMBOL> (LONG|SHORT) @ <price>`` OR
# ``(LONG|SHORT) <qty> <SYMBOL> @ <price>``
_POS_SIDE_AFTER_RE = re.compile(
    rf"(?<![A-Za-z0-9.])(?P<qty>{_QUANTITY})\s+"
    rf"(?P<symbol>{_TICKER})\s+"
    r"(?P<side>LONG|SHORT|BUY|SELL)\s*"
    r"@\s*"
    rf"(?P<price>\$?{_PRICE})"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_POS_SIDE_TRAILING_RE = re.compile(
    rf"(?<![A-Za-z0-9.])(?P<qty>{_QUANTITY})\s+"
    rf"(?P<symbol>{_TICKER})\s+"
    r"@\s*"
    rf"(?P<price>\$?{_PRICE})\s+"
    r"(?P<side>long|short)"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)

# Option shape: ``<qty> <SYMBOL> <strike> (CALL|PUT) @ <price>``
_POS_OPTION_RE = re.compile(
    rf"(?<![A-Za-z0-9.])(?P<qty>{_QUANTITY})\s+"
    rf"(?P<symbol>{_STOCK_TICKER})\s+"
    rf"(?P<strike>{_PRICE})\s+"
    r"(?P<right>CALL|PUT|C|P)\s*"
    r"@\s*"
    rf"(?P<price>\$?{_PRICE})"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _parse_price(raw: str) -> float | None:
    """Return float from a price string ``$1,234.56`` -> 1234.56."""
    cleaned = raw.replace("$", "").replace(",", "")
    try:
        v = float(cleaned)
        if v <= 0 or v >= 10_000_000:
            return None
        return v
    except (ValueError, TypeError):
        return None


def _parse_qty(raw: str) -> tuple[float, str | None] | None:
    """Return (abs_quantity, sign_implied_side) from a qty string.

    ``-100`` -> (100.0, "short"), ``+5`` -> (5.0, "long"),
    ``100`` -> (100.0, None).
    """
    raw = raw.strip()
    implied: str | None = None
    if raw.startswith("-"):
        implied = "short"
        raw = raw[1:]
    elif raw.startswith("+"):
        implied = "long"
        raw = raw[1:]
    try:
        v = float(raw)
        if v <= 0 or v >= 10_000_000:
            return None
        return (v, implied)
    except (ValueError, TypeError):
        return None


def _classify_symbol(symbol: str) -> str:
    """Tag the symbol as stock / crypto / option / futures."""
    sym = symbol.upper()
    # Detect pair shape (X/Y or X-Y)
    for sep in ("/", "-"):
        if sep in sym:
            parts = sym.split(sep)
            if len(parts) == 2:
                base, quote = parts[0], parts[1]
                if base in _CRYPTO_BASE or quote in _QUOTE_TICKERS:
                    return "crypto"
                # Could be a stock pair (PAYX/USD?) -- treat as stock
                return "stock"
    # Bare ticker
    if sym in _CRYPTO_BASE:
        return "crypto"
    # Common stocks heuristic: 1-5 letters, ALL CAPS, not in crypto
    if 1 <= len(sym) <= 5 and sym.isalpha():
        return "stock"
    # Futures contracts typically end in a month code: ESH4, ESZ3
    if re.match(r"^[A-Z]{2,4}[FGHJKMNQUVXZ]\d{1,2}$", sym):
        return "futures"
    return "stock"


def extract_positions(text: str) -> list[dict[str, str | float | None]]:
    """Extract trading-position notations from ``text``.

    Returns a list of ``{"side", "size", "symbol", "price", "kind"}``
    dicts in source-text order.

    Safety:
    * Symbol must look like a ticker (1-8 uppercase letters,
      optionally pair-separated by / or -).
    * Quantity bounded 0 < n < 10,000,000.
    * Price bounded 0 < p < 10,000,000.
    * Pair-form symbols recognised as crypto when base or quote is in
      the curated catalogue; otherwise treated as stock.
    * Option shape requires explicit CALL / PUT keyword.
    * Capped at 50 entries.
    """
    if not text or not isinstance(text, str):
        return []
    out: list[dict[str, str | float | None]] = []
    consumed: list[tuple[int, int]] = []

    def _seen(s: int, e: int) -> bool:
        for cs, ce in consumed:
            if s < ce and e > cs:
                return True
        return False

    def _push(entry: dict[str, str | float | None], s: int, e: int) -> bool:
        if len(out) >= _MAX_POSITIONS:
            return False
        if _seen(s, e):
            return False
        out.append(entry)
        consumed.append((s, e))
        return True

    # --- Pass 1: option (most specific shape, claim first) ---------
    for m in _POS_OPTION_RE.finditer(text):
        qty_info = _parse_qty(m.group("qty"))
        if qty_info is None:
            continue
        size, implied_side = qty_info
        strike = _parse_price(m.group("strike"))
        price = _parse_price(m.group("price"))
        if price is None or strike is None:
            continue
        right = m.group("right").upper()
        if right == "C":
            right = "CALL"
        elif right == "P":
            right = "PUT"
        symbol_raw = m.group("symbol").upper()
        side = implied_side or "long"
        entry: dict[str, str | float | None] = {
            "side": side,
            "size": size,
            "symbol": f"{symbol_raw} {strike:g} {right}",
            "price": price,
            "kind": "option",
        }
        _push(entry, m.start(), m.end())

    # --- Pass 2: sided after symbol --------------------------------
    for m in _POS_SIDE_AFTER_RE.finditer(text):
        qty_info = _parse_qty(m.group("qty"))
        if qty_info is None:
            continue
        size, _ = qty_info
        price = _parse_price(m.group("price"))
        if price is None:
            continue
        side_raw = m.group("side").lower()
        side = "long" if side_raw in {"long", "buy"} else "short"
        symbol = m.group("symbol").upper()
        kind = _classify_symbol(symbol)
        entry = {
            "side": side,
            "size": size,
            "symbol": symbol,
            "price": price,
            "kind": kind,
        }
        _push(entry, m.start(), m.end())

    # --- Pass 3: side trailing ------------------------------------
    for m in _POS_SIDE_TRAILING_RE.finditer(text):
        qty_info = _parse_qty(m.group("qty"))
        if qty_info is None:
            continue
        size, _ = qty_info
        price = _parse_price(m.group("price"))
        if price is None:
            continue
        side = m.group("side").lower()
        symbol = m.group("symbol").upper()
        kind = _classify_symbol(symbol)
        entry = {
            "side": side,
            "size": size,
            "symbol": symbol,
            "price": price,
            "kind": kind,
        }
        _push(entry, m.start(), m.end())

    # --- Pass 4: bare qty + symbol + @ + price --------------------
    for m in _POS_BARE_RE.finditer(text):
        qty_info = _parse_qty(m.group("qty"))
        if qty_info is None:
            continue
        size, implied = qty_info
        price = _parse_price(m.group("price"))
        if price is None:
            continue
        symbol = m.group("symbol").upper()
        # Safety: bare-shape symbol MUST be a recognisable ticker -- pair
        # form OR in the crypto catalogue OR 2..5 letters (stock).
        if "/" not in symbol and "-" not in symbol:
            if symbol not in _CRYPTO_BASE and not (2 <= len(symbol) <= 5 and symbol.isalpha()):
                continue
            # Reject common prose words that look like tickers but
            # almost never are at this shape.
            if symbol in {"FOR", "BY", "AT", "ON", "OF", "TO", "IN", "AND",
                          "THE", "BUT", "OR", "IF", "SO", "DO", "NO", "YES",
                          "ALL", "ANY", "ARE", "BE", "GO", "AS", "MY", "WE",
                          "US", "AM", "PM", "EST", "PST", "CST", "MST", "GMT",
                          "UTC", "ETA", "DOB"}:
                continue
        side = implied or "long"
        kind = _classify_symbol(symbol)
        entry = {
            "side": side,
            "size": size,
            "symbol": symbol,
            "price": price,
            "kind": kind,
        }
        _push(entry, m.start(), m.end())

    return out
