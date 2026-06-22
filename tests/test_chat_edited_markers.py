"""Chat edited-message marker detection (``ChatFields.edits``).

The new ``ChatFields.edits`` slot captures messages that show an
``(edited)`` / ``(edited 2m)`` / ``[edited]`` / ``edited at 12:34``
marker. Each entry is a ``{"sender", "text", "tail"}`` dict with
``sender`` as the speaker (when extractable), ``text`` as the
message body with the marker stripped, and ``tail`` as the matched
marker tail (so dashboards can render ``"edited 2m"`` without
re-parsing).
"""
from __future__ import annotations

from shotclassify_common import ChatFields, OCRResult
from shotclassify_extract import enrich_chat
from shotclassify_extract.chat import _extract_edits

# ---- bare marker shapes -----------------------------------------


def test_bare_paren_edited():
    out = _extract_edits("Hello world (edited)")
    assert out == [{"text": "Hello world", "tail": "edited"}]


def test_bare_paren_edited_2m():
    """Discord-style ``(edited 2m)``."""
    out = _extract_edits("Hello world (edited 2m)")
    assert out == [{"text": "Hello world", "tail": "edited 2m"}]


def test_bare_paren_edited_5h():
    out = _extract_edits("foo bar (edited 5h)")
    assert out == [{"text": "foo bar", "tail": "edited 5h"}]


def test_bare_paren_edited_just_now():
    """Slack-style ``(edited just now)``."""
    out = _extract_edits("ship it (edited just now)")
    assert out == [{"text": "ship it", "tail": "edited just now"}]


def test_bare_paren_edited_minutes_ago():
    out = _extract_edits("oops (edited 12 minutes ago)")
    assert out == [{"text": "oops", "tail": "edited 12 minutes ago"}]


def test_bare_bracket_edited():
    """Telegram bot-style ``[edited]``."""
    out = _extract_edits("retracted [edited]")
    assert out == [{"text": "retracted", "tail": "edited"}]


def test_inline_edited_at():
    """Slack-web ``edited at 12:34``."""
    out = _extract_edits("hello world edited at 12:34")
    assert out == [{"text": "hello world", "tail": "edited at 12:34"}]


def test_inline_edited_2m_ago():
    out = _extract_edits("the thing edited 2m ago")
    assert out == [{"text": "the thing", "tail": "edited 2m ago"}]


def test_paren_modified():
    out = _extract_edits("status changed (modified)")
    assert out == [{"text": "status changed", "tail": "modified"}]


def test_paren_updated():
    out = _extract_edits("docs (updated)")
    assert out == [{"text": "docs", "tail": "updated"}]


def test_case_insensitive():
    """``(Edited)`` / ``(EDITED)`` both match."""
    out = _extract_edits("first (Edited)\nsecond (EDITED)")
    assert len(out) == 2
    assert all(e["tail"] == "edited" for e in out)


# ---- sender extraction -----------------------------------------


def test_with_sender_paren():
    out = _extract_edits("Alice: hi there (edited)")
    assert out == [{"sender": "Alice", "text": "hi there", "tail": "edited"}]


def test_with_sender_inline():
    out = _extract_edits("Bob: ship it edited at 14:00")
    assert out == [{"sender": "Bob", "text": "ship it", "tail": "edited at 14:00"}]


def test_with_sender_bracket():
    out = _extract_edits("Cara: nm [edited]")
    assert out == [{"sender": "Cara", "text": "nm", "tail": "edited"}]


def test_sender_with_underscore_and_dash():
    """The default sender regex accepts underscores / dashes / digits."""
    out = _extract_edits("Alice_Smith: hi (edited)")
    assert any(e.get("sender") == "Alice_Smith" for e in out)


# ---- multi-line / order ----------------------------------------


def test_multiple_edits_in_order():
    text = (
        "Alice: first message (edited)\n"
        "Bob: second message (edited 2m)\n"
        "Cara: third (edited just now)\n"
    )
    out = _extract_edits(text)
    senders = [e.get("sender") for e in out]
    assert senders == ["Alice", "Bob", "Cara"]


def test_non_edited_lines_skipped():
    text = (
        "Alice: hello\n"
        "Bob: hi (edited)\n"
        "Cara: bye\n"
    )
    out = _extract_edits(text)
    assert len(out) == 1
    assert out[0]["sender"] == "Bob"


def test_empty_text():
    assert _extract_edits("") == []
    assert _extract_edits(None) == []  # type: ignore[arg-type]


# ---- rejection cases ------------------------------------------


def test_substring_inside_word_not_matched():
    """``unedited`` / ``credited`` shouldn't match the inline form."""
    # The inline regex requires the word ``edited`` to be space-
    # preceded. ``unedited`` contains "edited" mid-word, so the
    # lookbehind ``(?<=\s)`` rejects it.
    out = _extract_edits("the unedited version")
    assert out == []
    out = _extract_edits("credited to author")
    assert out == []


def test_marker_must_be_at_end():
    """``(edited) is the new`` -- marker in mid-line is NOT captured
    because the trailing ``\\s*$`` anchor requires the marker to sit
    at end-of-line."""
    out = _extract_edits("(edited) is the new normal")
    assert out == []


def test_just_marker_no_body():
    """A line that is JUST the marker captures an empty body."""
    out = _extract_edits("(edited)")
    assert out == [{"text": "", "tail": "edited"}]


# ---- enrich_chat integration ----------------------------------


def test_enrich_chat_populates_edits_field():
    text = (
        "Alice: hi (edited)\n"
        "Bob: bye (edited 2m)\n"
    )
    out = enrich_chat(None, OCRResult(text=text, word_count=8))
    senders = [e.get("sender") for e in out.edits]
    assert senders == ["Alice", "Bob"]


def test_enrich_chat_preserves_caller_edits():
    """LLM-supplied edits land first, OCR edits append after."""
    existing = ChatFields(
        edits=[{"sender": "LLM", "text": "from llm", "tail": "edited"}],
    )
    text = "Alice: bye (edited)\n"
    out = enrich_chat(existing, OCRResult(text=text, word_count=4))
    assert out.edits[0]["sender"] == "LLM"
    assert any(e.get("sender") == "Alice" for e in out.edits)


def test_enrich_chat_dedupes_identical_edits():
    """Caller edit identical to OCR edit -> one entry total."""
    existing = ChatFields(
        edits=[{"sender": "Alice", "text": "hi there", "tail": "edited"}],
    )
    text = "Alice: hi there (edited)\n"
    out = enrich_chat(existing, OCRResult(text=text, word_count=4))
    alice_edits = [e for e in out.edits if e.get("sender") == "Alice"]
    assert len(alice_edits) == 1


def test_enrich_chat_no_edits_returns_empty_list():
    text = "Alice: hello\nBob: hi\n"
    out = enrich_chat(None, OCRResult(text=text, word_count=4))
    assert out.edits == []


def test_enrich_chat_real_imessage_thread():
    text = (
        "Alice: heading out now\n"
        "Bob: on my way (edited)\n"
        "Cara: see you soon\n"
        "Dave: running 5 min late (edited 2m)\n"
    )
    out = enrich_chat(None, OCRResult(text=text, word_count=15))
    senders = sorted(e["sender"] for e in out.edits)
    assert senders == ["Bob", "Dave"]
    bob = next(e for e in out.edits if e["sender"] == "Bob")
    assert bob["text"] == "on my way"
    assert bob["tail"] == "edited"
    dave = next(e for e in out.edits if e["sender"] == "Dave")
    assert dave["text"] == "running 5 min late"
    assert dave["tail"] == "edited 2m"
