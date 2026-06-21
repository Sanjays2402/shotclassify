"""Tests for the cross-category phone-number extractor.

Phone numbers found in OCR text are stashed under
``ExtractedFields.raw["phones"]`` by the enrich pipeline so dashboards
and routing rules have a single place to look regardless of which
category the screenshot belongs to.

The matcher accepts:

* **E.164** (``+`` prefix, 8..15 digits) -- universal international
  form.
* **NANP-formatted** (``(NXX) NXX-XXXX`` / ``NXX-NXX-XXXX`` /
  ``NXX.NXX.XXXX`` / ``NXX NXX XXXX``) with NANP-valid leading
  digits (area code and exchange both start ``2..9``).
* **Keyword-prefixed bare NANP** (``Phone: 4155551234``, ``Tel
  4155551234``, ``Mobile 4155551234``, ``Fax 4155551234``).

Output is canonical digits-only (``+`` preserved for E.164) so the
same number printed in different formats collapses to one entry.
"""
from __future__ import annotations

import pytest
from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_phones

# ---- extract_phones: E.164 ---------------------------------------------


def test_extract_e164_us():
    assert extract_phones("call +14155551234 now") == ["+14155551234"]


def test_extract_e164_uk():
    assert extract_phones("ring +442071234567 today") == ["+442071234567"]


def test_extract_e164_with_separators():
    """E.164 can carry separators between digit groups. The canonical
    output collapses them to digits-only."""
    assert extract_phones("dial +1 (415) 555-1234 please") == ["+14155551234"]


def test_extract_e164_with_dashes():
    assert extract_phones("contact +91-98765-43210") == ["+919876543210"]


def test_e164_rejects_too_short():
    """ITU E.164 bounds the digit length to 8..15. ``+1234`` is too
    short to be a real number."""
    assert extract_phones("ref +1234") == []


def test_e164_rejects_too_long():
    """16-digit ``+`` numbers are not E.164."""
    text = "id +12345678901234567 here"
    assert extract_phones(text) == []


# ---- extract_phones: NANP-formatted ------------------------------------


@pytest.mark.parametrize(
    "snippet,expected",
    [
        ("(415) 555-1234", "4155551234"),
        ("415-555-1234", "4155551234"),
        ("415.555.1234", "4155551234"),
        ("415 555 1234", "4155551234"),
        ("(212) 867-5309", "2128675309"),
    ],
)
def test_extract_nanp_formatted(snippet, expected):
    assert extract_phones(f"call us at {snippet} today") == [expected]


def test_nanp_rejects_invalid_area_code():
    """NANP area codes never start with 0 or 1. ``(123) ...`` would
    look phone-shaped but cannot be a real area code."""
    assert extract_phones("ref 123-456-7890 in log") == []


def test_nanp_rejects_invalid_exchange():
    """NANP exchange (middle three) also cannot start with 0 or 1."""
    assert extract_phones("ref 415-055-1234 in log") == []


def test_nanp_rejects_mixed_separators():
    """``123.456-7890`` mixes a dot with a dash; reject to keep
    formatted-number recall tight."""
    assert extract_phones("ref 415.555-1234 in log") == []


# ---- extract_phones: keyword-prefixed bare -----------------------------


@pytest.mark.parametrize(
    "snippet,expected",
    [
        ("Phone: 4155551234", "4155551234"),
        ("Tel 4155551234", "4155551234"),
        ("Telephone 4155551234", "4155551234"),
        ("Mobile: 4155551234", "4155551234"),
        ("Cell 4155551234", "4155551234"),
        ("Fax 4155551234", "4155551234"),
        ("PHONE 4155551234", "4155551234"),  # keyword is case-insensitive
    ],
)
def test_extract_keyword_prefixed(snippet, expected):
    assert extract_phones(f"vendor footer:\n{snippet}\n") == [expected]


def test_bare_10_digit_run_rejected_without_keyword():
    """A bare 10-digit run is too easy to false-positive on account
    numbers and IDs. Require a phone-class keyword to extract."""
    assert extract_phones("order 4155551234 shipped") == []


