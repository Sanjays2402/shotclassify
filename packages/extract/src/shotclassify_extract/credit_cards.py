"""Cross-category credit-card / PAN extractor.

Payment-card numbers (PANs) surface across many categories of
screenshot -- receipts print partial PANs (``Visa ****4242``),
chat captures share card details, error logs occasionally leak a
PAN inside a request body, code snippets carry test PANs as
fixtures, document captures of statements include the full PAN.
Rather than teach each per-category extractor to find them, we run
:func:`extract_credit_cards` once on the OCR text and stash the
unique, order-preserving list under
``ExtractedFields.raw["credit_cards"]`` so dashboards, routing rules,
and downstream agents have a single place to look.

Output shape: a list of ``{"brand", "bin", "last4"}`` dicts. The
full PAN is NEVER stored -- we deliberately persist only the BIN
(first 6 digits) and the last 4 so a downstream consumer can identify
the issuing network and the customer's last-4 without re-exposing
the secret. The :mod:`shotclassify_common.redact` module already
provides a ``credit_card`` mode that swaps the full PAN with a
``[REDACTED:credit_card]`` token; that mode and this extractor work
together (extractor surfaces BIN+last4 metadata; redactor removes
the raw digits before storage).

Recognised shapes:

* **Full 13..19 digit PAN** with single space or dash separators
  between groups, validated via the Luhn checksum. The brand is
  identified from the BIN range using the public network catalogues
  (Visa ``4xxx``, Mastercard ``51-55`` or ``2221-2720``, Amex
  ``34`` / ``37``, Discover ``6011`` / ``65`` / ``644-649``, JCB
  ``35{28-89}``, Diners ``300-305`` / ``36`` / ``38-39``, UnionPay
  ``62``).
* **Partial PAN with masking**: ``****4242``, ``**** **** **** 4242``,
  ``XXXX-XXXX-XXXX-4242``, ``....4242``. When the BIN portion is
  masked, ``bin`` is None and ``last4`` carries the visible 4
  digits. The brand falls back to ``None`` unless an explicit brand
  word (``Visa``, ``Mastercard``, ``Amex``, ``Discover``) sits
  within the same line.

Deliberately NOT matched:

* 13..19 digit runs that fail Luhn (these are not real PANs).
* Phone numbers (the phone extractor's regex is distinct enough
  that we won't bite into one, and the Luhn check filters anyway).
* IBANs (start with two letters; never digit-leading).
* Pure digit IDs that happen to be PAN-length but fail Luhn.
"""
from __future__ import annotations

import re

_MAX_CARDS = 50


def _luhn_ok(digits: str) -> bool:
    """Mod-10 check as published by ISO/IEC 7812."""
    if not digits or not digits.isdigit():
        return False
    s = 0
    alt = False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        s += d
        alt = not alt
    return s > 0 and s % 10 == 0


def _brand_for(digits: str) -> str | None:
    """Identify the issuing brand from the BIN. Returns None when no
    catalogued brand matches.

    Tables drawn from the public ISO/IEC 7812 BIN range publications
    plus each network's own developer docs. Conservative: a digit
    string outside every documented range returns None rather than
    guessing.
    """
    if not digits or len(digits) < 4:
        return None
    n = len(digits)
    d = digits

    # Amex: 15 digits, starts 34 or 37.
    if n == 15 and (d.startswith("34") or d.startswith("37")):
        return "amex"
    # Diners Club: 14 digits, starts 300-305, 36, or 38-39.
    if n == 14:
        if d[:3] in {"300", "301", "302", "303", "304", "305"}:
            return "diners"
        if d[:2] in {"36", "38", "39"}:
            return "diners"
    # Visa: starts 4, length 13 / 16 / 19.
    if d.startswith("4") and n in (13, 16, 19):
        return "visa"
    # Mastercard: starts 51-55, length 16. Or 2221-2720 (the 2017
    # expansion range), length 16.
    if n == 16 and d[:2] in {"51", "52", "53", "54", "55"}:
        return "mastercard"
    if n == 16 and d[:4].isdigit():
        bin4 = int(d[:4])
        if 2221 <= bin4 <= 2720:
            return "mastercard"
    # Discover: 16 digits, starts 6011, 65, or 644-649.
    if n == 16:
        if d.startswith("6011") or d.startswith("65"):
            return "discover"
        if d[:3] in {"644", "645", "646", "647", "648", "649"}:
            return "discover"
    # JCB: 16 digits, starts 3528..3589.
    if n == 16 and d[:4].isdigit():
        bin4 = int(d[:4])
        if 3528 <= bin4 <= 3589:
            return "jcb"
    # UnionPay: 16..19 digits, starts 62.
    if d.startswith("62") and 16 <= n <= 19:
        return "unionpay"
    return None


# 13..19 digit runs with optional single space or dash separators
# between digits. Word boundaries on both sides keep us from biting
# into the middle of a longer digit string. The non-greedy approach
# lands one PAN per run; consumed spans are blanked so a follow-up
# scan does not re-match.
_PAN_RE = re.compile(
    r"\b(?:\d[ -]?){12,18}\d\b"
)

