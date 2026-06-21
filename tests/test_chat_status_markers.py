"""Chat status marker extraction (read / delivered / unread / typing).

The new ``ChatFields.statuses`` slot captures status badges visible
in a chat screenshot. Each entry is a dict with at minimum a
``status`` tag (``read`` / ``delivered`` / ``seen`` / ``sent`` /
``unread`` / ``typing``) and optionally a ``time`` (normalised by
parse_timestamp) or a ``count`` (for ``3 unread messages``).

Recognised platform conventions:
- iMessage: "Read 11:14 AM", "Delivered" + optional time.
- WhatsApp / Telegram: "Seen 12:00", "Read at 11:14".
- Slack / Discord: "3 unread messages", "2 unread".
- Generic: "Alice is typing...", "typing...".

Order: status entries are sorted by their offset in the OCR text so
the list reflects the top-to-bottom reading order, not the matcher
iteration order. De-dupe runs after sorting on the (status,
time-or-count) tuple.
"""
from __future__ import annotations

import pytest
from shotclassify_common import ChatFields, OCRResult
from shotclassify_extract import enrich_chat
from shotclassify_extract.chat import _extract_statuses

# ---- _extract_statuses helper ----------------------------------------


def test_read_with_ampm():
    assert _extract_statuses("Read 11:14 AM") == [
        {"status": "read", "time": "11:14"}
    ]


def test_read_with_at_separator():
    assert _extract_statuses("Read at 11:14") == [
        {"status": "read", "time": "11:14"}
    ]


def test_read_yesterday():
    """Non-clock relative time ('yesterday') stored verbatim."""
    assert _extract_statuses("Read yesterday") == [
        {"status": "read", "time": "yesterday"}
    ]


def test_delivered_bare():
    """Bare 'Delivered' with no trailing time still tags."""
    assert _extract_statuses("Delivered") == [{"status": "delivered"}]


def test_delivered_with_pm_normalised():
    """``Delivered 10:30 PM`` -> 24h 22:30."""
    assert _extract_statuses("Delivered 10:30 PM") == [
        {"status": "delivered", "time": "22:30"}
    ]


def test_seen_with_clock():
    assert _extract_statuses("Seen 12:00") == [
        {"status": "seen", "time": "12:00"}
    ]


def test_sent_with_pm_normalised():
    assert _extract_statuses("Sent 3:45 PM") == [
        {"status": "sent", "time": "15:45"}
    ]


def test_unread_bare():
    assert _extract_statuses("Unread") == [{"status": "unread"}]


def test_unread_with_count():
    """``3 unread messages`` -> count=3 (no time field)."""
    assert _extract_statuses("3 unread messages") == [
        {"status": "unread", "count": "3"}
    ]


def test_unread_two_word_form():
    assert _extract_statuses("2 unread") == [
        {"status": "unread", "count": "2"}
    ]


def test_typing_with_prefix():
    assert _extract_statuses("Alice is typing...") == [
        {"status": "typing"}
    ]


def test_typing_bare():
    assert _extract_statuses("typing") == [{"status": "typing"}]


def test_typing_capital_bare():
    """Lowercase is required by the rest of the regex, capital case
    still works because of the optional name prefix."""
    assert _extract_statuses("Bob is typing") == [{"status": "typing"}]


# ---- order / dedup ----------------------------------------------------


def test_order_follows_ocr_text_offset_not_matcher_order():
    """A Delivered line that appears BEFORE a Read line in the source
    should be returned BEFORE the Read entry, even though the matcher
    iterates Read first."""
    text = "Hey there\nDelivered 10:30 PM\nRead 11:14 AM"
    out = _extract_statuses(text)
    assert out == [
        {"status": "delivered", "time": "22:30"},
        {"status": "read", "time": "11:14"},
    ]


def test_dedup_on_status_time_pair():
    """Two identical 'Read 11:14 AM' entries collapse to one."""
    text = "Read 11:14 AM\nRead 11:14 AM"
    assert _extract_statuses(text) == [
        {"status": "read", "time": "11:14"}
    ]


def test_different_times_kept_separately():
    """``Read 10:00`` and ``Read 11:00`` are separate entries."""
    text = "Read 10:00 AM and later Read 11:00 AM"
    out = _extract_statuses(text)
    assert {"status": "read", "time": "10:00"} in out
    assert {"status": "read", "time": "11:00"} in out


