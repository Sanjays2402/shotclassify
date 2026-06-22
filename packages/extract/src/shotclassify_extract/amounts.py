"""Cross-category currency-amount extractor.

Currency amounts show up across every category of screenshot --
receipts are the obvious case but code snippets quote prices in test
fixtures (``price = 12.99``), error logs cite billing thresholds
("payment of $9.99 declined"), chat captures share pricing
discussions ("the plan is €29/mo"), and document captures of
invoices / quotes / contracts. Rather than teach each per-category
extractor (or the LLM) to find amounts, we run
:func:`extract_amounts` once on the OCR text and stash the typed
list under ``ExtractedFields.raw["amounts"]`` so dashboards and
routing rules can group by currency without per-category coupling.

Output shape: a list of ``{"currency", "amount"}`` dicts. The
``amount`` is a positive float (we deliberately do NOT track sign --
negative amounts are typically discounts, refunds, or balance
adjustments and belong in the dedicated receipt fields). The
``currency`` is the ISO 4217 three-letter code where we can infer it
(``USD`` / ``EUR`` / ``GBP`` / ``JPY`` / ``CAD`` / etc.) or ``None``
when we matched a bare-number-with-currency-keyword that didn't
resolve to a specific code.

Recognised shapes:

* **Symbol-prefixed amounts**: ``$12.99``, ``€10,50``, ``£99``,
  ``¥1000``, ``₹500``, ``₽1,200``, ``₩50,000``, ``₪80``, ``₺25``,
  ``₫10000``, ``₱100``, ``A$5.50``, ``C$5.50``, ``HK$10``, ``NZ$8``,
  ``US$50``, ``S$10`` (Singapore), ``R$25`` (Brazil), ``CHF 100``.
* **Symbol-suffixed amounts**: ``12.99$``, ``10€``, ``99£`` (the EU
  / South American convention).
* **ISO-code-prefixed amounts**: ``USD 12.99``, ``EUR 10.50``,
  ``GBP 99``, ``JPY 1000``, ``CAD 12``, ``AUD 5.50``, ``CHF 100``,
  ``BRL 25``, ``ZAR 80``, ``SEK 100``, ``NOK 150``, ``DKK 75``,
  ``HKD 50``, ``SGD 10``, ``CNY 700``, ``KRW 50000``, ``INR 999``,
  ``MXN 200``, ``NZD 8``, ``RUB 1200``, ``TRY 25``, ``THB 350``,
  ``IDR 100000``, ``PLN 30``, ``CZK 100``, ``HUF 5000``.
* **ISO-code-suffixed amounts**: ``12.99 USD``, ``10.50 EUR``,
  ``99 GBP`` (common on invoices in EU-style locales).
* **Decimal style**: both ``,`` and ``.`` accepted as the decimal
  separator. Thousands grouping (``1,234.56`` or ``1.234,56`` or
  ``1 234,56``) is normalised in :func:`_normalise_amount`.

Deliberately NOT matched:

* Bare numbers with no currency context (a code snippet's
  ``return 12.99`` is captured nowhere -- there's no signal that it's
  a price).
* Percent values (``12.99%``) -- those are not currency.
* Multipliers / quantities (``2 x 3.50`` -> the per-unit price ``3.50``
  alone would not match without a currency anchor; the outer flow
  applies one).
* Range expressions (``$5-$10``) -- we capture each endpoint as a
  separate entry because dashboards want both for sorting.

The matcher de-dupes on the ``(currency, amount)`` pair. First-seen
order is preserved. Capped at 100 entries because a receipt can
legitimately list 60+ line-items each with its own price.
"""
from __future__ import annotations

import re

# Currency symbol -> ISO code mapping. Order MATTERS in the symbol
# regex (longer / more-specific prefix-pairs first) so ``HK$`` wins
# over a bare ``$``.
_SYMBOL_TO_CODE: dict[str, str] = {
    # Multi-char prefixes (must be matched BEFORE the bare $).
    "A$": "AUD",
    "C$": "CAD",
    "HK$": "HKD",
    "NZ$": "NZD",
    "US$": "USD",
    "S$": "SGD",
    "R$": "BRL",
    "NT$": "TWD",
    "RM": "MYR",
    "kr": "SEK",
    "Rp": "IDR",
    "₱": "PHP",
    "₫": "VND",
    # Single-char prefixes.
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
    "₽": "RUB",
    "₩": "KRW",
    "₪": "ILS",
    "₺": "TRY",
    "₦": "NGN",
    "฿": "THB",
    "₴": "UAH",
    "₸": "KZT",
    "₵": "GHS",
}

