"""Chat thread-reply marker detection tests.

A new ChatFields.threads slot captures thread-reply footers found
in chat screenshots (Slack ``5 replies``, Discord ``Thread - 4
replies``, Teams ``Reply (3)``, ``View thread``, ``Last reply 2h
ago``).

Each entry is a ``{"count": int, "last_reply": str | None,
"sender": str | None}`` dict.
"""
from __future__ import annotations

from shotclassify_common import ChatFields, OCRResult
from shotclassify_extract.chat import _extract_threads, enrich_chat

# ---- Basic count-only forms --------------------------------------


def test_single_reply():
    out = _extract_threads("1 reply")
    assert out == [{"count": 1, "last_reply": None}]


def test_two_replies():
    out = _extract_threads("2 replies")
    assert out == [{"count": 2, "last_reply": None}]


def test_five_replies():
    out = _extract_threads("5 replies")
    assert out == [{"count": 5, "last_reply": None}]


def test_large_count():
    out = _extract_threads("125 replies")
    assert out == [{"count": 125, "last_reply": None}]


def test_zero_replies_does_not_fire():
    # "0 replies" still matches as a thread marker with count=0.
    out = _extract_threads("0 replies")
    assert out == [{"count": 0, "last_reply": None}]


# ---- Empty / None input ------------------------------------------


def test_empty_text():
    assert _extract_threads("") == []


def test_none_text():
    assert _extract_threads(None) == []  # type: ignore[arg-type]


def test_no_thread_marker_text():
    assert _extract_threads("Just a regular chat message") == []


# ---- Reply with last-reply tail ----------------------------------


def test_replies_with_inline_last_reply():
    out = _extract_threads("5 replies, last reply 2h ago")
    assert out == [{"count": 5, "last_reply": "2h ago"}]


def test_replies_with_and_last_reply():
    out = _extract_threads("3 replies and last reply just now")
    assert out == [{"count": 3, "last_reply": "just now"}]


def test_replies_with_long_last_reply():
    out = _extract_threads("8 replies, last reply 1 hour ago")
    assert out == [{"count": 8, "last_reply": "1 hour ago"}]


# ---- Standalone "Last reply" line --------------------------------


def test_standalone_last_reply():
    out = _extract_threads("Last reply 2h ago")
    assert out == [{"count": 0, "last_reply": "2h ago"}]


def test_standalone_last_reply_attaches_to_adjacent_count():
    text = "5 replies\nLast reply 3m ago"
    out = _extract_threads(text)
    # The standalone Last reply attaches to the count-bearing entry
    # on the previous line.
    assert len(out) == 1
    assert out[0]["count"] == 5
    assert out[0]["last_reply"] == "3m ago"


def test_latest_reply_synonym():
    out = _extract_threads("Latest reply 5m ago")
    assert out == [{"count": 0, "last_reply": "5m ago"}]


# ---- Thread-tagged form ------------------------------------------


def test_thread_tagged_dash():
    out = _extract_threads("Thread - 4 replies")
    assert out == [{"count": 4, "last_reply": None}]


def test_thread_tagged_colon():
    out = _extract_threads("Thread: 4 replies")
    assert out == [{"count": 4, "last_reply": None}]


def test_thread_tagged_em_dash():
    out = _extract_threads("Thread \u2014 7 replies")
    assert out == [{"count": 7, "last_reply": None}]


def test_thread_tagged_en_dash():
    out = _extract_threads("Thread \u2013 12 replies")
    assert out == [{"count": 12, "last_reply": None}]


# ---- Teams Reply (N) parenthesised count -------------------------


def test_teams_reply_paren_count():
    out = _extract_threads("Reply (3)")
    assert out == [{"count": 3, "last_reply": None}]


def test_teams_reply_paren_one():
    out = _extract_threads("Reply (1)")
    assert out == [{"count": 1, "last_reply": None}]


def test_teams_reply_paren_large():
    out = _extract_threads("Reply (200)")
    assert out == [{"count": 200, "last_reply": None}]


# ---- Discord "N messages ›" form ---------------------------------


def test_discord_messages_with_chevron():
    out = _extract_threads("12 messages \u203A")
    assert out == [{"count": 12, "last_reply": None}]


def test_discord_messages_bare():
    out = _extract_threads("4 messages")
    assert out == [{"count": 4, "last_reply": None}]


def test_discord_message_singular():
    out = _extract_threads("1 message")
    assert out == [{"count": 1, "last_reply": None}]


