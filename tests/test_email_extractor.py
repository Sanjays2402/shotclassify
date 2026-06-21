"""Tests for the cross-category email-address extractor.

Email addresses found in OCR text are stashed under
``ExtractedFields.raw["emails"]`` by the enrich pipeline so dashboards
and routing rules have a single place to look regardless of which
category the screenshot belongs to.

The matcher accepts conservative ``local@domain.tld`` shapes only,
lowercases the result for storage (so ``Alice@Example.COM`` and
``alice@example.com`` collapse to one entry), strips a leading
``mailto:`` prefix, trims trailing sentence punctuation, de-dupes
while preserving first-seen order, and caps the result at 50 entries
to bound storage growth.
"""
from __future__ import annotations

import pytest
from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_emails

# ---- extract_emails: basic shapes --------------------------------------


def test_extract_basic():
    assert extract_emails("contact alice@example.com today") == [
        "alice@example.com"
    ]


def test_extract_with_plus_tag():
    assert extract_emails("hit ops+alerts@example.com") == [
        "ops+alerts@example.com"
    ]


def test_extract_with_dots_and_hyphens():
    """Common real-world local parts: dotted names, hyphenated domains."""
    assert extract_emails("mail to a.b.c@sub-domain.example.com") == [
        "a.b.c@sub-domain.example.com"
    ]


def test_lowercase_normalisation():
    """``Alice@Example.COM`` collapses to ``alice@example.com``."""
    assert extract_emails("write Alice@Example.COM") == [
        "alice@example.com"
    ]


def test_mailto_prefix_stripped():
    assert extract_emails("mailto:alice@example.com") == [
        "alice@example.com"
    ]


def test_extract_multiple_preserves_first_seen_order():
    text = (
        "from: alice@example.com\n"
        "cc: bob@example.com\n"
        "again alice@example.com\n"
    )
    assert extract_emails(text) == [
        "alice@example.com",
        "bob@example.com",
    ]


# ---- extract_emails: rejection / boundary cases ------------------------


def test_does_not_match_mention():
    """A bare ``@user`` mention has no domain TLD; reject it."""
    assert extract_emails("ping @alice for review") == []


def test_does_not_match_ssh_user_at_host():
    """``user@host`` without a dotted TLD is NOT an email."""
    assert extract_emails("ssh root@server01 now") == []


def test_does_not_match_numeric_only_tld():
    """``user@host.42`` looks like an email but has a digit TLD; reject."""
    assert extract_emails("config: user@host.42 line") == []


def test_does_not_match_leading_dot_local():
    """RFC says local can't start with a dot; we enforce it."""
    assert extract_emails("see .foo@example.com") == []


def test_trims_trailing_punctuation_email():
    """A trailing ``.`` / ``,`` / ``)`` is sentence punctuation, not part
    of the email. The regex's lookahead rejects trailing word chars
    but a quote/paren can still appear and must be trimmed."""
    cases = [
        ("contact alice@example.com.", "alice@example.com"),
        ("contact alice@example.com,", "alice@example.com"),
        ("(see alice@example.com)", "alice@example.com"),
        ("[ref alice@example.com]", "alice@example.com"),
        ('"alice@example.com"', "alice@example.com"),
    ]
    for text, expected in cases:
        assert extract_emails(text) == [expected], f"failed: {text!r}"


def test_no_emails_returns_empty_list():
    assert extract_emails("nothing here") == []
    assert extract_emails("") == []
    assert extract_emails(None) == []  # type: ignore[arg-type]


def test_real_world_mixed_text():
    """A realistic error log mentioning the on-call email."""
    text = (
        "ERROR: backup failed at 2026-06-20T10:00Z\n"
        "page oncall: oncall+backups@acme.io and cc reports@acme.io\n"
    )
    assert extract_emails(text) == [
        "oncall+backups@acme.io",
        "reports@acme.io",
    ]


def test_cap_at_50_emails():
    text = "\n".join(f"user{i}@example.com" for i in range(120))
    out = extract_emails(text)
    assert len(out) == 50
    assert out[0] == "user0@example.com"
    assert out[-1] == "user49@example.com"


# ---- extract_emails: pipeline integration ------------------------------


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
def test_enrich_populates_raw_emails_for_every_category(category):
    ocr = OCRResult(
        text="contact alice@example.com or ops@example.com",
        word_count=5,
    )
    out = enrich(category, ExtractedFields(), ocr)
    assert out.raw.get("emails") == [
        "alice@example.com",
        "ops@example.com",
    ]


def test_enrich_omits_raw_emails_when_text_has_none():
    ocr = OCRResult(text="just words no addresses", word_count=4)
    out = enrich(Category.code_snippet, ExtractedFields(), ocr)
    assert "emails" not in out.raw


def test_enrich_preserves_existing_raw_keys_alongside_emails():
    ocr = OCRResult(text="reply to ops@acme.io please", word_count=4)
    fields = ExtractedFields(raw={"trace_id": "abc123"})
    out = enrich(Category.error_stacktrace, fields, ocr)
    assert out.raw["trace_id"] == "abc123"
    assert out.raw["emails"] == ["ops@acme.io"]


def test_enrich_urls_paths_network_emails_coexist_cleanly():
    """A real OCR pass with all four cross-category signals."""
    ocr = OCRResult(
        text=(
            "docs at https://example.com/help "
            "logs at /var/log/app.log "
            "upstream redis.cache:6379 down "
            "page oncall@acme.io"
        ),
        word_count=14,
    )
    out = enrich(Category.error_stacktrace, ExtractedFields(), ocr)
    assert out.raw["urls"] == ["https://example.com/help"]
    assert out.raw["paths"] == ["/var/log/app.log"]
    assert "redis.cache:6379" in out.raw["network"]
    assert out.raw["emails"] == ["oncall@acme.io"]


def test_email_inside_url_query_string_still_captured():
    """A URL like ``...?email=alice@example.com`` legitimately
    contains an email; we extract it because it IS a valid contact
    even though it also appears in raw[\"urls\"]. Dashboards can
    de-dupe on URL vs email context."""
    text = "click https://api.example.com/sub?email=alice@example.com to opt in"
    emails = extract_emails(text)
    assert "alice@example.com" in emails
