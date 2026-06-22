"""Cross-category error-fingerprint extractor.

The new ``raw["error_fingerprints"]`` slot captures Sentry event
IDs, Datadog trace_id / span_id pairs, Rollbar / New Relic /
Bugsnag / Honeybadger / Airbrake event IDs found in OCR text.
Each entry is a ``{"vendor", "kind", "id"}`` dict.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_error_fingerprints

# ---- Sentry: full 32-hex event ID ------------------------------


def test_sentry_full_event_id_with_label():
    out = extract_error_fingerprints("Event ID: deadbeef12345678deadbeef12345678")
    assert out == [{"vendor": "sentry", "kind": "event_id", "id": "deadbeef12345678deadbeef12345678"}]


def test_sentry_full_event_id_with_sentry_prefix():
    out = extract_error_fingerprints(
        "Sentry Event ID: a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
    )
    assert out == [
        {"vendor": "sentry", "kind": "event_id", "id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"}
    ]


def test_sentry_full_event_id_lowercased():
    """Mixed-case hex is normalised to lowercase for stable dedupe."""
    out = extract_error_fingerprints(
        "Event ID: ABCDEF1234567890ABCDEF1234567890"
    )
    assert out == [
        {"vendor": "sentry", "kind": "event_id", "id": "abcdef1234567890abcdef1234567890"}
    ]


def test_sentry_full_event_id_underscore_label():
    """``event_id:`` underscore form is supported."""
    out = extract_error_fingerprints("event_id: deadbeefcafebabe1234567890abcdef")
    assert out == [
        {"vendor": "sentry", "kind": "event_id", "id": "deadbeefcafebabe1234567890abcdef"}
    ]


# ---- Sentry: short bracketed ID --------------------------------


def test_sentry_short_bracketed_with_sentry_anchor():
    out = extract_error_fingerprints("Sentry: [abc1234]")
    assert out == [{"vendor": "sentry", "kind": "event_id", "id": "abc1234"}]


def test_sentry_short_bracketed_with_event_anchor():
    out = extract_error_fingerprints("event: [deadbeef]")
    assert out == [{"vendor": "sentry", "kind": "event_id", "id": "deadbeef"}]


def test_sentry_short_bracketed_no_anchor_rejected():
    """A bare ``[abc1234]`` without a sentry / event anchor doesn't fire."""
    out = extract_error_fingerprints("see [abc1234] for the commit")
    assert out == []


def test_sentry_inline_short_id():
    out = extract_error_fingerprints("Sentry id: abc1234")
    assert out == [{"vendor": "sentry", "kind": "event_id", "id": "abc1234"}]


def test_sentry_inline_long_short_id():
    """16-char short IDs are accepted (the upper bound of the short range)."""
    out = extract_error_fingerprints("sentry event id: deadbeef12345678")
    assert out == [
        {"vendor": "sentry", "kind": "event_id", "id": "deadbeef12345678"}
    ]


# ---- Datadog: trace_id / span_id -------------------------------


def test_datadog_trace_id_numeric():
    out = extract_error_fingerprints("dd.trace_id=1234567890987654321")
    assert out == [{"vendor": "datadog", "kind": "trace_id", "id": "1234567890987654321"}]


def test_datadog_span_id_numeric():
    out = extract_error_fingerprints("dd.span_id=98765432123")
    assert out == [{"vendor": "datadog", "kind": "span_id", "id": "98765432123"}]


def test_datadog_trace_span_pair():
    out = extract_error_fingerprints("dd.trace_id=12345 dd.span_id=67890")
    kinds = [(e["vendor"], e["kind"]) for e in out]
    assert ("datadog", "trace_id") in kinds
    assert ("datadog", "span_id") in kinds


def test_datadog_trace_id_hex_form():
    """W3C trace context: 16-hex / 32-hex blobs."""
    out = extract_error_fingerprints(
        "dd.trace_id=a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
    )
    assert out == [
        {"vendor": "datadog", "kind": "trace_id", "id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"}
    ]