# Set of currency codes we recognise as prefix / suffix tokens. Keep
# this list aligned with the most-commonly-printed ISO 4217 codes
# rather than the full ~180 codes -- adding unused codes increases
# the chance of false-positives on three-letter prose words.
_KNOWN_CODES: frozenset[str] = frozenset({
    "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR",
    "MXN", "BRL", "ZAR", "SGD", "HKD", "NZD", "SEK", "NOK", "DKK",
    "KRW", "RUB", "TRY", "PLN", "CZK", "HUF", "THB", "IDR", "ILS",
    "PHP", "MYR", "TWD", "VND", "AED", "SAR", "QAR", "EGP", "NGN",
    "RON", "ARS", "CLP", "COP", "PEN", "UYU", "BGN", "HRK", "ISK",
    "RMB",  # informal alias used outside China for CNY
})

# Single-symbol prefix list, sorted longest-first so ``HK$`` is tried
# before ``$``.
_SYMBOL_PREFIX_RE = re.compile(
    r"(?P<sym>HK\$|NZ\$|US\$|A\$|C\$|S\$|R\$|NT\$|RM|kr|Rp|"
    r"\$|€|£|¥|₹|₽|₩|₪|₺|₦|฿|₴|₸|₵|₱|₫)"
    r"\s?(?P<num>(?:\d{1,3}(?:[ ,.]\d{3})+|\d+)(?:[.,]\d{1,4})?)"
    r"(?!\w)"
)

# Suffix-shape: ``12.99$`` / ``10,50€`` / ``99£``. We require a
# non-digit / non-word boundary on the left so we don't bite into the
# tail of a longer number / identifier.
_SYMBOL_SUFFIX_RE = re.compile(
    r"(?<![\w.])"
    r"(?P<num>(?:\d{1,3}(?:[ ,.]\d{3})+|\d+)(?:[.,]\d{1,4})?)"
    r"\s?"
    r"(?P<sym>\$|€|£|¥|₹|₽|₩|₪|₺|₦|฿|₴|₸|₵|₱|₫|kr)"
    r"(?![\w$])"
)

# ISO-code prefix shape: ``USD 12.99`` / ``EUR 10.50``. We capture
# the code as a three-letter run and validate it against
# :data:`_KNOWN_CODES` so a stray ``EUR`` in prose without a price
# tag does NOT register. Separator must be present (whitespace) so
# ``USDX`` isn't matched.
_CODE_PREFIX_RE = re.compile(
    r"(?<![A-Za-z])"
    r"(?P<code>[A-Z]{3})\s+"
    r"(?P<num>(?:\d{1,3}(?:[ ,.]\d{3})+|\d+)(?:[.,]\d{1,4})?)"
    r"(?!\w)"
)

# ISO-code suffix shape: ``12.99 USD`` / ``10.50 EUR``. Same
# validation requirement on the code.
_CODE_SUFFIX_RE = re.compile(
    r"(?<![\w.])"
    r"(?P<num>(?:\d{1,3}(?:[ ,.]\d{3})+|\d+)(?:[.,]\d{1,4})?)"
    r"\s+(?P<code>[A-Z]{3})"
    r"(?![A-Za-z])"
)


# Cap output entries. 100 covers a long receipt and a long invoice
# without blowing JSON column size for the storage layer.
_MAX_AMOUNTS = 100


def _normalise_amount(raw: str) -> float | None:
    """Convert a raw amount string into a positive float.

    Handles thousands-separators in either comma or dot style, and
    both decimal conventions (``1,234.56`` US / ``1.234,56`` EU /
    ``1 234,56`` FR). Strategy:

    1. Strip whitespace.
    2. If both ``,`` and ``.`` appear, the RIGHTMOST one is the
       decimal separator; the other (and any whitespace) are
       grouping. Drop the grouping and keep the decimal.
    3. If only one of ``,`` / ``.`` appears, decide between
       "decimal" and "grouping" by group size: ``1.234`` -> 1.234
       (decimal) but ``1,234`` -> 1234 (grouping) -- to make this
       deterministic we treat exactly-three-digit tails as a
       grouping when the OTHER separator is the rare one for the
       digit (heuristic: ``,`` is grouping in US, ``.`` is
       grouping in EU; without other context we treat a
       three-digit-tail as grouping and a non-three-digit tail
       as decimal).
    4. ``int()`` / ``float()`` the result.

    Returns ``None`` for unparseable input.
    """
    if not raw:
        return None
    text = raw.strip().replace(" ", "")
    if not text:
        return None
    has_comma = "," in text
    has_dot = "." in text
    if has_comma and has_dot:
        # Rightmost separator is the decimal point.
        if text.rfind(",") > text.rfind("."):
            # EU style: ``1.234,56`` -> drop dots, swap comma to dot.
            text = text.replace(".", "").replace(",", ".")
        else:
            # US style: ``1,234.56`` -> drop commas.
            text = text.replace(",", "")
    elif has_comma:
        # Decide by group size. ``12,34`` (2-digit tail) -> decimal
        # comma; ``1,234`` (3-digit tail) -> grouping comma;
        # ``12,3456`` (4+ digit tail) -> decimal comma.
        idx = text.rfind(",")
        tail = text[idx + 1:]
        if len(tail) == 3 and tail.isdigit():
            # Grouping comma; drop it.
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
    elif has_dot:
        idx = text.rfind(".")
        tail = text[idx + 1:]
        if len(tail) == 3 and tail.isdigit() and text.count(".") > 1:
            # Multiple dots like ``1.234.567`` are all grouping.
            text = text.replace(".", "")
    try:
        value = float(text)
    except ValueError:
        return None
    if value < 0:
        return None
    return value