# Masked PAN: a leading run of mask chars (``*``, ``X``, ``x``, ``.``,
# optionally with spaces / dashes between groups) followed by exactly
# 4 trailing digits. We require AT LEAST 4 mask chars so we don't
# false-positive on a stray ``****`` divider or a single ``X``.
_MASKED_PAN_RE = re.compile(
    r"(?:[\*Xx.]{1,4}[ -]?){2,4}(?P<last4>\d{4})\b"
)

# Brand keywords that pin a masked PAN's brand when the BIN is hidden.
# Case-insensitive. We scan the SAME LINE as the masked PAN.
_BRAND_KEYWORDS = {
    "visa": "visa",
    "mastercard": "mastercard",
    "master card": "mastercard",
    "mc": "mastercard",
    "amex": "amex",
    "american express": "amex",
    "discover": "discover",
    "jcb": "jcb",
    "diners": "diners",
    "diners club": "diners",
    "unionpay": "unionpay",
    "union pay": "unionpay",
}


def _line_for(text: str, pos: int) -> str:
    """Return the source line that contains offset ``pos``."""
    start = text.rfind("\n", 0, pos)
    end = text.find("\n", pos)
    if start == -1:
        start = 0
    else:
        start += 1
    if end == -1:
        end = len(text)
    return text[start:end]


def _brand_from_line(line: str) -> str | None:
    """Pick the first brand keyword that appears in ``line``.

    Multi-word keywords are checked before single-word so ``american
    express`` wins over ``american`` (not in the catalogue) and
    ``master card`` wins over ``card`` (also not in the catalogue).
    The implementation iterates a length-sorted catalogue so the
    longer keyword always wins when it sits at the same offset.
    """
    if not line:
        return None
    lower = line.lower()
    best: tuple[int, str] | None = None  # (offset, brand)
    for kw, brand in sorted(_BRAND_KEYWORDS.items(), key=lambda x: -len(x[0])):
        idx = lower.find(kw)
        if idx == -1:
            continue
        # Word boundary on both sides so ``masterclass`` doesn't pin
        # a ``master`` brand. ``mc`` requires word boundaries too so
        # ``mcrib`` isn't matched.
        left = lower[idx - 1] if idx > 0 else " "
        right_idx = idx + len(kw)
        right = lower[right_idx] if right_idx < len(lower) else " "
        if left.isalnum() or right.isalnum():
            continue
        if best is None or idx < best[0]:
            best = (idx, brand)
    return best[1] if best else None


def extract_credit_cards(text: str) -> list[dict[str, str | None]]:
    """Return unique credit cards found in ``text`` as BIN+last4 dicts.

    Each entry is a dict with keys ``brand`` (``visa`` / ``mastercard``
    / ``amex`` / ``discover`` / ``jcb`` / ``diners`` / ``unionpay``
    / ``None``), ``bin`` (first 6 digits as a string, or ``None`` when
    only the last 4 were visible behind a mask), and ``last4`` (last
    4 digits as a string).

    The full PAN is NEVER returned -- the caller intentionally only
    gets BIN+last4 so storage cannot leak the full card. Preserves
    first-seen-in-text order, de-duplicates by ``(brand, bin, last4)``,
    and caps the output at 50 entries.
    """
    if not text or not isinstance(text, str):
        return []
    out: list[dict[str, str | None]] = []
    seen: set[tuple[str | None, str | None, str]] = set()
    work = text

    def _add(brand: str | None, bin_str: str | None, last4: str, start: int, end: int) -> None:
        nonlocal work
        key = (brand, bin_str, last4)
        if key in seen or len(out) >= _MAX_CARDS:
            return
        seen.add(key)
        out.append({"brand": brand, "bin": bin_str, "last4": last4})
        # Blank out the span so neither the full nor the masked PAN
        # matcher can re-pick this PAN.
        work = work[:start] + (" " * (end - start)) + work[end:]

    # 1) Full PANs first -- the Luhn validation is strong enough to
    #    keep noise out, and we want a full match to win before the
    #    masked matcher even sees the line.
    for m in list(_PAN_RE.finditer(work)):
        raw = m.group(0)
        digits = re.sub(r"\D", "", raw)
        if not (13 <= len(digits) <= 19):
            continue
        if not _luhn_ok(digits):
            continue
        brand = _brand_for(digits)
        bin_str = digits[:6]
        last4 = digits[-4:]
        _add(brand, bin_str, last4, m.start(), m.end())

    # 2) Masked PANs. Brand inferred from the same source line via
    #    a brand-keyword scan when present, else None.
    for m in list(_MASKED_PAN_RE.finditer(work)):
        last4 = m.group("last4")
        if not last4.isdigit():
            continue
        line = _line_for(text, m.start())
        brand = _brand_from_line(line)
        _add(brand, None, last4, m.start(), m.end())

    return out


__all__ = ["extract_credit_cards"]
