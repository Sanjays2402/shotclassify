"""Receipt loyalty / store / register identifier extraction.

Three new ``ReceiptFields`` slots populate from common identifier
lines printed on retail receipts:

* ``loyalty_id`` -- customer-side membership identifier (``Member:
  12345``, ``Loyalty #ABC-99``, ``Rewards ID 4477``).
* ``store_id`` -- location-side identifier (``Store #1234``,
  ``Branch 045``, ``Location 12``, ``Shop No. 7``).
* ``register_id`` -- terminal-side identifier (``REG 02``,
  ``Register #3``, ``Terminal 5``, ``Till 04``, ``POS 12``,
  ``Lane 4``).

All three are stored as strings (alphanumeric + ``./-`` allowed).
A leading ``#`` on the value is consumed by the keyword pattern so
the captured value is bare. First-keyword-wins within each
category; first-occurrence-wins within a single keyword. Length
bounded 1..30 chars; values without a digit are rejected.
"""
from __future__ import annotations

from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract import enrich_receipt
from shotclassify_extract.receipt import (
    _find_loyalty_id,
    _find_register_id,
    _find_store_id,
    parse_receipt_text,
)

# ---- loyalty_id ------------------------------------------------------


def test_loyalty_member_colon_digits():
    assert _find_loyalty_id("Member: 12345") == "12345"


def test_loyalty_member_id_keyword():
    assert _find_loyalty_id("Member ID 99001") == "99001"


def test_loyalty_membership_number():
    assert _find_loyalty_id("Membership No. 4477") == "4477"


def test_loyalty_keyword_with_alphanumeric():
    assert _find_loyalty_id("Loyalty #ABC-99") == "ABC-99"


def test_loyalty_number_keyword():
    assert _find_loyalty_id("Loyalty Number 1234") == "1234"


def test_loyalty_rewards_id():
    assert _find_loyalty_id("Rewards ID: 4477") == "4477"


def test_loyalty_rewards_plural():
    assert _find_loyalty_id("Rewards Number 8800") == "8800"


def test_loyalty_reward_member_with_hash():
    assert _find_loyalty_id("Reward Member #88") == "88"


def test_loyalty_member_bare():
    """Bare ``Member 7788`` (no separator) still matches."""
    assert _find_loyalty_id("Member 7788") == "7788"


def test_loyalty_returns_first_occurrence():
    """When the same keyword matches twice, the FIRST occurrence wins."""
    text = "Member: 12345\nMember: 99999"
    assert _find_loyalty_id(text) == "12345"


def test_loyalty_catalog_priority_specific_wins():
    """``Loyalty Number`` is checked before the bare ``Member`` keyword.

    A receipt with both ``Member: A`` and ``Loyalty Number B`` resolves
    to B because the more specific keyword sits earlier in the
    catalogue. This matches the order-number / refund-amount helpers
    that also use catalogue priority instead of source-text offset.
    """
    text = "Member: 12345\nLoyalty Number 99999"
    assert _find_loyalty_id(text) == "99999"


def test_loyalty_none_for_empty():
    assert _find_loyalty_id("") is None
    assert _find_loyalty_id("   ") is None


def test_loyalty_no_digit_rejected():
    """``Member: see card`` has no digit -> reject."""
    assert _find_loyalty_id("Member: see card") is None


def test_loyalty_word_boundary_rejects_prefix():
    """``Remember 1234`` must not fire the ``member`` matcher."""
    assert _find_loyalty_id("Remember 1234 dollars") is None


def test_loyalty_too_long_value_rejected():
    """A value longer than 30 chars (likely OCR garbage) is rejected."""
    long_val = "A" * 35 + "1"
    assert _find_loyalty_id(f"Member {long_val}") is None


def test_loyalty_case_insensitive():
    assert _find_loyalty_id("MEMBER: 7788") == "7788"
    assert _find_loyalty_id("loyalty number 99") == "99"


# ---- store_id --------------------------------------------------------


def test_store_hash_digits():
    assert _find_store_id("Store #1234") == "1234"


def test_store_no_dot_keyword():
    assert _find_store_id("Store No. 045") == "045"


def test_store_number_keyword():
    assert _find_store_id("Store Number 12") == "12"


def test_store_id_keyword():
    assert _find_store_id("Store ID 7") == "7"


def test_store_branch_keyword():
    assert _find_store_id("Branch 045") == "045"


def test_store_branch_with_hash():
    assert _find_store_id("Branch #99") == "99"


def test_store_location_keyword():
    assert _find_store_id("Location 12") == "12"


def test_store_location_id():
    assert _find_store_id("Location ID: 4477") == "4477"


def test_store_shop_keyword():
    assert _find_store_id("Shop No. 7") == "7"


def test_store_alphanumeric_value():
    assert _find_store_id("Store #ABC-1234") == "ABC-1234"


def test_store_first_keyword_wins_over_branch():
    """``Store`` family is checked before ``Branch`` family."""
    text = "Store #1\nBranch 99"
    assert _find_store_id(text) == "1"


def test_store_word_boundary_rejects_bookstore():
    """``Bookstore #1`` must not fire the ``Store`` matcher."""
    assert _find_store_id("Bookstore #1") is None


def test_store_no_digit_rejected():
    assert _find_store_id("Store closed today") is None


def test_store_none_for_empty():
    assert _find_store_id("") is None
    assert _find_store_id("   ") is None


def test_store_case_insensitive():
    assert _find_store_id("STORE #99") == "99"
    assert _find_store_id("branch no. 12") == "12"


# ---- register_id -----------------------------------------------------


def test_register_reg_short():
    assert _find_register_id("REG 02") == "02"


