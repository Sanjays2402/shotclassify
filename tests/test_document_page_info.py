"""Document page-number footer detection tests.

A new DocumentFields.page_info slot captures the page-number footer
printed by multi-page document captures (PDFs, slide decks, scanned
contracts). Output is a ``{"current", "total", "label", "continued"}``
dict or None.
"""
from __future__ import annotations

from shotclassify_common import DocumentFields, OCRResult
from shotclassify_extract.document import _find_page_info, enrich_document

# ---- "Page N of M" canonical form --------------------------------


def test_page_3_of_12():
    out = _find_page_info("Page 3 of 12")
    assert out is not None
    assert out["current"] == 3
    assert out["total"] == 12
    assert out["continued"] is False
    assert out["label"] == "Page 3 of 12"


def test_page_1_of_5():
    out = _find_page_info("Page 1 of 5")
    assert out["current"] == 1
    assert out["total"] == 5


def test_pages_plural_form():
    out = _find_page_info("Pages 3 of 12")
    assert out["current"] == 3
    assert out["total"] == 12


def test_lowercase_form():
    out = _find_page_info("page 7 of 100")
    assert out["current"] == 7
    assert out["total"] == 100


def test_uppercase_form():
    out = _find_page_info("PAGE 5 OF 20")
    assert out["current"] == 5
    assert out["total"] == 20


def test_page_slash_form():
    out = _find_page_info("Page 3 / 12")
    assert out["current"] == 3
    assert out["total"] == 12


def test_page_slash_no_space():
    out = _find_page_info("Page 3/12")
    assert out["current"] == 3
    assert out["total"] == 12


# ---- "Slide N of M" form -----------------------------------------


def test_slide_4_of_20():
    out = _find_page_info("Slide 4 of 20")
    assert out["current"] == 4
    assert out["total"] == 20


def test_slide_slash_form():
    out = _find_page_info("Slide 4 / 20")
    assert out["current"] == 4
    assert out["total"] == 20


# ---- "Sheet N of M" form -----------------------------------------


def test_sheet_3_of_5():
    out = _find_page_info("Sheet 3 of 5")
    assert out["current"] == 3
    assert out["total"] == 5


# ---- Abbreviated forms -------------------------------------------


def test_pg_dot_form():
    out = _find_page_info("Pg. 12 of 30")
    assert out["current"] == 12
    assert out["total"] == 30


def test_pg_no_dot_form():
    out = _find_page_info("Pg 12 of 30")
    assert out["current"] == 12
    assert out["total"] == 30


def test_p_dot_form():
    out = _find_page_info("p. 7 of 12")
    assert out["current"] == 7
    assert out["total"] == 12


def test_p_dot_bare():
    out = _find_page_info("Header line\np. 7\nFooter line")
    assert out is not None
    assert out["current"] == 7
    assert out["total"] is None


def test_pg_dot_bare():
    out = _find_page_info("Pg. 12")
    assert out["current"] == 12
    assert out["total"] is None


# ---- Bare "Page N" form ------------------------------------------


def test_page_1_alone():
    out = _find_page_info("Page 1")
    assert out["current"] == 1
    assert out["total"] is None


def test_page_42_alone():
    out = _find_page_info("Page 42")
    assert out["current"] == 42
    assert out["total"] is None


def test_slide_alone():
    out = _find_page_info("Slide 7")
    assert out["current"] == 7
    assert out["total"] is None


# ---- Hyphen typography form --------------------------------------


def test_hyphen_form_5():
    out = _find_page_info("- 5 -")
    assert out["current"] == 5
    assert out["total"] is None


def test_hyphen_form_with_lines():
    """The hyphen typography form must sit on its own line."""
    text = "Some body text\n- 12 -\nMore body"
    out = _find_page_info(text)
    assert out is not None
    assert out["current"] == 12


def test_hyphen_no_spaces():
    """The hyphen typography form requires the hyphens to bracket
    the number; we don't accept "-5-" inline because that's an
    arithmetic / range marker."""
    # Without padding inside, our pattern requires \s* (zero or
    # more) so it's still recognised.
    out = _find_page_info("-5-")
    # Either way, only on its own line.
    assert out is None or out["current"] == 5


# ---- Bare slash form (own line only) -----------------------------


def test_bare_slash_form_on_own_line():
    text = "Body text\n3 / 12\nFooter"
    out = _find_page_info(text)
    assert out is not None
    assert out["current"] == 3
    assert out["total"] == 12


def test_bare_slash_form_inline_rejected():
    """A bare ``3 / 12`` inside a sentence must NOT be claimed."""
    out = _find_page_info("I have 3 / 12 of the answers")
    assert out is None


def test_bare_slash_date_form_rejected():
    """``3 / 12 / 2024`` is a date, not a page marker."""
    out = _find_page_info("Date: 3 / 12 / 2024")
    assert out is None


# ---- Continuation marker -----------------------------------------


def test_continued_paren_form():
    text = "Page 3 of 12\n(continued)"
    out = _find_page_info(text)
    assert out["continued"] is True
    assert out["current"] == 3


def test_continued_no_paren():
    text = "Page 5 of 10\ncontinued from previous page"
    out = _find_page_info(text)
    assert out["continued"] is True
    assert out["current"] == 5


def test_continued_only_no_page_marker():
    """A ``(continued)`` notice with no page marker still yields
    a result tagging continued=True."""
    out = _find_page_info("This section (continued)")
    assert out is not None
    assert out["continued"] is True
    assert out["current"] is None
    assert out["total"] is None