def test_datadog_bare_trace_id_needs_anchor():
    """A bare ``trace_id: <hex>`` with no DD anchor is REJECTED."""
    out = extract_error_fingerprints("trace_id: deadbeef12345678")
    assert out == []


def test_datadog_bare_trace_id_with_anchor():
    out = extract_error_fingerprints(
        "[Datadog] trace_id: deadbeef12345678deadbeef12345678"
    )
    assert any(
        e["vendor"] == "datadog" and e["kind"] == "trace_id"
        for e in out
    )


# ---- Rollbar ---------------------------------------------------


def test_rollbar_event_id():
    out = extract_error_fingerprints("Rollbar event #98765")
    assert out == [{"vendor": "rollbar", "kind": "event_id", "id": "98765"}]


def test_rollbar_occurrence():
    out = extract_error_fingerprints("[Rollbar] occurrence 6789")
    assert out == [{"vendor": "rollbar", "kind": "event_id", "id": "6789"}]


def test_rollbar_item():
    out = extract_error_fingerprints("rollbar item: 12345")
    assert out == [{"vendor": "rollbar", "kind": "event_id", "id": "12345"}]


def test_rollbar_no_anchor_rejected():
    """A bare ``event #99999`` with no rollbar anchor doesn't fire."""
    out = extract_error_fingerprints("event #99999 was triggered")
    assert out == []


# ---- New Relic -------------------------------------------------


def test_newrelic_trace_id():
    out = extract_error_fingerprints(
        "New Relic trace_id: a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
    )
    assert out == [
        {"vendor": "newrelic", "kind": "trace_id", "id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"}
    ]


def test_newrelic_alternate_anchor():
    """``newrelic`` (no space) and ``nr-`` short prefix also work."""
    out = extract_error_fingerprints(
        "newrelic trace-id=a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
    )
    assert any(e["vendor"] == "newrelic" for e in out)


def test_newrelic_16hex_trace():
    out = extract_error_fingerprints(
        "New Relic traceId: deadbeef12345678"
    )
    assert out == [
        {"vendor": "newrelic", "kind": "trace_id", "id": "deadbeef12345678"}
    ]


def test_newrelic_no_anchor_rejected():
    out = extract_error_fingerprints(
        "trace_id: a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
    )
    assert out == []


# ---- Bugsnag ---------------------------------------------------


def test_bugsnag_error_id():
    out = extract_error_fingerprints("Bugsnag error #abc123XYZ")
    assert out == [{"vendor": "bugsnag", "kind": "event_id", "id": "abc123XYZ"}]


def test_bugsnag_case_preserved():
    """Bugsnag IDs preserve case (they may be alphanumeric)."""
    out = extract_error_fingerprints("Bugsnag event-XYZW1234")
    assert any(e["id"] == "XYZW1234" for e in out)


def test_bugsnag_no_anchor_rejected():
    out = extract_error_fingerprints("event #abc123")
    assert out == []


# ---- Honeybadger -----------------------------------------------


def test_honeybadger_fault_id():
    out = extract_error_fingerprints("Honeybadger fault #54321")
    assert out == [{"vendor": "honeybadger", "kind": "fault_id", "id": "54321"}]


def test_honeybadger_notice():
    out = extract_error_fingerprints("Honeybadger Notice 67890")
    assert out == [{"vendor": "honeybadger", "kind": "fault_id", "id": "67890"}]


def test_honeybadger_no_anchor_rejected():
    out = extract_error_fingerprints("fault #12345")
    assert out == []


# ---- Airbrake --------------------------------------------------


def test_airbrake_error_id():
    out = extract_error_fingerprints("Airbrake notice #11223")
    assert out == [{"vendor": "airbrake", "kind": "event_id", "id": "11223"}]


def test_airbrake_bracketed():
    out = extract_error_fingerprints("[Airbrake] [tag] error #67890")
    assert out == [{"vendor": "airbrake", "kind": "event_id", "id": "67890"}]


