"""Tests for the cross-category URL extractor.

URLs found in OCR text are stashed under ``ExtractedFields.raw["urls"]``
by the enrich pipeline so dashboards and routing rules have a single
place to look regardless of which category the screenshot belongs to.

The matcher accepts ``http(s)://`` only, trims trailing sentence
punctuation, de-dupes while preserving first-seen order, and caps
the result at 50 entries to bound storage growth.
"""
from __future__ import annotations

import pytest
from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_urls


def test_extract_basic_https():
    urls = extract_urls("see https://example.com for more")
    assert urls == ["https://example.com"]


def test_extract_basic_http():
    urls = extract_urls("legacy http://internal.example.com/path")
    assert urls == ["http://internal.example.com/path"]


def test_extract_multiple_unique_order_preserved():
    text = (
        "first https://a.example.com\n"
        "then https://b.example.com\n"
        "and again https://a.example.com (dup)\n"
    )
    assert extract_urls(text) == [
        "https://a.example.com",
        "https://b.example.com",
    ]


def test_trims_trailing_punctuation():
    cases = [
        ("see https://example.com.", "https://example.com"),
        ("see https://example.com,", "https://example.com"),
        ("(see https://example.com)", "https://example.com"),
        ("[ref https://example.com]", "https://example.com"),
        ("see https://example.com?", "https://example.com"),
        ('"https://example.com"', "https://example.com"),
    ]
    for text, expected in cases:
        assert extract_urls(text) == [expected], f"failed: {text!r}"


def test_preserves_query_and_fragment():
    text = "docs at https://example.com/path?q=hi&n=2#frag now"
    assert extract_urls(text) == [
        "https://example.com/path?q=hi&n=2#frag"
    ]


def test_no_urls_returns_empty_list():
    assert extract_urls("nothing here") == []
    assert extract_urls("") == []
    assert extract_urls(None) == []  # type: ignore[arg-type]


def test_does_not_match_bare_domain():
    """We intentionally require a scheme to keep false positives down."""
    assert extract_urls("visit example.com today") == []
    assert extract_urls("www.example.com") == []


def test_ftp_not_matched():
    """Other schemes are out of scope; keep the matcher tight."""
    assert extract_urls("ftp://files.example.com") == []


def test_url_inside_markdown_link():
    text = "see [docs](https://docs.example.com/intro) for setup"
    assert extract_urls(text) == ["https://docs.example.com/intro"]


def test_cap_at_50_urls():
    text = "\n".join(f"line https://host{i}.example.com" for i in range(120))
    urls = extract_urls(text)
    assert len(urls) == 50
    assert urls[0] == "https://host0.example.com"
    assert urls[-1] == "https://host49.example.com"


# --- pipeline integration ---------------------------------------------------


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
def test_enrich_populates_raw_urls_for_every_category(category):
    ocr = OCRResult(
        text="docs https://example.com/help and https://api.example.com",
        word_count=4,
    )
    out = enrich(category, ExtractedFields(), ocr)
    assert out.raw.get("urls") == [
        "https://example.com/help",
        "https://api.example.com",
    ]


def test_enrich_omits_raw_urls_when_text_has_none():
    """No empty list left lying around when there's nothing to record."""
    ocr = OCRResult(text="just words, no links", word_count=4)
    out = enrich(Category.code_snippet, ExtractedFields(), ocr)
    assert "urls" not in out.raw


def test_enrich_preserves_existing_raw_keys():
    """Adding ``urls`` must not clobber other keys a caller stashed in raw."""
    ocr = OCRResult(text="see https://example.com", word_count=2)
    fields = ExtractedFields(raw={"trace_id": "abc123"})
    out = enrich(Category.chat_screenshot, fields, ocr)
    assert out.raw["trace_id"] == "abc123"
    assert out.raw["urls"] == ["https://example.com"]