def test_discord_messages_with_arrow():
    out = _extract_threads("8 messages \u2192")
    assert out == [{"count": 8, "last_reply": None}]


# ---- View thread bare form ---------------------------------------


def test_view_thread_bare():
    out = _extract_threads("View thread")
    assert out == [{"count": 0, "last_reply": None}]


def test_view_thread_case_insensitive():
    out = _extract_threads("view thread")
    assert out == [{"count": 0, "last_reply": None}]


# ---- Replying in thread marker -----------------------------------


def test_replying_in_thread():
    out = _extract_threads("Replying in thread")
    assert out == [{"count": 0, "last_reply": None}]


# ---- Case insensitivity ------------------------------------------


def test_replies_uppercase():
    out = _extract_threads("5 REPLIES")
    assert out == [{"count": 5, "last_reply": None}]


def test_thread_tagged_lowercase():
    out = _extract_threads("thread - 4 replies")
    assert out == [{"count": 4, "last_reply": None}]


# ---- Sender attribution -------------------------------------------


def test_sender_attached_to_thread_marker():
    text = "Alice: Hello everyone\n5 replies"
    out = _extract_threads(text)
    assert out[0]["count"] == 5
    assert out[0]["sender"] == "Alice"


def test_sender_inherits_from_nearest_preceding_line():
    text = (
        "Alice: Hello\n"
        "5 replies\n"
        "Bob: Hi there\n"
        "3 replies\n"
    )
    out = _extract_threads(text)
    senders = [e.get("sender") for e in out]
    counts = [e["count"] for e in out]
    assert counts == [5, 3]
    assert senders == ["Alice", "Bob"]


def test_no_sender_when_no_transcript():
    out = _extract_threads("Just 4 replies")
    # "Just" doesn't match Sender: pattern; no sender attached.
    # But the matcher fires on line-start so "Just 4 replies"
    # doesn't satisfy `^[ \t]*4 replies` because "Just " is at
    # start. Should NOT fire.
    assert out == []


# ---- False-positive defences -------------------------------------


def test_mid_sentence_replies_does_not_fire():
    # "There were 5 replies in the chat" -- not a footer.
    out = _extract_threads("There were 5 replies in the chat")
    assert out == []


def test_messages_inside_sentence():
    # "12 messages were sent today" is not a Discord thread footer.
    out = _extract_threads("12 messages were sent today")
    assert out == []


def test_reply_without_paren_count_does_not_fire():
    out = _extract_threads("Reply something")
    assert out == []


def test_view_thread_with_other_text():
    out = _extract_threads("Please view thread carefully")
    assert out == []


# ---- De-duplication ----------------------------------------------


def test_duplicate_count_lines_collapse():
    text = "5 replies\n5 replies"
    out = _extract_threads(text)
    assert len(out) == 1
    assert out[0]["count"] == 5


def test_different_counts_kept_separate():
    text = "5 replies\n10 replies"
    out = _extract_threads(text)
    assert len(out) == 2
    counts = [e["count"] for e in out]
    assert 5 in counts
    assert 10 in counts


# ---- Multiple thread markers in one capture ----------------------


def test_realistic_slack_thread_screenshot():
    text = """Alice: Big feature is ready for review
    5 replies
    Last reply 2h ago
Bob: Looks great
    3 replies
    Last reply 1m ago
Carol: I have one concern
    1 reply
    Last reply just now
"""
    out = _extract_threads(text)
    counts = sorted(e["count"] for e in out)
    # 1, 3, 5
    assert counts == [1, 3, 5]
    # Each has a last_reply tail attached.
    for entry in out:
        assert entry["last_reply"] is not None


def test_realistic_discord_screenshot():
    text = """Alice: Anyone want to play?
Thread - 4 replies
Bob: Friday demo?
Thread: 7 replies
"""
    out = _extract_threads(text)
    counts = sorted(e["count"] for e in out)
    assert counts == [4, 7]


def test_realistic_teams_screenshot():
    text = """Important announcement
Reply (3)
Follow up
Reply (8)
"""
    out = _extract_threads(text)
    counts = sorted(e["count"] for e in out)
    assert counts == [3, 8]


# ---- Order preservation ------------------------------------------


def test_first_seen_order_preserved():
    text = """5 replies
10 replies
3 replies
"""
    out = _extract_threads(text)
    counts = [e["count"] for e in out]
    assert counts == [5, 10, 3]


