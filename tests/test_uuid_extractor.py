"""Tests for the cross-category UUID extractor.

UUIDs found in OCR text are stashed under
``ExtractedFields.raw["uuids"]`` by the enrich pipeline so dashboards
and routing rules have a single place to look regardless of which
category the screenshot belongs to.

The matcher accepts:

* **Dashed** RFC 4122 form (8-4-4-4-12 hex with hyphens) for v1..v5.
* **Compact** 32-hex form (same version-nibble enforcement at
  position 12).

Output is canonical lowercase + hyphenated regardless of input
shape, so the same UUID in different formats collapses to one
entry. The "nil" UUID (all zeros) is rejected as a placeholder.
"""
from __future__ import annotations

import pytest
from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_uuids

# ---- extract_uuids: dashed form ----------------------------------------


def test_extract_basic_v4_dashed():
    text = "trace 550e8400-e29b-41d4-a716-446655440000 today"
    assert extract_uuids(text) == ["550e8400-e29b-41d4-a716-446655440000"]


def test_extract_v1():
    """v1 (time-based) UUIDs are also accepted."""
    text = "id c232ab00-9414-11ec-b3c8-9e6bdeced846 here"
    assert extract_uuids(text) == ["c232ab00-9414-11ec-b3c8-9e6bdeced846"]


@pytest.mark.parametrize("version", ["1", "2", "3", "4", "5"])
def test_all_versions_accepted(version):
    uuid = f"550e8400-e29b-{version}1d4-a716-446655440000"
    assert extract_uuids(uuid) == [uuid]


def test_uppercase_normalised_to_lowercase():
    """RFC 4122 says case-insensitive; we canonicalise to lowercase."""
    text = "id 550E8400-E29B-41D4-A716-446655440000 here"
    assert extract_uuids(text) == ["550e8400-e29b-41d4-a716-446655440000"]


def test_extract_multiple_preserves_first_seen_order():
    text = (
        "trace_id: 550e8400-e29b-41d4-a716-446655440000\n"
        "span_id:  6ba7b810-9dad-11d1-80b4-00c04fd430c8\n"
        "user_id:  6ba7b811-9dad-11d1-80b4-00c04fd430c8\n"
    )
    assert extract_uuids(text) == [
        "550e8400-e29b-41d4-a716-446655440000",
        "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        "6ba7b811-9dad-11d1-80b4-00c04fd430c8",
    ]


# ---- extract_uuids: compact form ---------------------------------------


def test_extract_compact_form():
    text = "id 550e8400e29b41d4a716446655440000 today"
    assert extract_uuids(text) == ["550e8400-e29b-41d4-a716-446655440000"]


def test_compact_uppercase_normalised():
    text = "id 550E8400E29B41D4A716446655440000 today"
    assert extract_uuids(text) == ["550e8400-e29b-41d4-a716-446655440000"]


def test_dashed_and_compact_collapse_to_one_entry():
    """Same underlying UUID in two formats -> single canonical entry."""
    text = (
        "compact: 550e8400e29b41d4a716446655440000\n"
        "dashed:  550e8400-e29b-41d4-a716-446655440000\n"
    )
    assert extract_uuids(text) == ["550e8400-e29b-41d4-a716-446655440000"]


# ---- extract_uuids: rejection rules ------------------------------------


def test_nil_uuid_rejected():
    """All-zero UUID is a placeholder; rejected."""
    text = "default 00000000-0000-0000-0000-000000000000 set"
    assert extract_uuids(text) == []


def test_invalid_version_nibble_rejected_dashed():
    """v0 / v6+ are not real UUID versions for our schemes."""
    cases = [
        "abcdef01-2345-0123-89ab-cdef01234567",  # version 0
        "abcdef01-2345-6123-89ab-cdef01234567",  # version 6 (not allowed)
        "abcdef01-2345-7123-89ab-cdef01234567",  # version 7
        "abcdef01-2345-8123-89ab-cdef01234567",  # version 8
    ]
    for u in cases:
        assert extract_uuids(f"id {u} here") == [], f"failed: {u!r}"