def test_airbrake_no_anchor_rejected():
    out = extract_error_fingerprints("notice #99999")
    assert out == []


# ---- Order & dedupe --------------------------------------------


def test_order_preserves_ocr_offset():
    text = (
        "first: dd.trace_id=11111\n"
        "second: Sentry: [abc1234]\n"
        "third: Rollbar event #99999\n"
    )
    out = extract_error_fingerprints(text)
    kinds = [(e["vendor"], e["kind"]) for e in out]
    assert kinds == [
        ("datadog", "trace_id"),
        ("sentry", "event_id"),
        ("rollbar", "event_id"),
    ]


def test_dedupe_identical():
    text = "dd.trace_id=12345\ndd.trace_id=12345"
    out = extract_error_fingerprints(text)
    assert len(out) == 1


def test_distinct_vendors_kept():
    text = "dd.trace_id=12345\nRollbar event #12345"
    # Same numeric id but different vendor -> two entries.
    out = extract_error_fingerprints(text)
    assert len(out) == 2


def test_cap_at_30():
    lines = [f"Rollbar event #{i:05d}" for i in range(50)]
    out = extract_error_fingerprints("\n".join(lines))
    assert len(out) == 30


# ---- Empty / no-match -----------------------------------------


def test_empty_text():
    assert extract_error_fingerprints("") == []


def test_no_fingerprint():
    text = (
        "Hello world\n"
        "Just a regular log line\n"
        "INFO some message\n"
    )
    assert extract_error_fingerprints(text) == []


def test_random_uuid_not_misfired():
    """A random standalone UUID is not a fingerprint without vendor anchor."""
    out = extract_error_fingerprints("a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d")
    assert out == []


# ---- Cross-category pipeline integration -----------------------


def test_enrich_pipeline_writes_raw_error_fingerprints():
    text = (
        "Traceback (most recent call last):\n"
        '  File "x.py", line 12, in main\n'
        "ValueError: bad input\n"
        "Sentry Event ID: deadbeef12345678deadbeef12345678\n"
    )
    fields = ExtractedFields()
    out = enrich(Category.error_stacktrace, fields, OCRResult(text=text))
    assert "error_fingerprints" in out.raw
    assert any(
        e["vendor"] == "sentry" and e["kind"] == "event_id"
        for e in out.raw["error_fingerprints"]
    )


def test_enrich_pipeline_runs_for_chat_too():
    """The matcher runs cross-category -- chat captures cite fingerprints too."""
    text = "Alice: page Bob -- dd.trace_id=12345 dd.span_id=67890"
    fields = ExtractedFields()
    out = enrich(Category.chat_screenshot, fields, OCRResult(text=text))
    assert "error_fingerprints" in out.raw
    fps = out.raw["error_fingerprints"]
    assert any(e["kind"] == "trace_id" for e in fps)
    assert any(e["kind"] == "span_id" for e in fps)


def test_enrich_pipeline_no_fingerprints_no_key():
    """When no fingerprints found, raw shouldn't carry the key."""
    text = "Just normal text with no error data"
    fields = ExtractedFields()
    out = enrich(Category.other, fields, OCRResult(text=text))
    assert "error_fingerprints" not in out.raw


# ---- All-vendors composite example -----------------------------


def test_multi_vendor_composite():
    text = (
        "Sentry Event ID: deadbeefcafebabe1234567890abcdef\n"
        "dd.trace_id=98765 dd.span_id=11111\n"
        "Rollbar event #4567\n"
        "Bugsnag error #ABCD1234\n"
        "Honeybadger fault #5555\n"
        "Airbrake notice #8888\n"
        "New Relic trace_id: a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6\n"
    )
    out = extract_error_fingerprints(text)
    vendors = {e["vendor"] for e in out}
    assert vendors == {
        "sentry", "datadog", "rollbar", "bugsnag",
        "honeybadger", "airbrake", "newrelic",
    }