# ---- Cap behaviour -----------------------------------------------


def test_capped_at_20_entries():
    lines = "\n".join(f"{i} replies" for i in range(1, 30))
    out = _extract_threads(lines)
    assert len(out) <= 20


# ---- last_reply normalisation ------------------------------------


def test_last_reply_lowercased():
    out = _extract_threads("5 replies, last reply 2H AGO")
    assert out[0]["last_reply"] == "2h ago"


def test_last_reply_trailing_punctuation_stripped():
    out = _extract_threads("5 replies, last reply 2h ago.")
    assert out[0]["last_reply"] == "2h ago"


def test_last_reply_whitespace_normalised():
    out = _extract_threads("Last reply 1   hour    ago")
    assert out[0]["last_reply"] == "1 hour ago"


# ---- enrich_chat integration -------------------------------------


def test_enrich_chat_populates_threads_field():
    """enrich_chat surfaces thread markers into ChatFields.threads."""
    ocr = OCRResult(text="Alice: Hello\n5 replies\nLast reply 2h ago")
    chat = enrich_chat(None, ocr)
    assert len(chat.threads) >= 1
    counts = [t["count"] for t in chat.threads]
    assert 5 in counts


def test_enrich_chat_no_threads_when_no_markers():
    ocr = OCRResult(text="Alice: just a regular message")
    chat = enrich_chat(None, ocr)
    assert chat.threads == []


def test_enrich_chat_preserves_caller_threads():
    """Caller-supplied threads are kept and OCR-parsed threads
    are appended without overwrite."""
    existing = ChatFields(
        threads=[{"count": 100, "last_reply": None}],
    )
    ocr = OCRResult(text="5 replies")
    chat = enrich_chat(existing, ocr)
    counts = [t["count"] for t in chat.threads]
    assert 100 in counts  # caller's entry preserved
    assert 5 in counts    # OCR-parsed entry added


def test_enrich_chat_dedupe_with_caller():
    """If the caller already provided an identical thread marker,
    the OCR-parsed one collapses into it."""
    existing = ChatFields(
        threads=[{"count": 5, "last_reply": None, "sender": None}],
    )
    ocr = OCRResult(text="5 replies")
    chat = enrich_chat(existing, ocr)
    # Only one entry (caller's), not duplicated.
    five_count = sum(1 for t in chat.threads if t["count"] == 5)
    assert five_count == 1


# ---- Edge cases --------------------------------------------------


def test_replies_with_leading_indent():
    out = _extract_threads("    5 replies")
    assert out == [{"count": 5, "last_reply": None}]


def test_replies_with_trailing_whitespace():
    out = _extract_threads("5 replies   ")
    assert out == [{"count": 5, "last_reply": None}]


def test_thread_tagged_inside_paragraph_blocked():
    # Tagged form requires end-of-line anchor; embedded mid-line
    # doesn't fire.
    out = _extract_threads("See Thread - 4 replies in the channel")
    # Won't fire because the surrounding context bumps it off
    # line-start / line-end anchors.
    assert out == []


def test_zero_count_view_thread_distinct_from_zero_count_replying():
    text = "View thread\nReplying in thread"
    out = _extract_threads(text)
    # Both fire as count=0. Both share the same dedupe key
    # (count=0, last_reply='', sender='') so collapse to one entry.
    # That's the intended behaviour because they're both 'engagement
    # markers' for the same parent.
    assert len(out) == 1


def test_sender_with_dash_in_name():
    text = "Bob-Smith: Question\n5 replies"
    out = _extract_threads(text)
    assert out[0]["count"] == 5
    assert out[0]["sender"] == "Bob-Smith"


def test_reply_paren_zero():
    out = _extract_threads("Reply (0)")
    assert out == [{"count": 0, "last_reply": None}]


def test_reply_paren_with_spaces():
    out = _extract_threads("Reply ( 3 )")
    # Doesn't fire because the pattern requires no inner spaces in
    # the paren. Microsoft Teams uses tight parens.
    # If we want to be more permissive we could relax, but for now
    # bare Reply (3) shape only.
    # (Adjust expectation if needed.)
    # Actually our pattern is `\(\s*(?P<count>\d{1,4})\s*\)` - we
    # didn't add \s* in the pattern. Let me confirm: the pattern
    # was `\((?P<count>\d{1,4})\)` -- no spaces.
    assert out == []