def test_register_keyword_with_hash():
    assert _find_register_id("Register #3") == "3"


def test_register_reg_hash():
    assert _find_register_id("Reg #04") == "04"


def test_register_number_keyword():
    assert _find_register_id("Register Number 12") == "12"


def test_register_id_keyword():
    assert _find_register_id("Register ID: 04") == "04"


def test_register_terminal_keyword():
    assert _find_register_id("Terminal 5") == "5"


def test_register_terminal_id():
    assert _find_register_id("Terminal ID 99") == "99"


def test_register_till_keyword():
    assert _find_register_id("Till 04") == "04"


def test_register_till_no_dot():
    assert _find_register_id("Till No. 12") == "12"


def test_register_pos_keyword():
    """``POS`` is the industry term for a register / point-of-sale."""
    assert _find_register_id("POS No. 12") == "12"


def test_register_lane_keyword():
    """Supermarket vocabulary: ``Lane 4``."""
    assert _find_register_id("Lane 4") == "4"


def test_register_first_keyword_wins():
    """``Register`` family beats ``Terminal`` when both appear."""
    text = "Register #2\nTerminal 99"
    assert _find_register_id(text) == "2"


def test_register_no_digit_rejected():
    assert _find_register_id("Register open") is None


def test_register_none_for_empty():
    assert _find_register_id("") is None
    assert _find_register_id("   ") is None


def test_register_case_insensitive():
    assert _find_register_id("REGISTER #02") == "02"
    assert _find_register_id("till 4") == "4"


def test_register_word_boundary_rejects_preregister():
    """``Preregister 99`` must not fire (alpha char precedes the keyword)."""
    assert _find_register_id("Preregister 99") is None


# ---- parse_receipt_text wiring ---------------------------------------


def _full_receipt(extra: str) -> str:
    return (
        "Cafe Roma\n"
        "123 Main Street\n"
        f"{extra}\n"
        "Subtotal 10.00\n"
        "Tax 1.00\n"
        "Total 11.00\n"
    )


def test_parse_receipt_text_member_line():
    fields = parse_receipt_text(_full_receipt("Member: 12345"))
    assert fields.loyalty_id == "12345"
    assert fields.store_id is None
    assert fields.register_id is None


def test_parse_receipt_text_store_line():
    fields = parse_receipt_text(_full_receipt("Store #1234"))
    assert fields.store_id == "1234"
    assert fields.loyalty_id is None
    assert fields.register_id is None


def test_parse_receipt_text_register_line():
    fields = parse_receipt_text(_full_receipt("REG 02"))
    assert fields.register_id == "02"
    assert fields.loyalty_id is None
    assert fields.store_id is None


def test_parse_receipt_text_all_three_present():
    text = _full_receipt("Store #1234\nREG 02\nMember: 7788")
    fields = parse_receipt_text(text)
    assert fields.store_id == "1234"
    assert fields.register_id == "02"
    assert fields.loyalty_id == "7788"


def test_parse_receipt_text_no_ids_defaults_none():
    fields = parse_receipt_text(_full_receipt(""))
    assert fields.loyalty_id is None
    assert fields.store_id is None
    assert fields.register_id is None


# ---- enrich_receipt: caller-supplied value wins ----------------------


def test_enrich_receipt_caller_supplied_loyalty_wins():
    """LLM-supplied loyalty_id is preserved; heuristic only fills gaps."""
    existing = ReceiptFields(loyalty_id="LLM-99")
    ocr = OCRResult(text=_full_receipt("Member: 12345"))
    out = enrich_receipt(existing, ocr)
    assert out.loyalty_id == "LLM-99"


def test_enrich_receipt_fills_loyalty_when_caller_silent():
    existing = ReceiptFields(vendor="Cafe")
    ocr = OCRResult(text=_full_receipt("Loyalty Number 1234"))
    out = enrich_receipt(existing, ocr)
    assert out.loyalty_id == "1234"


def test_enrich_receipt_fills_store_when_caller_silent():
    existing = ReceiptFields(vendor="Cafe")
    ocr = OCRResult(text=_full_receipt("Branch 045"))
    out = enrich_receipt(existing, ocr)
    assert out.store_id == "045"


def test_enrich_receipt_fills_register_when_caller_silent():
    existing = ReceiptFields(vendor="Cafe")
    ocr = OCRResult(text=_full_receipt("Terminal 5"))
    out = enrich_receipt(existing, ocr)
    assert out.register_id == "5"


def test_enrich_receipt_independent_fills():
    """Each ID field fills independently of the others."""
    existing = ReceiptFields(store_id="OLD-STORE")
    ocr = OCRResult(text=_full_receipt("Store #NEW\nREG 04\nMember: 999"))
    out = enrich_receipt(existing, ocr)
    assert out.store_id == "OLD-STORE"
    assert out.register_id == "04"
    assert out.loyalty_id == "999"


# ---- LLM wire-format passthrough -------------------------------------


def test_llm_wire_format_passes_through_loyalty_id():
    from shotclassify_classify.client import _parse_llm_payload

    payload = {
        "primary": "receipt",
        "confidences": [{"category": "receipt", "score": 0.9}],
        "rationale": "test",
        "fields": {
            "receipt": {
                "vendor": "Cafe",
                "loyalty_id": "ABC-9988",
                "store_id": "045",
                "register_id": "04",
            }
        },
    }
    _, fields = _parse_llm_payload(payload)
    assert fields.receipt is not None
    assert fields.receipt.loyalty_id == "ABC-9988"
    assert fields.receipt.store_id == "045"
    assert fields.receipt.register_id == "04"