def test_keyword_prefixed_rejects_invalid_nanp():
    """Even with a phone keyword, the digits must be NANP-valid."""
    assert extract_phones("Phone: 1234567890") == []


# ---- extract_phones: de-dup and order ----------------------------------


def test_dedups_same_number_in_two_formats():
    """``(415) 555-1234`` and ``415-555-1234`` are the same phone;
    keep only the first-seen form (canonical digits-only)."""
    text = "main (415) 555-1234, alt 415-555-1234"
    assert extract_phones(text) == ["4155551234"]


def test_dedups_e164_and_bare_nanp():
    """``+14155551234`` and the bare ``(415) 555-1234`` refer to the
    same number; the E.164 form wins and the NANP duplicate is
    suppressed."""
    text = "intl: +1 (415) 555-1234\nlocal: (415) 555-1234"
    assert extract_phones(text) == ["+14155551234"]


def test_preserves_first_seen_order():
    text = (
        "primary: (415) 555-1234\n"
        "support: (212) 867-5309\n"
        "fax:     (415) 555-9999\n"
    )
    assert extract_phones(text) == [
        "4155551234",
        "2128675309",
        "4155559999",
    ]


def test_empty_input_returns_empty_list():
    assert extract_phones("") == []
    assert extract_phones("nothing here") == []
    assert extract_phones(None) == []  # type: ignore[arg-type]


def test_cap_at_50_phones():
    text = "\n".join(
        f"Phone: {410 + (i // 1000):03d}-555-{i % 10000:04d}" for i in range(120)
    )
    out = extract_phones(text)
    assert len(out) <= 50


# ---- extract_phones: real-world mixed text -----------------------------


def test_receipt_footer_with_phone_and_fax():
    text = (
        "ACME Cafe\n"
        "123 Market St\n"
        "Phone: (415) 555-1234\n"
        "Fax: (415) 555-9999\n"
        "Subtotal 10.00\nTotal 10.00\n"
    )
    assert extract_phones(text) == [
        "4155551234",
        "4155559999",
    ]


def test_chat_contact_card_with_e164():
    text = (
        "Alice (Mobile)\n"
        "+1 415 555 1234\n"
        "alice@example.com\n"
    )
    assert extract_phones(text) == ["+14155551234"]


# ---- pipeline integration ----------------------------------------------


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
def test_enrich_populates_raw_phones_for_every_category(category):
    ocr = OCRResult(
        text="contact us at +1 (415) 555-1234 or fax (212) 867-5309",
        word_count=10,
    )
    out = enrich(category, ExtractedFields(), ocr)
    assert out.raw.get("phones") == [
        "+14155551234",
        "2128675309",
    ]


def test_enrich_omits_raw_phones_when_text_has_none():
    ocr = OCRResult(text="just prose no phones here", word_count=5)
    out = enrich(Category.code_snippet, ExtractedFields(), ocr)
    assert "phones" not in out.raw


def test_enrich_preserves_existing_raw_keys_alongside_phones():
    ocr = OCRResult(text="dial +1 (415) 555-1234 to escalate", word_count=6)
    fields = ExtractedFields(raw={"trace_id": "abc123"})
    out = enrich(Category.error_stacktrace, fields, ocr)
    assert out.raw["trace_id"] == "abc123"
    assert out.raw["phones"] == ["+14155551234"]


def test_enrich_phones_coexist_with_urls_paths_emails():
    """A real OCR pass with all four cross-category signals."""
    ocr = OCRResult(
        text=(
            "docs at https://example.com/help "
            "logs at /var/log/app.log "
            "page oncall@acme.io "
            "or phone (415) 555-1234"
        ),
        word_count=14,
    )
    out = enrich(Category.error_stacktrace, ExtractedFields(), ocr)
    assert out.raw["urls"] == ["https://example.com/help"]
    assert out.raw["paths"] == ["/var/log/app.log"]
    assert out.raw["emails"] == ["oncall@acme.io"]
    assert out.raw["phones"] == ["4155551234"]