def _resolve_symbol(sym: str) -> str | None:
    """Return the ISO code for a recognised symbol prefix / suffix."""
    return _SYMBOL_TO_CODE.get(sym)


def extract_amounts(text: str) -> list[dict]:
    """Return currency amounts found in ``text``.

    Each entry is a ``{"currency": str | None, "amount": float}``
    dict. Preserves first-seen order. De-dupes on the
    ``(currency, amount)`` pair so a price printed twice in the same
    capture collapses to one entry. Capped at 100 entries.

    Recognises symbol-prefix / symbol-suffix / ISO-code-prefix /
    ISO-code-suffix shapes. ISO codes must match the curated
    :data:`_KNOWN_CODES` set so a stray three-letter prose word
    ("RED", "BIG") that happens to sit next to a number doesn't fire.
    Decimal normalisation handles both ``1,234.56`` (US) and
    ``1.234,56`` (EU) conventions.
    """
    if not text or not isinstance(text, str):
        return []
    work = text
    candidates: list[tuple[int, str | None, float]] = []

    def _mask(start: int, end: int) -> None:
        nonlocal work
        work = work[:start] + (" " * (end - start)) + work[end:]

    # Symbol-prefix matches first because they're the most distinctive
    # (the symbol is a single non-letter glyph adjacent to the number).
    for m in list(_SYMBOL_PREFIX_RE.finditer(work)):
        code = _resolve_symbol(m.group("sym"))
        amount = _normalise_amount(m.group("num"))
        if amount is None:
            continue
        candidates.append((m.start(), code, amount))
        _mask(m.start(), m.end())

    # ISO-code prefix next so a ``USD 12.99`` is captured before the
    # suffix matcher considers ``12.99`` floating.
    for m in list(_CODE_PREFIX_RE.finditer(work)):
        code = m.group("code")
        if code not in _KNOWN_CODES:
            continue
        amount = _normalise_amount(m.group("num"))
        if amount is None:
            continue
        canonical = "CNY" if code == "RMB" else code
        candidates.append((m.start(), canonical, amount))
        _mask(m.start(), m.end())

    # ISO-code suffix.
    for m in list(_CODE_SUFFIX_RE.finditer(work)):
        code = m.group("code")
        if code not in _KNOWN_CODES:
            continue
        amount = _normalise_amount(m.group("num"))
        if amount is None:
            continue
        canonical = "CNY" if code == "RMB" else code
        candidates.append((m.start(), canonical, amount))
        _mask(m.start(), m.end())

    # Symbol-suffix LAST so a ``$12.99`` (already taken by the
    # symbol-prefix matcher) doesn't double-count when paired with
    # an adjacent number.
    for m in list(_SYMBOL_SUFFIX_RE.finditer(work)):
        code = _resolve_symbol(m.group("sym"))
        amount = _normalise_amount(m.group("num"))
        if amount is None:
            continue
        candidates.append((m.start(), code, amount))
        _mask(m.start(), m.end())

    candidates.sort(key=lambda x: x[0])
    out: list[dict] = []
    seen: set[tuple[str | None, float]] = set()
    for _, code, amount in candidates:
        key = (code, amount)
        if key in seen:
            continue
        seen.add(key)
        entry: dict = {"amount": amount}
        if code is not None:
            entry["currency"] = code
        else:
            entry["currency"] = None
        out.append(entry)
        if len(out) >= _MAX_AMOUNTS:
            break
    return out


__all__ = ["extract_amounts"]
