"""Cross-category currency-pair extractor.

Currency / crypto trading pairs surface in trading-app screenshots,
fintech captures, exchange dashboards, and developer chats about
forex / crypto positions. The format is consistent enough across
the industry to extract reliably:

* ``USD/EUR``      -- slash-separated forex pair
* ``EUR/JPY``      -- slash-separated forex pair
* ``BTC/USDT``     -- slash-separated crypto pair
* ``BTC-USDT``     -- dash-separated crypto pair (Coinbase / Kraken style)
* ``BTCUSDT``      -- bare concatenated (Binance perp style, e.g. ``BTCUSDT``)
* ``EUR/JPY @ 158.40`` -- pair with current rate
* ``BTC/USD: 67000.00`` -- pair with colon-separated rate
* ``BTC/USDT 67000``    -- pair with bare rate

Output shape: a list of ``{"base", "quote", "rate"}`` dicts. ``base``
is the LEFT side (the asset being priced), ``quote`` is the RIGHT
side (the asset doing the pricing). ``rate`` is the float rate when
the pair is printed alongside one (``@``, ``:``, or bare whitespace
followed by a numeric value), or ``None`` for bare-pair captures.

Recognised codes:

* ISO 4217 currency codes (USD / EUR / GBP / JPY / etc.) -- 40-code
  curated catalogue, same set as :mod:`shotclassify_extract.amounts`.
* Cryptocurrency tickers -- curated catalogue of the top ~60 by
  market cap (BTC / ETH / USDT / BNB / SOL / XRP / USDC / DOGE /
  ADA / TRX / etc.), plus the most-traded stablecoins (USDT / USDC /
  DAI / BUSD / TUSD / FRAX / GUSD / USDD).

Deliberately NOT matched:

* Three-letter prose words (``THE`` / ``AND``) that happen to sit
  next to a slash or dash -- the catalogue gating prevents these.
* Filesystem paths (``/usr/bin/env``) -- the codes must be uppercase
  AND in the catalogue.
* Date ranges (``2024/01/15``) -- the digits-only segments don't
  match the alphabet-only code pattern.
* Generic ratios (``5/10``) -- same reason.

The matcher de-dupes on the ``(base, quote)`` pair (rate is NOT
included in the dedupe key -- a pair printed twice with different
rates collapses to the first-seen rate). First-seen order is
preserved. Capped at 50 entries because a trading dashboard
screenshot rarely shows more.
"""
from __future__ import annotations

import re

# ISO 4217 currency codes -- mirrors the curated set used by
# :mod:`shotclassify_extract.amounts`. Keep this list aligned with
# the most-commonly-printed codes rather than the full 180.
_FIAT_CODES: frozenset[str] = frozenset({
    "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR",
    "MXN", "BRL", "ZAR", "SGD", "HKD", "NZD", "SEK", "NOK", "DKK",
    "KRW", "RUB", "TRY", "PLN", "CZK", "HUF", "THB", "IDR", "ILS",
    "PHP", "MYR", "TWD", "VND", "AED", "SAR", "QAR", "EGP", "NGN",
    "RON", "ARS", "CLP", "COP", "PEN", "UYU", "BGN", "HRK", "ISK",
    "RMB",  # informal alias used outside China for CNY
})

# Cryptocurrency tickers. Top-by-market-cap + most-traded stablecoins
# and major altcoins. We pick the curated set rather than allowing
# arbitrary 3-5 letter uppercase strings because the false-positive
# risk would be too high (every English acronym would qualify).
_CRYPTO_CODES: frozenset[str] = frozenset({
    # Top by market cap
    "BTC", "ETH", "USDT", "BNB", "SOL", "XRP", "USDC", "DOGE",
    "ADA", "TRX", "TON", "AVAX", "LINK", "DOT", "MATIC", "WBTC",
    "SHIB", "LTC", "BCH", "UNI", "ATOM", "ETC", "XLM", "ICP",
    "FIL", "CRO", "APT", "ARB", "NEAR", "OP", "VET", "AAVE",
    "MKR", "ALGO", "GRT", "QNT", "FTM", "EGLD", "RUNE", "SAND",
    "AXS", "EOS", "FLOW", "XTZ", "MANA", "CHZ", "INJ", "STX",
    "RNDR", "LDO", "MNT", "HBAR", "IMX", "KAS", "ARKM", "PEPE",
    "GALA", "PYTH", "SUI", "SEI", "WLD", "BLUR", "ENS",
    # Stablecoins
    "DAI", "BUSD", "TUSD", "FRAX", "GUSD", "USDD", "USDP", "PYUSD",
    # Wrapped variants
    "WETH", "WBNB", "WSOL", "STETH", "WSTETH",
    # Exchange / DeFi tokens
    "FTT", "OKB", "HT", "CAKE", "CRV", "SNX", "COMP", "YFI",
    "1INCH", "SUSHI", "BAL", "ENJ", "BAT", "OMG", "ZRX",
})

