"""Tests for the cross-category academic / publishing identifier extractor.

The extractor pulls four typed identifier classes out of OCR text and
stashes them under ``ExtractedFields.raw["identifiers"]`` as a list of
``{"type", "value"}`` dicts. Types: ``ISBN`` (10 or 13, validated via
check digit), ``DOI`` (Crossref shape), ``arXiv`` (legacy + new), and
``ISSN`` (8-digit with mod-11 check).

Document and chart screenshots are the obvious use case, but a code
snippet's docstring or chat message can also cite a DOI, so the
extractor runs cross-category just like urls/paths/network/emails.
"""
from __future__ import annotations

import pytest
from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_identifiers

# ---- DOI ---------------------------------------------------------------


def test_doi_basic():
    out = extract_identifiers("see DOI 10.1038/nature12373 for refs")
    assert out == [{"type": "DOI", "value": "10.1038/nature12373"}]


def test_doi_with_trailing_period_trimmed():
    out = extract_identifiers("paper at 10.1145/3372297.3417883.")
    assert out == [{"type": "DOI", "value": "10.1145/3372297.3417883"}]


def test_doi_inside_parentheses_trims():
    out = extract_identifiers("(see 10.1038/nature12373)")
    assert out == [{"type": "DOI", "value": "10.1038/nature12373"}]


def test_doi_unicode_dash_in_suffix_ok():
    """Real DOIs sometimes include dashes / underscores; allow them."""
    out = extract_identifiers("DOI: 10.1109/MIC.2019.2911426")
    assert out == [{"type": "DOI", "value": "10.1109/MIC.2019.2911426"}]


# ---- ISBN-13 -----------------------------------------------------------


def test_isbn13_hyphenated():
    """Canonical hyphenated form on a book back."""
    out = extract_identifiers("ISBN 978-3-16-148410-0")
    assert out == [{"type": "ISBN", "value": "9783161484100"}]


def test_isbn13_digits_only():
    out = extract_identifiers("barcode 9780306406157 reads")
    assert out == [{"type": "ISBN", "value": "9780306406157"}]


def test_isbn13_invalid_check_digit_rejected():
    """Random 13-digit run (failing EAN-13 check) is NOT extracted."""
    out = extract_identifiers("see 9999999999999 on the wrapper")
    assert out == []


# ---- ISBN-10 -----------------------------------------------------------


def test_isbn10_hyphenated():
    out = extract_identifiers("older ISBN 0-306-40615-2 cover")
    assert out == [{"type": "ISBN", "value": "0306406152"}]


def test_isbn10_with_x_check_digit():
    """An ISBN-10 ending in X is valid; the X represents 10."""
    # Real example: 'Modern Information Retrieval' is 020139829X.
    out = extract_identifiers("book 020139829X paperback")
    assert out == [{"type": "ISBN", "value": "020139829X"}]


def test_isbn10_invalid_rejected():
    out = extract_identifiers("see 1234567890 in catalog")
    assert out == []


# ---- arXiv -------------------------------------------------------------


def test_arxiv_new_form_with_version():
    out = extract_identifiers("see arXiv:2306.12345v2 for proof")
    assert out == [{"type": "arXiv", "value": "2306.12345v2"}]


def test_arxiv_new_form_no_version():
    out = extract_identifiers("see arXiv:2306.12345 for proof")
    assert out == [{"type": "arXiv", "value": "2306.12345"}]


def test_arxiv_legacy_form_subject_class():
    out = extract_identifiers("legacy arXiv:hep-th/9901002 paper")
    assert out == [{"type": "arXiv", "value": "hep-th/9901002"}]


def test_arxiv_requires_prefix():
    """A bare ``2306.12345`` without ``arXiv:`` is too ambiguous to
    extract (looks like a version string); we require the prefix."""
    out = extract_identifiers("Python 3.11.5 has 2306.12345 issues")
    # Not extracted as arXiv (no prefix).
    assert all(e["type"] != "arXiv" for e in out)


# ---- ISSN --------------------------------------------------------------


def test_issn_basic():
    """Nature's ISSN: 0028-0836."""
    out = extract_identifiers("Nature ISSN 0028-0836 cites it")
    assert {"type": "ISSN", "value": "0028-0836"} in out


def test_issn_invalid_check_rejected():
    """A random 4-3-1 grouping that fails the mod-11 check is rejected."""
    out = extract_identifiers("see 1234-5678 in catalog")
    # 1234-5678 happens to not pass mod-11; should be empty (or at
    # minimum no ISSN entry).
    assert all(e["type"] != "ISSN" for e in out)


# ---- multiple identifiers, ordering -----------------------------------


def test_multiple_identifiers_preserves_priority_order():
    """When several identifier types appear, the output groups by the
    matcher's priority (arXiv first, then DOI, then ISBN, then ISSN)."""
    text = (
        "See arXiv:2306.12345 and DOI 10.1038/nature12373 "
        "and ISBN 978-3-16-148410-0 and ISSN 0028-0836."
    )
    out = extract_identifiers(text)
    types = [e["type"] for e in out]
    assert types == ["arXiv", "DOI", "ISBN", "ISSN"]


def test_duplicate_identifiers_deduped():
    text = "10.1038/nature12373 cited again as 10.1038/nature12373"
    out = extract_identifiers(text)
    assert out == [{"type": "DOI", "value": "10.1038/nature12373"}]


def test_doi_does_not_double_count_as_isbn():
    """A DOI body contains many digits; the masking step prevents the
    ISBN-13 regex from re-extracting any 13-digit subsequence."""
    out = extract_identifiers("see 10.1145/3372297.3417883 only")
    assert out == [{"type": "DOI", "value": "10.1145/3372297.3417883"}]


def test_empty_or_none_returns_empty_list():
    assert extract_identifiers("") == []
    assert extract_identifiers(None) == []  # type: ignore[arg-type]
    assert extract_identifiers("no identifiers here") == []


# ---- pipeline integration ---------------------------------------------


@pytest.mark.parametrize(
    "category",
    [
        Category.receipt,
        Category.code_snippet,
        Category.error_stacktrace,
        Category.chat_screenshot,
        Category.document,
        Category.meme,
        Category.ui_mockup,
        Category.chart,
        Category.other,
    ],
)
def test_enrich_populates_raw_identifiers_for_every_category(category):
    ocr = OCRResult(
        text="cite arXiv:2306.12345 and DOI 10.1038/nature12373",
        word_count=5,
    )
    out = enrich(category, ExtractedFields(), ocr)
    ids = out.raw.get("identifiers", [])
    assert {"type": "arXiv", "value": "2306.12345"} in ids
    assert {"type": "DOI", "value": "10.1038/nature12373"} in ids


def test_enrich_omits_raw_identifiers_when_text_has_none():
    ocr = OCRResult(text="plain words only no refs", word_count=5)
    out = enrich(Category.document, ExtractedFields(), ocr)
    assert "identifiers" not in out.raw


def test_enrich_preserves_other_raw_keys_alongside_identifiers():
    ocr = OCRResult(
        text="cite https://example.com and DOI 10.1038/nature12373",
        word_count=4,
    )
    fields = ExtractedFields(raw={"trace_id": "abc"})
    out = enrich(Category.document, fields, ocr)
    assert out.raw["trace_id"] == "abc"
    assert out.raw["urls"] == ["https://example.com"]
    assert out.raw["identifiers"] == [
        {"type": "DOI", "value": "10.1038/nature12373"}
    ]
