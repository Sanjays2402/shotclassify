"""Receipt party size / split-bill detection.

A new ``ReceiptFields.party_size`` slot carries the cover count or
split-bill count printed on the receipt. Recognised phrases (case
insensitive):

* ``Party of 4`` / ``Party Size: 6`` / ``Party 2``
* ``Guests: 3`` / ``Guests 3`` / ``# of Guests 4`` / ``No. of Guests 2``
* ``Guest count: 5``
* ``Covers: 8`` (POS industry term)
* ``Split 3 ways`` / ``Split between 4`` / ``Split by 4``
* ``Per person (4)`` / ``Per-person 4``

Party-of / guest cues win over split cues when both appear because the
cover count is the source of truth. Counts outside 1..50 are rejected
as OCR noise.
"""
from __future__ import annotations

from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract import enrich_receipt
from shotclassify_extract.receipt import _detect_party_size, parse_receipt_text

# ---- _detect_party_size helper ---------------------------------------


def test_party_of_n():
    assert _detect_party_size("Party of 4") == 4


def test_party_of_n_inside_sentence():
    assert _detect_party_size("Welcome! Party of 6 tonight") == 6


def test_party_size_colon():
    assert _detect_party_size("Party Size: 8") == 8


def test_party_size_no_colon():
    assert _detect_party_size("Party Size 3") == 3


def test_party_bare_after_colon():
    """Bare ``Party N`` only fires after a colon / comma / line start
    so a stray sentence doesn't trigger.
    """
    assert _detect_party_size("Header: Party 2") == 2


def test_party_bare_after_newline():
    """Bare ``Party N`` at the start of a line also fires."""
    assert _detect_party_size("Subtotal 10.00\nParty 3\n") == 3


def test_party_bare_inside_prose_does_not_fire():
    """``the party 3 days ago`` is prose, not a cover count."""
    assert _detect_party_size("the party 3 days ago") is None


def test_guests_colon():
    assert _detect_party_size("Guests: 4") == 4


def test_guests_no_colon():
    assert _detect_party_size("Guests 5") == 5


def test_guest_singular():
    """Singular ``Guest 1`` still tags (a solo diner)."""
    assert _detect_party_size("Guest 1") == 1


def test_guest_count_colon():
    assert _detect_party_size("Guest count: 5") == 5


def test_hash_of_guests():
    assert _detect_party_size("# of Guests 4") == 4


def test_hash_guests_short():
    assert _detect_party_size("# Guests 4") == 4


def test_no_of_guests_with_period():
    assert _detect_party_size("No. of Guests 2") == 2


def test_no_of_guests_no_period():
    assert _detect_party_size("No of Guests 2") == 2


def test_covers_colon():
    """POS industry term used in fine dining."""
    assert _detect_party_size("Covers: 8") == 8


def test_covers_no_colon():
    assert _detect_party_size("Covers 6") == 6


def test_cover_singular():
    """Singular ``Cover 1`` (one diner) also tags."""
    assert _detect_party_size("Cover 1") == 1


def test_split_n_ways():
    assert _detect_party_size("Split 3 ways") == 3


def test_split_n_way_singular():
    """``Split 2 way`` (some POS systems drop the plural)."""
    assert _detect_party_size("Split 2 way") == 2


def test_split_between():
    assert _detect_party_size("Split between 4 patrons") == 4


def test_split_by():
    assert _detect_party_size("Split by 5") == 5


def test_per_person_with_parens():
    assert _detect_party_size("Per person (4)") == 4


def test_per_person_no_parens():
    """``Per person 4`` (no parens) also tags."""
    assert _detect_party_size("Per person 4") == 4


def test_per_dash_person():
    """Hyphenated form ``per-person 4`` tags."""
    assert _detect_party_size("Per-person 4") == 4


def test_party_wins_over_split_when_both_present():
    """Cover count is the source of truth when both signals appear."""
    text = "Party of 4 ... Split 2 ways"
    assert _detect_party_size(text) == 4


def test_guests_wins_over_split_when_both_present():
    text = "Guests: 6\nSplit 3 ways"
    assert _detect_party_size(text) == 6


def test_none_when_no_signal():
    assert _detect_party_size("Cafe\nSubtotal 10.00\nTotal 11.00\n") is None


def test_none_for_empty_text():
    assert _detect_party_size("") is None
    assert _detect_party_size("   ") is None


def test_zero_rejected():
    """``Party of 0`` is OCR noise; rejected (returns None)."""
    assert _detect_party_size("Party of 0") is None


def test_over_50_rejected():
    """Values above 50 are OCR noise (banquet halls don't print this)."""
    assert _detect_party_size("Party of 99") is None


def test_three_digit_count_rejected():
    """Three-digit count fails the {1,2} digit cap in the regex."""
    assert _detect_party_size("Party of 100") is None


def test_case_insensitive():
    assert _detect_party_size("PARTY OF 4") == 4
    assert _detect_party_size("guests: 3") == 3
    assert _detect_party_size("SPLIT 5 WAYS") == 5


# ---- parse_receipt_text wiring ---------------------------------------


def _receipt(extra_line: str) -> str:
    return f"Bistro\n{extra_line}\nSubtotal 40.00\nTotal 44.00\n"


def test_parse_receipt_text_extracts_party_of():
    fields = parse_receipt_text(_receipt("Party of 4"))
    assert fields.party_size == 4


def test_parse_receipt_text_extracts_split():
    fields = parse_receipt_text(_receipt("Split 3 ways"))
    assert fields.party_size == 3


def test_parse_receipt_text_none_for_solo_receipt():
    fields = parse_receipt_text("Cafe\nSubtotal 10.00\nTotal 11.00\n")
    assert fields.party_size is None


# ---- enrich_receipt: caller-supplied wins ----------------------------


def test_enrich_receipt_caller_supplied_party_wins():
    """LLM-supplied party_size is preserved; the heuristic only fills gaps."""
    existing = ReceiptFields(party_size=2)
    ocr = OCRResult(text="Party of 5")  # heuristic would say 5
    out = enrich_receipt(existing, ocr)
    assert out.party_size == 2


def test_enrich_receipt_fills_when_caller_absent():
    ocr = OCRResult(text="Bistro\nParty of 4\nSubtotal 40.00\nTotal 44.00")
    out = enrich_receipt(None, ocr)
    assert out.party_size == 4


def test_enrich_receipt_none_when_no_signal():
    ocr = OCRResult(text="Cafe\nSubtotal 10.00\nTotal 11.00\n")
    out = enrich_receipt(None, ocr)
    assert out.party_size is None
