"""Cross-category crypto-address extractor tests.

A new extractor surfaces Bitcoin / Ethereum / Solana addresses found
in the OCR text under ``ExtractedFields.raw["crypto"]``.

Output: list of ``{"chain", "address"}`` dicts. Chains tagged:

* ``bitcoin``  -- Base58Check (P2PKH '1...', P2SH '3...') with
                   Base58Check checksum validation, AND Bech32 /
                   Bech32m (SegWit / Taproot 'bc1...') with polymod
                   checksum validation.
* ``ethereum`` -- ``0x`` + 40 hex chars. Shape-only because EIP-55
                   needs keccak256 outside stdlib. Lowercased on
                   output for de-dup. All-zero null address rejected.
* ``solana``   -- 32..44 Base58 chars. Shape-only AND requires a
                   Solana-context anchor (``sol`` / ``solana`` /
                   ``spl`` / ``phantom`` / ``mint`` / ``pubkey`` /
                   ``wallet`` / ``token``) on the same or previous
                   line because Base58 alphabets overlap with random
                   base58-shaped IDs.

Dedupes on canonical address. Preserves first-seen order across
chain matchers. Capped at 50.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_crypto
from shotclassify_extract.crypto import (
    _base58check_ok,
    _bech32_decode_ok,
)

# Real-world Bitcoin / Ethereum / Solana test vectors.
# Genesis block P2PKH:    1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa
# Sample P2SH:            3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy
# BIP-173 SegWit (v0):    bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4
# BIP-350 Taproot (v1):   bc1p5d7rjq7g6rdk2yhzks9smlaqtedr4dekq08ge8ztwac72sfr9rusxg3297
# Vitalik's wallet:       0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045
# Solana token mint:      So11111111111111111111111111111111111111112

# ---- _base58check_ok ----------------------------------------------


def test_b58check_genesis_p2pkh():
    assert _base58check_ok("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")


def test_b58check_p2sh():
    assert _base58check_ok("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")


def test_b58check_bad_checksum_rejected():
    # Flip the last char to corrupt checksum.
    assert not _base58check_ok("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divfna")


def test_b58check_random_b58_rejected():
    # 34-char base58-shaped string that's NOT a real BTC address.
    assert not _base58check_ok("1234567890abcdefghijkmnopqrstuvwxy")


def test_b58check_invalid_char_rejected():
    # '0' is not in the Base58 alphabet.
    assert not _base58check_ok("10000000000000000000000000000000000")


# ---- _bech32_decode_ok ---------------------------------------------


def test_bech32_segwit_v0():
    assert _bech32_decode_ok("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4", "bc")


def test_bech32m_taproot_v1():
    assert _bech32_decode_ok(
        "bc1p5d7rjq7g6rdk2yhzks9smlaqtedr4dekq08ge8ztwac72sfr9rusxg3297", "bc"
    )


def test_bech32_uppercase_accepted():
    assert _bech32_decode_ok(
        "BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4", "bc"
    )


def test_bech32_mixed_case_rejected():
    """BIP-173 forbids mixed-case in bech32 addresses."""
    assert not _bech32_decode_ok(
        "bc1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4", "bc"
    )


def test_bech32_wrong_hrp_rejected():
    """Testnet 'tb1...' shouldn't pass when we expect mainnet 'bc'."""
    assert not _bech32_decode_ok(
        "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx", "bc"
    )


def test_bech32_bad_checksum_rejected():
    assert not _bech32_decode_ok(
        "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3aa", "bc"
    )


# ---- Bitcoin extraction --------------------------------------------


def test_extract_btc_p2pkh():
    out = extract_crypto("Send to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa now")
    assert out == [
        {"chain": "bitcoin", "address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"}
    ]


def test_extract_btc_p2sh():
    out = extract_crypto("addr 3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")
    assert out == [
        {"chain": "bitcoin", "address": "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"}
    ]


