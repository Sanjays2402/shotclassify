"""Cross-category crypto-address extractor.

Bitcoin / Ethereum / Solana addresses surface in code snippets
(``const ADDR = "0x..."``), error logs ("Invalid address 0xabc..."),
chat captures (donation links), and document captures (whitepapers,
exchange screenshots, payment landing pages). Rather than teach each
per-category extractor to find these, we run :func:`extract_crypto`
once on the OCR text and stash unique entries under
``ExtractedFields.raw["crypto"]``.

Output shape: a list of ``{"chain", "address"}`` dicts. Chain tags:

* ``bitcoin``   -- Base58Check P2PKH (``1...``), P2SH (``3...``),
                   Bech32 SegWit (``bc1...``) and Bech32m Taproot
                   (``bc1p...``).
* ``ethereum``  -- ``0x`` + 40 hex chars. We accept any case
                   variant (all-lower / all-upper / mixed) without
                   enforcing EIP-55 checksum because that requires
                   keccak256 (not stdlib) and most real-world
                   addresses are pasted lowercase.
* ``solana``    -- 32..44 Base58 chars (no Base58Check checksum --
                   Solana uses raw ed25519 public keys with no
                   built-in checksum -- so we accept by shape).

Output preserves first-seen order across all chain matchers and is
capped at 50 entries. De-dupes on the ``address`` value so the same
address printed multiple times in the same screenshot collapses to
one entry.

Validation philosophy:

* Bitcoin **Base58Check** addresses (P2PKH / P2SH) carry a 4-byte
  SHA256(SHA256(payload))[:4] checksum at the tail. We validate the
  checksum so a random 34-char Base58-shaped string does NOT pass
  as a Bitcoin address. This is the most common false-positive
  source on snippets that quote hashes / IDs.
* Bitcoin **Bech32 / Bech32m** addresses (SegWit / Taproot) carry a
  6-char BCH polymod checksum. We validate by computing the
  polymod (small pure-Python helper) and accepting only addresses
  whose polymod equals the right constant for their HRP + length
  combination.
* **Ethereum** is shape-only: 0x + 40 hex chars. No checksum
  validation because EIP-55 requires keccak256 outside stdlib.
* **Solana** is shape-only: 32..44 Base58 chars. Solana uses raw
  ed25519 public keys with no checksum; any 32..44 base58 string
  has a chance of being a valid pubkey. We narrow false-positives
  by requiring a leading context-word anchor (``sol`` / ``solana`` /
  ``spl`` / ``phantom`` / ``mint`` / ``pubkey`` / ``wallet`` /
  ``token``) on the same or previous line. Without an anchor we
  reject the shape because base58 alphabets overlap heavily with
  random base58-shaped IDs that are not addresses.
"""
from __future__ import annotations

import hashlib
import re

# ---- Base58Check helpers (Bitcoin P2PKH / P2SH) --------------------

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX = {c: i for i, c in enumerate(_BASE58_ALPHABET)}


def _base58_decode(s: str) -> bytes | None:
    """Decode a Base58 string to bytes. Return None on any invalid
    character (so callers can short-circuit without exception
    handling)."""
    n = 0
    for ch in s:
        idx = _BASE58_INDEX.get(ch)
        if idx is None:
            return None
        n = n * 58 + idx
    # Convert to bytes (preserve leading zero bytes for each leading "1")
    nbytes = max(1, (n.bit_length() + 7) // 8)
    body = n.to_bytes(nbytes, "big") if n else b""
    leading_zeros = len(s) - len(s.lstrip("1"))
    return b"\x00" * leading_zeros + body


def _base58check_ok(s: str) -> bool:
    """Return True when ``s`` is a valid Base58Check string -- the last
    4 bytes match SHA256(SHA256(payload))[:4]."""
    raw = _base58_decode(s)
    if raw is None or len(raw) < 5:
        return False
    payload, checksum = raw[:-4], raw[-4:]
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return checksum == expected


# ---- Bech32 / Bech32m helpers (Bitcoin SegWit / Taproot) -----------

_BECH32_ALPHABET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_INDEX = {c: i for i, c in enumerate(_BECH32_ALPHABET)}
_BECH32_CONST = 1
_BECH32M_CONST = 0x2BC830A3


def _bech32_polymod(values: list[int]) -> int:
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if (b >> i) & 1:
                chk ^= gen[i]
    return chk


def _bech32_hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _bech32_verify(hrp: str, data: list[int]) -> int | None:
    """Return the polymod constant used (1 for bech32, 0x2bc830a3 for
    bech32m) if the checksum matches one of them; None otherwise."""
    polymod = _bech32_polymod(_bech32_hrp_expand(hrp) + data)
    if polymod == _BECH32_CONST:
        return _BECH32_CONST
    if polymod == _BECH32M_CONST:
        return _BECH32M_CONST
    return None


def _bech32_decode_ok(addr: str, expected_hrp: str) -> bool:
    """Return True when ``addr`` is a syntactically valid bech32 /
    bech32m address with the expected HRP (``bc`` for mainnet)."""
    addr_low = addr.lower()
    if addr != addr_low and addr != addr.upper():
        return False  # mixed-case is invalid per BIP-173
    addr = addr_low
    pos = addr.rfind("1")
    if pos < 1 or pos + 7 > len(addr):
        return False
    hrp = addr[:pos]
    if hrp != expected_hrp:
        return False
    data_part = addr[pos + 1:]
    if any(c not in _BECH32_INDEX for c in data_part):
        return False
    data = [_BECH32_INDEX[c] for c in data_part]
    const = _bech32_verify(hrp, data)
    if const is None:
        return False
    # Witness version (first data byte) decides bech32 vs bech32m
    # per BIP-350: v0 must use bech32 (const=1), v1+ must use bech32m
    # (const=0x2bc830a3).
    witver = data[0]
    if witver == 0 and const != _BECH32_CONST:
        return False
    if witver > 0 and const != _BECH32M_CONST:
        return False
    return True


# ---- Matchers ------------------------------------------------------

# Bitcoin Base58Check: prefix 1 or 3, total 26..35 chars from the
# Base58 alphabet. Word-boundary anchored so we don't bite into a
# longer hash. Validated against Base58Check checksum.
_BTC_B58_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<addr>[13][1-9A-HJ-NP-Za-km-z]{25,34})(?![A-Za-z0-9])"
)

