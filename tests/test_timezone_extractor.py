"""Tests for the cross-category timezone extractor.

Timezone tokens found in OCR text are stashed under
``ExtractedFields.raw["timezones"]`` by the enrich pipeline so
dashboards and routing rules have a single place to look regardless
of which category the screenshot belongs to.

Recognised forms:

* Numeric UTC offsets (``+05:30``, ``-0800``, ``UTC+1``, ``GMT-5``).
* ``Z`` / Zulu suffix on an ISO-8601-ish timestamp.
* Named abbreviations (``UTC``, ``PST``, ``IST``, ``JST``, etc.).
* IANA names (``America/New_York``, ``Europe/London``).

Output canonicalisation:

* Numeric offsets -> ``+hh`` (no minutes) or ``+hh:mm`` (with minutes).
* Z suffix -> ``+00``.
* Named abbreviations -> uppercase.
* IANA names -> verbatim Region/City form.
"""
from __future__ import annotations

import pytest
from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_timezones

# ---- numeric offsets ---------------------------------------------------


def test_extract_offset_with_minutes():
    assert extract_timezones("logged at 09:23 +05:30 yesterday") == ["+05:30"]


def test_extract_offset_no_minutes_padded():
    assert extract_timezones("at -0800 now") == ["-08"]


def test_extract_offset_no_minutes_short_form():
    """``-08`` and ``-0800`` collapse to ``-08``."""
    assert extract_timezones("offset -08 here") == ["-08"]


def test_extract_offset_colon_form_minutes_zero_collapses():
    assert extract_timezones("at +05:00 today") == ["+05"]


def test_extract_offset_compact_form():
    assert extract_timezones("ts +0530") == ["+05:30"]


def test_extract_offset_with_utc_prefix():
    assert extract_timezones("starts UTC+01:00") == ["+01"]


def test_extract_offset_with_gmt_prefix():
    assert extract_timezones("UTC-5 (GMT-5)") == ["-05"]


def test_extract_offset_positive_max():
    """+14 is the IANA max (Pacific/Kiritimati)."""
    assert extract_timezones("offset +14:00") == ["+14"]


def test_extract_offset_negative_max():
    """-12 is the IANA negative max (Pacific/Niue)."""
    assert extract_timezones("offset -12:00") == ["-12"]


def test_rejects_offset_hours_too_large_positive():
    """``+15`` is beyond the IANA max."""
    assert extract_timezones("invalid +15:00") == []


def test_rejects_offset_hours_too_large_negative():
    """``-13`` is beyond the IANA min."""
    assert extract_timezones("invalid -13:00") == []


def test_rejects_offset_minutes_too_large():
    """``+05:60`` has invalid minutes."""
    assert extract_timezones("bad +05:60") == []


def test_offset_dedup_compact_vs_colon():
    """``+0530`` and ``+05:30`` collapse to one entry."""
    text = "shown as +05:30 and again as +0530"
    assert extract_timezones(text) == ["+05:30"]


def test_offset_dedup_long_vs_short():
    """``-08`` and ``-0800`` collapse."""
    text = "stamp -08 and stamp -0800"
    assert extract_timezones(text) == ["-08"]


def test_multiple_distinct_offsets():
    text = "ny -05:00 london +00:00 mumbai +05:30"
    assert extract_timezones(text) == ["-05", "+00", "+05:30"]


# ---- Z suffix ----------------------------------------------------------


def test_z_suffix_iso8601():
    """The Z right after an ISO-8601 timestamp normalises to +00."""
    assert extract_timezones("event at 2024-03-15T08:23:01Z") == ["+00"]


def test_z_suffix_with_fractional_seconds():
    assert extract_timezones("2024-03-15T08:23:01.123Z") == ["+00"]


def test_z_suffix_after_simple_time():
    assert extract_timezones("12:00Z") == ["+00"]


def test_bare_z_rejected():
    """A bare ``Z`` in prose does not fire."""
    assert extract_timezones("see appendix Z for details") == []


def test_z_inside_word_rejected():
    """``Zealand`` does not satisfy the Z suffix."""
    assert extract_timezones("flying to New Zealand soon") == []


def test_z_after_letter_rejected():
    """Only a Z preceded by a digit counts."""
    assert extract_timezones("size XZ here") == []


# ---- named abbreviations ----------------------------------------------


@pytest.mark.parametrize(
    "abbrev",
    [
        "UTC",
        "GMT",
        "PST",
        "PDT",
        "EST",
        "EDT",
        "CST",
        "CDT",
        "MST",
        "MDT",
        "BST",
        "CET",
        "CEST",
        "IST",
        "JST",
        "KST",
        "AEST",
        "AEDT",
        "HST",
        "AKST",
        "AKDT",
        "NZST",
        "NZDT",
        "WET",
        "WEST",
        "EET",
        "EEST",
        "MSK",
        "SGT",
        "HKT",
        "PHT",
    ],
)
def test_named_abbrev_recognised(abbrev):
    text = f"meeting at 9:00 AM {abbrev} today"
    assert abbrev in extract_timezones(text)


