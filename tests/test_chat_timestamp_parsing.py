"""Tests for chat-line timestamp parsing.

The new :func:`parse_timestamp` helper recognises ISO8601, 12-hour
AM/PM, and 24-hour bare clock stamps. It normalises 12-hour shapes to
24-hour ``HH:MM`` so downstream sorting works lexicographically and
leaves ISO values untouched so the screenshot's timezone is preserved
for the caller.

The new :func:`enrich_chat` behaviour pulls the stamp out of message
bodies into ``messages[i]["time"]`` and strips it (and any adjacent
separator) from the body so the message text is clean.
"""
from __future__ import annotations

import pytest
from shotclassify_common import ChatFields, OCRResult
from shotclassify_extract import enrich_chat, parse_timestamp


@pytest.mark.parametrize(
    "line,expected",
    [
        # ISO8601: returned verbatim
        ("posted at 2026-01-01T12:34:56Z", "2026-01-01T12:34:56Z"),
        ("2026-04-19T07:05:00+02:00 - hello", "2026-04-19T07:05:00+02:00"),
        ("2026-04-19T07:05 hi", "2026-04-19T07:05"),
        # 12-hour AM/PM normalised to 24h
        ("12:34 PM", "12:34"),
        ("12:34 AM", "00:34"),
        ("9:05 am", "09:05"),
        ("1:00 pm", "13:00"),
        ("11:59 P.M.", "23:59"),
        ("Sent 7:45a.m. by Alice", "07:45"),
        # Bare 24h clock
        ("13:42", "13:42"),
        ("00:00 midnight", "00:00"),
        ("23:59 - last", "23:59"),
    ],
)
def test_parse_timestamp_shapes(line, expected):
    assert parse_timestamp(line) == expected


def test_parse_timestamp_returns_none_when_absent():
    assert parse_timestamp("hello world") is None
    assert parse_timestamp("") is None
    # 33:33 is not a valid clock and we have no AM/PM signal so reject it.
    assert parse_timestamp("33:33") is None


def test_parse_timestamp_ignores_digits_in_word_middle():
    """A version string like ``v1.12.34`` must not be read as a clock."""
    # The clock regex requires a colon between the two groups, which
    # eliminates this case at the regex level.
    assert parse_timestamp("ship v1.12.34 today") is None


def test_iso_wins_over_bare_clock_when_both_present():
    line = "2026-01-01T12:34:56Z (was 09:00 PT)"
    assert parse_timestamp(line) == "2026-01-01T12:34:56Z"


# --- enrich_chat backfills time on parsed messages --------------------------


def test_enrich_chat_pulls_time_from_sender_lines():
    text = (
        "Alice: 12:34 PM ship it\n"
        "Bob:   12:35 PM agreed\n"
        "Cara:  13:01 merging\n"
    )
    out = enrich_chat(None, OCRResult(text=text, word_count=10))
    times = [m.get("time") for m in out.messages]
    texts = [m["text"] for m in out.messages]
    assert times == ["12:34", "12:35", "13:01"]
    assert texts == ["ship it", "agreed", "merging"]


def test_enrich_chat_keeps_text_when_no_timestamp():
    text = "Alice: hello there\n"
    out = enrich_chat(None, OCRResult(text=text, word_count=3))
    assert out.messages == [{"sender": "Alice", "text": "hello there"}]


def test_enrich_chat_iso_timestamp_in_line():
    text = "Alice: 2026-01-01T12:34:56Z shipped\n"
    out = enrich_chat(None, OCRResult(text=text, word_count=4))
    assert out.messages[0]["time"] == "2026-01-01T12:34:56Z"
    assert out.messages[0]["text"] == "shipped"


def test_enrich_chat_backfills_time_on_caller_messages():
    """LLM hands us raw messages; we still normalise the stamp."""
    existing = ChatFields(
        messages=[
            {"sender": "Alice", "text": "9:05 am ready"},
            {"sender": "Bob", "text": "no time here"},
            {"sender": "Cara", "text": "1:00 pm — going live"},
        ]
    )
    out = enrich_chat(existing, OCRResult(text="", word_count=0))
    assert out.messages[0]["time"] == "09:05"
    assert out.messages[0]["text"] == "ready"
    assert "time" not in out.messages[1]
    assert out.messages[1]["text"] == "no time here"
    assert out.messages[2]["time"] == "13:00"
    assert out.messages[2]["text"] == "going live"


def test_enrich_chat_does_not_overwrite_existing_time():
    existing = ChatFields(
        messages=[{"sender": "Alice", "text": "1:00 pm hi", "time": "preset"}]
    )
    out = enrich_chat(existing, OCRResult(text="", word_count=0))
    assert out.messages[0]["time"] == "preset"
    # Body left alone too because we only strip when we set the time.
    assert out.messages[0]["text"] == "1:00 pm hi"