def test_invalid_version_nibble_rejected_compact():
    cases = [
        "abcdef0123456023456789abcdef01234567",  # too long (36)
        "abcdef0123450123456789abcdef0123",  # 32 chars, version 0
        "abcdef0123456123456789abcdef0123",  # 32 chars, version 6
    ]
    for u in cases:
        # Wrap with non-hex boundaries to mirror real OCR context.
        assert extract_uuids(f" {u} ") == [], f"failed: {u!r}"


def test_too_short_rejected():
    assert extract_uuids("id 550e8400-e29b-41d4 here") == []


def test_too_long_dashed_rejected():
    """A 13-char tail group would fail the regex 12-hex enforcement."""
    text = "id 550e8400-e29b-41d4-a716-4466554400000 here"
    assert extract_uuids(text) == []


def test_sha_hash_not_treated_as_uuid():
    """A 40-char SHA-1 hash starts with hex but is too long; the
    compact UUID regex's non-hex boundary rejects it."""
    sha = "a" * 40
    assert extract_uuids(f"hash {sha} here") == []
    sha256 = "b" * 64
    assert extract_uuids(f"hash {sha256} here") == []


def test_empty_input_returns_empty():
    assert extract_uuids("") == []
    assert extract_uuids("no uuids here") == []
    assert extract_uuids(None) == []  # type: ignore[arg-type]


def test_cap_at_50_uuids():
    uuids = [
        f"550e8400-e29b-41d4-a716-{i:012x}" for i in range(120)
    ]
    text = "\n".join(uuids)
    out = extract_uuids(text)
    assert len(out) == 50
    assert out[0] == uuids[0]
    assert out[-1] == uuids[49]


# ---- extract_uuids: real-world contexts --------------------------------


def test_error_log_correlation_id():
    text = (
        "ERROR 2026-06-20T12:00Z\n"
        "correlation_id=550e8400-e29b-41d4-a716-446655440000\n"
        "traceback follows\n"
    )
    assert extract_uuids(text) == ["550e8400-e29b-41d4-a716-446655440000"]


def test_uuid_inside_url_path_still_extracted():
    """A URL like ``/users/{uuid}`` is a perfectly valid place for
    a UUID; we surface it even though the URL extractor already
    captures the full URL."""
    text = "GET /users/550e8400-e29b-41d4-a716-446655440000/edit 200"
    assert extract_uuids(text) == ["550e8400-e29b-41d4-a716-446655440000"]


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
def test_enrich_populates_raw_uuids_for_every_category(category):
    ocr = OCRResult(
        text="trace 550e8400-e29b-41d4-a716-446655440000 and 6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        word_count=4,
    )
    out = enrich(category, ExtractedFields(), ocr)
    assert out.raw.get("uuids") == [
        "550e8400-e29b-41d4-a716-446655440000",
        "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
    ]


def test_enrich_omits_raw_uuids_when_text_has_none():
    ocr = OCRResult(text="just words no identifiers", word_count=4)
    out = enrich(Category.code_snippet, ExtractedFields(), ocr)
    assert "uuids" not in out.raw


def test_enrich_preserves_existing_raw_keys_alongside_uuids():
    ocr = OCRResult(
        text="see 550e8400-e29b-41d4-a716-446655440000 today",
        word_count=4,
    )
    fields = ExtractedFields(raw={"trace_id": "abc123"})
    out = enrich(Category.error_stacktrace, fields, ocr)
    assert out.raw["trace_id"] == "abc123"
    assert out.raw["uuids"] == ["550e8400-e29b-41d4-a716-446655440000"]


def test_enrich_uuids_coexist_with_other_cross_category_signals():
    """A real OCR pass with URL, path, email, phone, AND uuid."""
    ocr = OCRResult(
        text=(
            "docs at https://example.com/help "
            "logs at /var/log/app.log "
            "page oncall@acme.io "
            "phone (415) 555-1234 "
            "trace 550e8400-e29b-41d4-a716-446655440000"
        ),
        word_count=14,
    )
    out = enrich(Category.error_stacktrace, ExtractedFields(), ocr)
    assert out.raw["urls"] == ["https://example.com/help"]
    assert out.raw["paths"] == ["/var/log/app.log"]
    assert out.raw["emails"] == ["oncall@acme.io"]
    assert out.raw["phones"] == ["4155551234"]
    assert out.raw["uuids"] == ["550e8400-e29b-41d4-a716-446655440000"]