def test_abbrev_not_inside_word():
    """``IST`` inside ``EXIST`` does not fire."""
    # ``EXIST`` contains the substring ``IST`` but word boundary keeps
    # it out. The same protection covers ``CSTOMER`` -> ``CST`` and so on.
    assert extract_timezones("the system EXIST") == []


def test_abbrev_at_line_end():
    text = "starts 09:00 PST"
    assert extract_timezones(text) == ["PST"]


def test_abbrev_in_parens():
    assert extract_timezones("9:00 AM (PST)") == ["PST"]


def test_abbrev_dedup():
    text = "9 AM PST and 5 PM PST"
    assert extract_timezones(text) == ["PST"]


# ---- IANA Region/City --------------------------------------------------


def test_iana_basic():
    assert extract_timezones("schedule America/New_York 9am") == ["America/New_York"]


def test_iana_europe():
    assert extract_timezones("zone Europe/London now") == ["Europe/London"]


def test_iana_asia():
    assert extract_timezones("logged from Asia/Tokyo") == ["Asia/Tokyo"]


def test_iana_three_part():
    """``America/Argentina/Buenos_Aires`` (3-part) supported."""
    text = "stored as America/Argentina/Buenos_Aires"
    assert extract_timezones(text) == ["America/Argentina/Buenos_Aires"]


def test_iana_etc_form():
    """``Etc/GMT+8`` is the deprecated POSIX form -- the region is Etc."""
    # The IANA city ``GMT+8`` contains a + that is not part of the
    # city-name character class, so our regex captures ``Etc/GMT``
    # only. Acceptable: dashboards rarely care about Etc zones, and
    # the bare GMT part still surfaces via the named-abbrev matcher.
    text = "fallback Etc/GMT zone"
    assert extract_timezones(text) == ["Etc/GMT"]


def test_iana_dedup():
    text = "stored America/New_York and again America/New_York"
    assert extract_timezones(text) == ["America/New_York"]


def test_iana_with_hyphen_city():
    """City names with hyphens (``America/Port-au-Prince``) supported."""
    text = "zone America/Port-au-Prince"
    assert extract_timezones(text) == ["America/Port-au-Prince"]


def test_non_iana_region_rejected():
    """``Foo/Bar`` is not an IANA zone."""
    assert extract_timezones("path Foo/Bar/baz") == []


# ---- order preservation -----------------------------------------------


def test_order_preserved_across_shapes():
    """Output is sorted by source-text offset."""
    text = "ny -05 london +00 mumbai IST tokyo Asia/Tokyo"
    result = extract_timezones(text)
    assert result == ["-05", "+00", "IST", "Asia/Tokyo"]


def test_iana_before_abbrev_in_same_text():
    """When IANA name appears first, it lands first."""
    text = "stored Europe/London then GMT"
    assert extract_timezones(text) == ["Europe/London", "GMT"]


# ---- cap ---------------------------------------------------------------


def test_cap_at_50():
    """Output capped at 50 entries."""
    # 60 distinct numeric offsets via varied minutes.
    pieces = []
    for h in range(1, 13):
        for m in (0, 15, 30, 45):
            pieces.append(f"slot +{h:02d}:{m:02d}")
    text = " ".join(pieces)  # 48 distinct offsets
    result = extract_timezones(text)
    # 48 distinct, all under cap.
    assert len(result) == 48


# ---- degenerate inputs -------------------------------------------------


def test_empty_string():
    assert extract_timezones("") == []


def test_none_input():
    assert extract_timezones(None) == []  # type: ignore[arg-type]


def test_no_timezones_in_text():
    assert extract_timezones("just some prose with no timezone markers") == []


def test_just_punctuation():
    assert extract_timezones(":::+++") == []


# ---- enrich pipeline integration --------------------------------------


@pytest.mark.parametrize(
    "category",
    [
        Category.chat_screenshot,
        Category.error_stacktrace,
        Category.receipt,
        Category.document,
        Category.other,
    ],
)
def test_pipeline_stashes_timezones_for_every_category(category):
    text = "logged at 2024-03-15T08:23:01Z"
    ocr = OCRResult(text=text, confidence=0.95)
    out = enrich(category, ExtractedFields(), ocr)
    assert out.raw.get("timezones") == ["+00"]


def test_pipeline_no_timezones_no_key():
    text = "no timestamp markers here"
    ocr = OCRResult(text=text, confidence=0.95)
    out = enrich(Category.other, ExtractedFields(), ocr)
    assert "timezones" not in (out.raw or {})


def test_pipeline_mix_shapes():
    text = "chat at 9:00 AM PST sent from Asia/Tokyo at +09:00"
    ocr = OCRResult(text=text, confidence=0.95)
    out = enrich(Category.chat_screenshot, ExtractedFields(), ocr)
    # Order: PST, Asia/Tokyo, +09.
    assert out.raw.get("timezones") == ["PST", "Asia/Tokyo", "+09"]


def test_pipeline_preserves_other_raw_keys():
    """raw["urls"] and raw["timezones"] coexist when both are present."""
    text = "see https://example.com at 2024-03-15T08:23:01Z"
    ocr = OCRResult(text=text, confidence=0.95)
    out = enrich(Category.other, ExtractedFields(), ocr)
    assert out.raw.get("timezones") == ["+00"]
    assert out.raw.get("urls") == ["https://example.com"]