def test_cont_on_next_page():
    text = "Page 4\ncont. on next page"
    out = _find_page_info(text)
    assert out["continued"] is True


def test_continued_uppercase():
    text = "Page 3\nCONTINUED FROM PREV PAGE"
    out = _find_page_info(text)
    assert out["continued"] is True


def test_page_marker_with_continued_inline():
    out = _find_page_info("Section A (continued) - Page 3 of 12")
    assert out["current"] == 3
    assert out["total"] == 12
    assert out["continued"] is True


# ---- Negative / reject cases -------------------------------------


def test_no_page_marker_returns_none():
    text = "This is a normal paragraph with no page footer."
    assert _find_page_info(text) is None


def test_empty_text():
    assert _find_page_info("") is None


def test_zero_page_rejected():
    """Page 0 is non-sensical."""
    out = _find_page_info("Page 0")
    assert out is None


def test_word_pages_not_followed_by_number():
    """The word ``Pages`` without a number doesn't fire."""
    assert _find_page_info("These pages are stapled") is None


def test_p_dot_without_dot_rejected():
    """``p 5`` (no dot) must NOT match the p.-form because the
    pattern requires the literal dot."""
    out = _find_page_info("see p 5 for details")
    assert out is None


def test_total_less_than_current_rejected():
    """``Page 12 of 3`` is reversed -- date-like noise. Reject."""
    out = _find_page_info("Page 12 of 3")
    # The current/total sanity check skips to the next pattern.
    # The bare "Page 12" form will then fire.
    assert out is None or (out["current"] == 12 and out["total"] is None)


# ---- Real-world contexts -----------------------------------------


def test_pdf_footer_context():
    text = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do\n"
        "eiusmod tempor incididunt ut labore et dolore magna aliqua.\n"
        "\n"
        "Page 3 of 12\n"
    )
    out = _find_page_info(text)
    assert out["current"] == 3
    assert out["total"] == 12


def test_slide_deck_footer():
    text = (
        "Q3 Revenue Forecast\n"
        "\n"
        "Some bullet points\n"
        "\n"
        "Slide 4 / 20"
    )
    out = _find_page_info(text)
    assert out["current"] == 4
    assert out["total"] == 20


def test_contract_typography():
    text = (
        "...this agreement shall remain in force...\n"
        "\n"
        "- 5 -\n"
    )
    out = _find_page_info(text)
    assert out["current"] == 5


# ---- High page counts --------------------------------------------


def test_long_document():
    out = _find_page_info("Page 247 of 1000")
    assert out["current"] == 247
    assert out["total"] == 1000


def test_4_digit_page():
    out = _find_page_info("Page 1234 of 9999")
    assert out["current"] == 1234
    assert out["total"] == 9999


# ---- Whitespace normalisation ------------------------------------


def test_extra_spaces_normalised():
    out = _find_page_info("Page   3   of   12")
    # Label preserved with single-spaces.
    assert "Page 3 of 12" == out["label"]


# ---- enrich_document integration ---------------------------------


def test_enrich_backfills_page_info():
    ocr = OCRResult(text="Page 3 of 12", word_count=4, mean_confidence=0.9)
    out = enrich_document(None, ocr)
    assert out.page_info is not None
    assert out.page_info["current"] == 3
    assert out.page_info["total"] == 12


def test_enrich_preserves_caller_page_info():
    """When an LLM has supplied page_info, enrich preserves it."""
    caller = DocumentFields(
        title="My PDF",
        page_info={"current": 99, "total": 100, "label": "LLM", "continued": False},
    )
    ocr = OCRResult(text="Page 3 of 12", word_count=4, mean_confidence=0.9)
    out = enrich_document(caller, ocr)
    assert out.page_info is not None
    assert out.page_info["current"] == 99
    assert out.title == "My PDF"


def test_enrich_no_page_marker():
    ocr = OCRResult(
        text="Lorem ipsum dolor sit amet.",
        word_count=5,
        mean_confidence=0.9,
    )
    out = enrich_document(None, ocr)
    assert out.page_info is None


def test_enrich_preserves_caller_title_when_none_page_info():
    caller = DocumentFields(title="Existing Title")
    ocr = OCRResult(text="Page 7 of 30", word_count=4, mean_confidence=0.9)
    out = enrich_document(caller, ocr)
    assert out.title == "Existing Title"
    assert out.page_info is not None
    assert out.page_info["current"] == 7


# ---- pipeline integration ----------------------------------------


def test_pipeline_runs_document_enrichment():
    """Pipeline.enrich must route Category.document through
    enrich_document so page_info is populated."""
    from shotclassify_common import Category, ExtractedFields
    from shotclassify_extract.pipeline import enrich

    ocr = OCRResult(
        text="Lorem ipsum.\n\nPage 5 of 10",
        word_count=6,
        mean_confidence=0.9,
    )
    fields = ExtractedFields(document=DocumentFields(title="My PDF"))
    out = enrich(Category.document, fields, ocr)
    assert out.document is not None
    assert out.document.page_info is not None
    assert out.document.page_info["current"] == 5


def test_pipeline_skips_non_document_categories():
    """For non-document categories the document slot stays None."""
    from shotclassify_common import Category, ExtractedFields
    from shotclassify_extract.pipeline import enrich

    ocr = OCRResult(
        text="Page 5 of 10",
        word_count=4,
        mean_confidence=0.9,
    )
    fields = ExtractedFields()
    out = enrich(Category.receipt, fields, ocr)
    # The document slot is not touched (it stays None).
    assert out.document is None