# Bitcoin Bech32 / Bech32m: HRP "bc" + separator "1" + 6..74 chars
# from the bech32 data alphabet. Case-insensitive (BIP-173 forbids
# mixed-case but accepts either all-lower or all-upper); we
# canonicalise to lowercase in the output.
_BTC_BECH32_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<addr>(?:bc|BC)1[A-Za-z0-9]{6,74})(?![A-Za-z0-9])"
)

# Ethereum (and EVM-compatible chains): 0x + 40 hex chars.
_ETH_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<addr>0x[a-fA-F0-9]{40})(?![A-Za-z0-9])"
)

# Solana: 32..44 base58 chars. We REQUIRE a Solana-related context
# anchor on the same or previous line because the base58 alphabet
# overlaps with random base58-shaped IDs in code snippets.
_SOL_CANDIDATE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<addr>[1-9A-HJ-NP-Za-km-z]{32,44})(?![A-Za-z0-9])"
)
_SOL_CONTEXT_RE = re.compile(
    r"\b(?:sol|solana|spl|phantom|mint|pubkey|wallet|token)\b",
    re.IGNORECASE,
)


_MAX_CRYPTO = 50


def _scan_btc_b58(text: str, seen: set[str], out: list[dict[str, str]]) -> None:
    for m in _BTC_B58_RE.finditer(text):
        addr = m.group("addr")
        if not _base58check_ok(addr):
            continue
        if addr in seen or len(out) >= _MAX_CRYPTO:
            continue
        seen.add(addr)
        out.append({"chain": "bitcoin", "address": addr})


def _scan_btc_bech32(text: str, seen: set[str], out: list[dict[str, str]]) -> None:
    for m in _BTC_BECH32_RE.finditer(text):
        addr = m.group("addr")
        if not _bech32_decode_ok(addr, "bc"):
            continue
        canonical = addr.lower()
        if canonical in seen or len(out) >= _MAX_CRYPTO:
            continue
        seen.add(canonical)
        out.append({"chain": "bitcoin", "address": canonical})


def _scan_eth(text: str, seen: set[str], out: list[dict[str, str]]) -> None:
    for m in _ETH_RE.finditer(text):
        addr = m.group("addr")
        # Reject the all-zero "null address" placeholder.
        body = addr[2:]
        if all(c == "0" for c in body):
            continue
        canonical = "0x" + body.lower()
        if canonical in seen or len(out) >= _MAX_CRYPTO:
            continue
        seen.add(canonical)
        out.append({"chain": "ethereum", "address": canonical})


def _line_index_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset)


def _scan_sol(text: str, seen: set[str], out: list[dict[str, str]]) -> None:
    """Solana addresses: require a Solana-related context anchor on the
    same or previous line. Without an anchor a 32..44 base58 string is
    too easy to confuse with random IDs."""
    lines = text.splitlines()
    # Pre-compute which lines have a Solana-context anchor so we can
    # check "current or previous line" in O(1).
    anchor_lines = {i for i, line in enumerate(lines) if _SOL_CONTEXT_RE.search(line)}
    for m in _SOL_CANDIDATE_RE.finditer(text):
        addr = m.group("addr")
        # Skip lookalikes that are already valid BTC base58 addresses
        # -- those should land in seen[] via _scan_btc_b58 first.
        if addr in seen:
            continue
        # Skip if it would be a valid Base58Check (it would have been
        # tagged BTC above) -- this avoids double-tagging a 34-char
        # P2PKH/P2SH that happened to satisfy the Solana shape too.
        if _BTC_B58_RE.fullmatch(addr) and _base58check_ok(addr):
            continue
        line_idx = _line_index_for_offset(text, m.start())
        if line_idx not in anchor_lines and (line_idx - 1) not in anchor_lines:
            continue
        if len(out) >= _MAX_CRYPTO:
            return
        seen.add(addr)
        out.append({"chain": "solana", "address": addr})


def extract_crypto(text: str) -> list[dict[str, str]]:
    """Return unique crypto-address entries found in ``text``.

    Output is a list of ``{"chain", "address"}`` dicts. Chains tagged:
    ``bitcoin`` (Base58Check or Bech32/Bech32m, both validated by
    checksum), ``ethereum`` (shape-only -- 0x + 40 hex), ``solana``
    (shape-only, requires a Solana-context anchor on the same or
    previous line).

    Ethereum and Bitcoin Bech32 addresses are normalised to lowercase
    in the output for de-dup consistency. Bitcoin Base58Check
    addresses preserve their case (the alphabet is case-sensitive).
    The Ethereum all-zero "null address" is rejected as a placeholder.

    Preserves first-seen order across all chain matchers. De-dupes
    on the canonical address. Capped at 50 entries.
    """
    if not text or not isinstance(text, str):
        return []
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    # Order matters: BTC base58check first so a 34-char address that
    # also satisfies the Solana shape is tagged as bitcoin, not
    # tagged twice.
    _scan_btc_b58(text, seen, out)
    _scan_btc_bech32(text, seen, out)
    _scan_eth(text, seen, out)
    _scan_sol(text, seen, out)
    return out


__all__ = ["extract_crypto"]