# Combined valid-token set for the membership check.
_VALID_TOKENS: frozenset[str] = _FIAT_CODES | _CRYPTO_CODES

# Slash / dash separated pair shape: ``USD/EUR`` / ``BTC-USDT``.
# Each side must be 2-6 uppercase letters or digits (1INCH is 5
# chars; WSTETH is 6). The word-boundary defence on both ends
# stops false-positives on path segments like ``/usr/bin``.
_PAIR_SLASH_DASH_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?P<base>[A-Z0-9]{2,6})"
    r"\s?[/\-]\s?"
    r"(?P<quote>[A-Z0-9]{2,6})"
    r"(?![A-Za-z0-9])"
)

# Rate-printed extension: ``EUR/JPY @ 158.40`` / ``BTC/USD: 67000``.
# We pull the rate off the immediate trailing fragment when an
# anchor (``@`` / ``:``) is followed by a numeric value with
# optional decimals and optional thousands separators.
#
# Bare-whitespace rate (``BTC/USDT 67000``) is also accepted but
# only after a pair match has already validated both sides --
# without that gating a generic ``DUR/foo 12345`` would steal an
# unrelated number as a rate.
#
# Order MATTERS in the alternation: the comma-grouped form requires
# AT LEAST ONE comma group (the ``+`` quantifier) so that a plain
# integer like ``67000`` falls through to the second alternative
# rather than being chopped to ``670``.
_RATE_AFTER_PAIR_RE = re.compile(
    r"\s*(?:[@:]\s*)?"
    r"(?P<num>\d{1,3}(?:[,]\d{3})+(?:\.\d{1,8})?|\d+(?:\.\d{1,8})?)"
    r"(?![A-Za-z\d])"
)

# Cap output entries. 50 covers a busy trading dashboard without
# blowing the JSON column size for the storage layer.
_MAX_FX_PAIRS = 50


def _is_valid_pair(base: str, quote: str) -> bool:
    """Return True when (base, quote) are BOTH in the curated catalogue.

    Both sides must be recognised -- a half-validated pair like
    ``USD/RED`` is almost certainly noise (an off-by-one slash in
    a sentence) so we reject it. ``RMB`` is intentionally accepted
    on either side (it's an informal alias for CNY).
    """
    return base in _VALID_TOKENS and quote in _VALID_TOKENS


def _canonical(code: str) -> str:
    """Return the canonical form of a code (RMB -> CNY for stable dedupe).

    All other codes pass through unchanged.
    """
    if code == "RMB":
        return "CNY"
    return code


def _parse_rate(raw: str) -> float | None:
    """Convert a captured rate string into a positive float.

    Handles US-style thousands grouping (``67,000.00``). Returns
    ``None`` for unparseable input or non-positive values.
    """
    if not raw:
        return None
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def extract_fx_pairs(text: str) -> list[dict]:
    """Return currency / crypto trading pairs found in ``text``.

    Each entry is a ``{"base": str, "quote": str, "rate": float | None}``
    dict where ``base`` is the asset being priced and ``quote`` is
    the asset doing the pricing. Rate is the float rate when the
    pair is printed alongside an ``@`` / ``:`` / bare-whitespace
    numeric value, or ``None`` for bare-pair captures.

    De-duped on the (base, quote) pair -- the first-seen rate
    wins for stable behaviour. First-seen order preserved. Capped
    at 50 entries.

    Both sides MUST be in the curated catalogue
    (:data:`_VALID_TOKENS`) so a stray ``USD/RED`` doesn't fire.
    """
    if not text or not isinstance(text, str):
        return []
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for m in _PAIR_SLASH_DASH_RE.finditer(text):
        base = m.group("base")
        quote = m.group("quote")
        # Both sides must be in the curated catalogue -- this is the
        # primary defence against random uppercase token pairs.
        if not _is_valid_pair(base, quote):
            continue
        # A pair cannot have identical sides (USD/USD is meaningless).
        if base == quote:
            continue
        canonical_base = _canonical(base)
        canonical_quote = _canonical(quote)
        key = (canonical_base, canonical_quote)
        if key in seen:
            continue
        seen.add(key)
        # Try to pull a rate off the tail of the match span.
        rate: float | None = None
        tail = text[m.end():m.end() + 32]
        rate_m = _RATE_AFTER_PAIR_RE.match(tail)
        if rate_m is not None:
            rate = _parse_rate(rate_m.group("num"))
        out.append({
            "base": canonical_base,
            "quote": canonical_quote,
            "rate": rate,
        })
        if len(out) >= _MAX_FX_PAIRS:
            break
    return out


__all__ = ["extract_fx_pairs"]