# ---- rejection / boundary cases ---------------------------------------


def test_word_boundary_rejects_iread():
    """``iRead`` (no word break before R) should NOT match Read."""
    assert _extract_statuses("iRead 10:30") == []


def test_lowercase_read_not_matched():
    """Status markers must be Capital-R Read; lowercase is too common
    in regular message text ('have you read this')."""
    assert _extract_statuses("read this article") == []


def test_message_body_does_not_false_positive():
    """A natural-language sentence with 'read' lowercase must not tag."""
    assert _extract_statuses("I have read your message yesterday") == []


def test_empty_or_none_returns_empty():
    assert _extract_statuses("") == []
    assert _extract_statuses("   \n   ") == []


def test_cap_at_20_statuses():
    """Pathological screenshot with 30 status markers caps at 20."""
    text = "\n".join(f"Read 1{i:02d}:00" for i in range(30))
    out = _extract_statuses(text)
    assert len(out) <= 20


# ---- enrich_chat integration -------------------------------------------


def test_enrich_chat_populates_statuses_from_ocr():
    ocr = OCRResult(
        text=(
            "Alice: hey\n"
            "Bob: hi\n"
            "Delivered 10:30 PM\n"
            "Read 11:14 AM\n"
        ),
        word_count=8,
    )
    out = enrich_chat(None, ocr)
    assert out.statuses == [
        {"status": "delivered", "time": "22:30"},
        {"status": "read", "time": "11:14"},
    ]


def test_enrich_chat_merges_caller_and_ocr_statuses():
    """An LLM-supplied status list is preserved and de-duped against
    the OCR-parsed list."""
    existing = ChatFields(statuses=[{"status": "typing"}])
    ocr = OCRResult(
        text="Delivered 10:30 PM\nAlice is typing...\n",
        word_count=5,
    )
    out = enrich_chat(existing, ocr)
    # Caller's "typing" entry preserved; ocr-parsed "Delivered" added.
    assert {"status": "typing"} in out.statuses
    assert {"status": "delivered", "time": "22:30"} in out.statuses
    # Dedup: typing appears in both inputs, should only appear once.
    typing_entries = [s for s in out.statuses if s.get("status") == "typing"]
    assert len(typing_entries) == 1


def test_enrich_chat_omits_statuses_when_none_present():
    ocr = OCRResult(text="Alice: hi\nBob: hey\n", word_count=4)
    out = enrich_chat(None, ocr)
    assert out.statuses == []


def test_enrich_chat_preserves_existing_fields_alongside_statuses():
    """Adding statuses must not regress the existing chat fields."""
    ocr = OCRResult(
        text=(
            "#general @alice Bob: hi\n"
            "Alice: hey #channel\n"
            "Read 11:14 AM\n"
        ),
        word_count=7,
    )
    out = enrich_chat(None, ocr)
    assert "#general" in out.hashtags
    assert any(s.get("status") == "read" for s in out.statuses)
    # Mentions extraction still works
    assert any("alice" in m.lower() for m in out.mentions)


# ---- LLM round-trip via classify client --------------------------------


def test_llm_supplied_statuses_survive_round_trip():
    """The classify client's payload-mapping path must hand
    ``statuses`` through to ChatFields."""
    from shotclassify_classify.client import _parse_llm_payload

    payload = {
        "primary": "chat_screenshot",
        "confidences": [{"category": "chat_screenshot", "score": 0.9}],
        "rationale": "",
        "fields": {
            "chat": {
                "platform": "imessage",
                "messages": [],
                "statuses": [
                    {"status": "read", "time": "11:14"},
                    {"status": "delivered"},
                ],
            }
        },
    }
    _, fields = _parse_llm_payload(payload)
    assert fields.chat is not None
    assert fields.chat.statuses == [
        {"status": "read", "time": "11:14"},
        {"status": "delivered"},
    ]


@pytest.mark.parametrize(
    "marker,expected_status",
    [
        ("Delivered", "delivered"),
        ("Read", "read"),
        ("Seen", "seen"),
        ("Sent 1:00 AM", "sent"),
        ("Unread", "unread"),
        ("typing", "typing"),
    ],
)
def test_each_status_tag_round_trips(marker, expected_status):
    """Each canonical status tag is recognised by the extractor."""
    out = _extract_statuses(f"Header\n{marker}\nFooter")
    assert any(s["status"] == expected_status for s in out), out