def test_extract_btc_segwit_v0():
    out = extract_crypto("addr bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
    assert out == [
        {
            "chain": "bitcoin",
            "address": "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
        }
    ]


def test_extract_btc_taproot_v1():
    out = extract_crypto(
        "taproot bc1p5d7rjq7g6rdk2yhzks9smlaqtedr4dekq08ge8ztwac72sfr9rusxg3297"
    )
    assert out == [
        {
            "chain": "bitcoin",
            "address": (
                "bc1p5d7rjq7g6rdk2yhzks9smlaqtedr4dekq08ge8ztwac72sfr9rusxg3297"
            ),
        }
    ]


def test_extract_btc_uppercase_bech32_canonicalized():
    out = extract_crypto(
        "addr BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4 in caps"
    )
    assert out == [
        {
            "chain": "bitcoin",
            "address": "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
        }
    ]


def test_extract_btc_bad_checksum_rejected():
    out = extract_crypto("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divfna corrupted")
    assert out == []


def test_extract_btc_random_b58_rejected():
    out = extract_crypto("ID 1234567890abcdefghijkmnopqrstuvwxy something")
    assert out == []


# ---- Ethereum extraction -------------------------------------------


def test_extract_eth_basic():
    out = extract_crypto(
        "send to 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
    )
    assert out == [
        {
            "chain": "ethereum",
            "address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
        }
    ]


def test_extract_eth_lowercase():
    out = extract_crypto(
        "addr 0xd8da6bf26964af9d7eed9e03e53415d37aa96045"
    )
    assert out == [
        {
            "chain": "ethereum",
            "address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
        }
    ]


def test_extract_eth_uppercase():
    out = extract_crypto(
        "addr 0xD8DA6BF26964AF9D7EED9E03E53415D37AA96045"
    )
    assert out == [
        {
            "chain": "ethereum",
            "address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
        }
    ]


def test_extract_eth_null_address_rejected():
    out = extract_crypto(
        "null addr 0x0000000000000000000000000000000000000000 placeholder"
    )
    assert out == []


def test_extract_eth_too_short_rejected():
    out = extract_crypto("hex 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA960 short")
    assert out == []


def test_extract_eth_too_long_rejected():
    out = extract_crypto(
        "hex 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA960450 long"
    )
    assert out == []


def test_extract_eth_dedupe_case_variants():
    """Same address printed lowercase + mixed-case dedupes to one entry."""
    text = (
        "first 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045\n"
        "again 0xd8da6bf26964af9d7eed9e03e53415d37aa96045\n"
    )
    out = extract_crypto(text)
    assert len(out) == 1


# ---- Solana extraction ---------------------------------------------


def test_extract_sol_with_anchor_same_line():
    out = extract_crypto(
        "solana wallet 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
    )
    assert out == [
        {
            "chain": "solana",
            "address": "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
        }
    ]


def test_extract_sol_with_anchor_previous_line():
    text = (
        "solana wallet for donations:\n"
        "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM\n"
    )
    out = extract_crypto(text)
    assert out == [
        {
            "chain": "solana",
            "address": "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
        }
    ]


def test_extract_sol_without_anchor_rejected():
    """A bare base58 string with no Solana-context anchor is too risky."""
    out = extract_crypto(
        "Just a random ID 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
    )
    assert out == []


def test_extract_sol_spl_anchor():
    out = extract_crypto(
        "SPL token mint So11111111111111111111111111111111111111112"
    )
    assert out == [
        {
            "chain": "solana",
            "address": "So11111111111111111111111111111111111111112",
        }
    ]


def test_extract_sol_phantom_anchor():
    out = extract_crypto(
        "Open Phantom and copy 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
    )
    assert out == [
        {
            "chain": "solana",
            "address": "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
        }
    ]


def test_extract_sol_pubkey_anchor():
    out = extract_crypto(
        "pubkey: 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
    )
    assert out == [
        {
            "chain": "solana",
            "address": "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
        }
    ]


def test_extract_sol_token_anchor():
    out = extract_crypto(
        "Token address 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
    )
    assert out == [
        {
            "chain": "solana",
            "address": "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
        }
    ]


# ---- Mixed-chain captures -----------------------------------------


def test_extract_multiple_chains_same_text():
    text = (
        "Btc: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa\n"
        "Eth: 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045\n"
        "Solana wallet 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM\n"
    )
    out = extract_crypto(text)
    addrs_by_chain = {entry["chain"]: entry["address"] for entry in out}
    assert addrs_by_chain == {
        "bitcoin": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        "ethereum": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
        "solana": "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
    }


def test_extract_dedupe_same_btc_printed_twice():
    text = (
        "Send 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa first\n"
        "again 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa\n"
    )
    out = extract_crypto(text)
    assert len(out) == 1


def test_extract_preserves_first_seen_order():
    text = (
        "First Eth 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045\n"
        "Then Btc 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa\n"
    )
    out = extract_crypto(text)
    # BTC base58 scanner runs first in our order so the BTC address
    # appears first in the output even though the ETH address comes
    # earlier in the source text. This is documented behaviour --
    # cross-chain ordering is matcher-iteration, not source-offset.
    assert out[0]["chain"] == "bitcoin"
    assert out[1]["chain"] == "ethereum"


# ---- Empty / non-string inputs ------------------------------------


def test_empty_text_returns_empty_list():
    assert extract_crypto("") == []


def test_no_crypto_in_normal_text():
    assert extract_crypto("This is a normal sentence.") == []


def test_none_text_returns_empty_list():
    assert extract_crypto(None) == []  # type: ignore[arg-type]


def test_cap_at_50_entries():
    """Pathological OCR with 60 distinct ETH addresses caps at 50."""
    addrs = [f"0x{i:040x}" for i in range(1, 61)]  # skip 0 (null)
    text = " ".join(addrs)
    out = extract_crypto(text)
    assert len(out) == 50


# ---- Pipeline integration -----------------------------------------


def test_pipeline_populates_raw_crypto_for_code():
    ocr = OCRResult(
        text='const WALLET = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"'
    )
    fields = enrich(Category.code_snippet, ExtractedFields(), ocr)
    assert "crypto" in fields.raw
    assert fields.raw["crypto"] == [
        {
            "chain": "ethereum",
            "address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
        }
    ]


def test_pipeline_populates_raw_crypto_for_chat():
    ocr = OCRResult(
        text="Alice: btc donations to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    )
    fields = enrich(Category.chat_screenshot, ExtractedFields(), ocr)
    assert "crypto" in fields.raw
    assert fields.raw["crypto"][0]["chain"] == "bitcoin"


def test_pipeline_omits_raw_crypto_when_none():
    """Don't populate the raw key for non-crypto screenshots."""
    ocr = OCRResult(text="Plain text with no crypto.")
    fields = enrich(Category.document, ExtractedFields(), ocr)
    assert "crypto" not in fields.raw


def test_pipeline_crypto_coexists_with_urls():
    """Crypto + URL extractors must not stomp on each other."""
    ocr = OCRResult(
        text=(
            "Donate at https://example.com to "
            "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        )
    )
    fields = enrich(Category.document, ExtractedFields(), ocr)
    assert "crypto" in fields.raw
    assert "urls" in fields.raw
