"""Chat pin / star / favourite marker detection (``ChatFields.pins``).

The new ``ChatFields.pins`` slot captures small badges and action
footers chat platforms render when a message is pinned to a
channel or starred / favourited / saved by a user.

Each entry is a ``{"kind", "sender"?, "actor"?}`` dict where
``kind`` is ``pin`` or ``star``.

Recognised shapes:
* ``📌 Pinned`` / ``📌 Pinned by Alice`` / ``📌 Pinned Message``
* ``⭐ Starred`` / ``⭐ Starred by Bob``
* ``Bob pinned a message to this channel`` (Slack/Discord action)
* ``Alice pinned "Welcome everyone"`` (Telegram quoted-message form)
* ``Pinned by You`` (iMessage bare-text form)
* ``Alice added a saved item`` (Slack saved-items shape)
* ``Bob starred this message`` (Slack starred-message shape)
"""
from __future__ import annotations

from shotclassify_common import ChatFields, OCRResult
from shotclassify_extract import enrich_chat
from shotclassify_extract.chat import _extract_pins

# ---- Pin emoji + Pinned keyword -----------------------------------


def test_pin_emoji_bare_pinned():
    out = _extract_pins("📌 Pinned")
    assert out == [{"kind": "pin"}]


def test_pin_emoji_pinned_message_keyword():
    out = _extract_pins("📌 Pinned Message")
    assert out == [{"kind": "pin"}]


def test_pin_emoji_pinned_post_keyword():
    """Some clients use 'Pinned Post' (Discord)."""
    out = _extract_pins("📌 Pinned Post")
    assert out == [{"kind": "pin"}]


def test_pin_emoji_pinned_by_name():
    out = _extract_pins("📌 Pinned by Alice")
    assert out == [{"kind": "pin", "actor": "Alice"}]


def test_pin_emoji_pinned_by_you():
    out = _extract_pins("📌 Pinned by You")
    assert out == [{"kind": "pin", "actor": "You"}]


def test_pin_emoji_with_admin_suffix_stripped():
    """``(admin)`` trailing parenthetical is dropped, actor preserved."""
    out = _extract_pins("📌 Pinned by Bob (admin)")
    assert out == [{"kind": "pin", "actor": "Bob"}]


def test_pin_emoji_alt_codepoint_u1f4cd():
    """The alternate pushpin codepoint U+1F4CD also recognised."""
    out = _extract_pins("📍 Pinned")
    assert out == [{"kind": "pin"}]


# ---- Star emoji + Starred / Saved keyword -------------------------


def test_star_emoji_bare_starred():
    out = _extract_pins("⭐ Starred")
    assert out == [{"kind": "star"}]


def test_star_emoji_starred_by_name():
    out = _extract_pins("⭐ Starred by Carol")
    assert out == [{"kind": "star", "actor": "Carol"}]


def test_star_emoji_saved_keyword():
    out = _extract_pins("⭐ Saved")
    assert out == [{"kind": "star"}]


def test_star_emoji_favorited_keyword():
    out = _extract_pins("⭐ Favorited")
    assert out == [{"kind": "star"}]


def test_glowing_star_emoji_saved():
    """The 🌟 glowing-star codepoint U+1F31F also recognised."""
    out = _extract_pins("🌟 Saved")
    assert out == [{"kind": "star"}]


# ---- Slack/Discord pin action footer ------------------------------


def test_slack_pin_action_to_channel():
    out = _extract_pins("Bob pinned a message to this channel")
    assert out == [{"kind": "pin", "actor": "Bob"}]


def test_slack_pin_action_this_message():
    out = _extract_pins("Alice pinned this message")
    assert out == [{"kind": "pin", "actor": "Alice"}]


def test_slack_pin_action_with_trailing_period():
    out = _extract_pins("Alice pinned a message to this channel.")
    assert out == [{"kind": "pin", "actor": "Alice"}]


def test_slack_pin_action_two_word_name():
    out = _extract_pins("Bob Smith pinned a message")
    assert out == [{"kind": "pin", "actor": "Bob Smith"}]


# ---- Telegram pinned quoted ---------------------------------------


def test_telegram_pin_quoted_message():
    out = _extract_pins('Bob pinned "Welcome everyone"')
    assert out == [{"kind": "pin", "actor": "Bob"}]


# ---- iMessage / bare text ------------------------------------------


def test_bare_pinned_by_text_form():
    out = _extract_pins("Pinned by You")
    assert out == [{"kind": "pin", "actor": "You"}]


def test_bare_pinned_by_lowercase_form_case_insensitive():
    out = _extract_pins("pinned by alice")
    assert out == [{"kind": "pin", "actor": "alice"}]


# ---- Slack star action ---------------------------------------------


def test_slack_star_action_this_message():
    out = _extract_pins("Carol starred this message")
    assert out == [{"kind": "star", "actor": "Carol"}]


def test_slack_favorited_action():
    out = _extract_pins("Alice favorited this message")
    assert out == [{"kind": "star", "actor": "Alice"}]


def test_slack_favourited_british_spelling():
    out = _extract_pins("Alice favourited a message")
    assert out == [{"kind": "star", "actor": "Alice"}]


def test_slack_saved_action():
    out = _extract_pins("Bob saved this message")
    assert out == [{"kind": "star", "actor": "Bob"}]


def test_slack_added_saved_item():
    out = _extract_pins("Alice added a saved item")
    assert out == [{"kind": "star", "actor": "Alice"}]


def test_slack_added_saved_item_no_a():
    out = _extract_pins("Bob added saved item")
    assert out == [{"kind": "star", "actor": "Bob"}]


# ---- Multiple markers in same transcript --------------------------


def test_multiple_pins_in_one_transcript():
    text = """\
📌 Pinned by Alice
Bob pinned a message to this channel
"""
    out = _extract_pins(text)
    assert len(out) == 2
    # Sorted by source-text offset (alice first, then bob).
    assert out[0] == {"kind": "pin", "actor": "Alice"}
    assert out[1] == {"kind": "pin", "actor": "Bob"}


def test_pin_and_star_mixed():
    text = """\
📌 Pinned by Alice
⭐ Starred by Bob
"""
    out = _extract_pins(text)
    assert out == [
        {"kind": "pin", "actor": "Alice"},
        {"kind": "star", "actor": "Bob"},
    ]


def test_dedupe_same_pin_appears_twice():
    text = """\
📌 Pinned by Alice
📌 Pinned by Alice
"""
    out = _extract_pins(text)
    assert out == [{"kind": "pin", "actor": "Alice"}]


def test_action_and_emoji_pin_with_same_actor_dedupe():
    """If both the emoji badge AND the action footer name the
    same actor, they dedupe to one entry."""
    text = """\
📌 Pinned by Alice
Alice pinned a message to this channel
"""
    out = _extract_pins(text)
    # Both forms produce (kind=pin, actor=Alice, sender=None) and
    # collapse on dedupe.
    assert out == [{"kind": "pin", "actor": "Alice"}]


# ---- Transcript sender attribution --------------------------------


def test_pin_inherits_nearest_sender():
    """A pin/star marker takes the nearest preceding ``Sender:``
    speaker as its ``sender`` slot."""
    text = """\
Alice: Welcome!
📌 Pinned by Alice
"""
    out = _extract_pins(text)
    # The pin sits BELOW Alice's line so it inherits Alice as sender.
    assert out == [{"kind": "pin", "sender": "Alice", "actor": "Alice"}]


def test_pin_floats_outside_transcript_no_sender():
    """A pin at the very top of the text has no preceding sender."""
    text = "📌 Pinned by Bob\nAlice: hello"
    out = _extract_pins(text)
    assert out == [{"kind": "pin", "actor": "Bob"}]


# ---- Negatives -----------------------------------------------------


def test_empty_input():
    assert _extract_pins("") == []


def test_random_transcript_no_pins():
    text = """\
Alice: hello
Bob: hi there
Alice: how are you
"""
    out = _extract_pins(text)
    assert out == []


def test_pin_emoji_without_keyword_not_pin():
    """``📌`` alone is just an attachment-style emoji, not a pin marker."""
    out = _extract_pins("📌")
    assert out == []


def test_pin_emoji_followed_by_unrelated_word():
    """``📌 Something`` (with a non-Pinned keyword) is rejected."""
    out = _extract_pins("📌 Reminder")
    assert out == []


def test_pinned_in_prose_not_action_footer():
    """``I pinned my hopes on him`` is not a pin action."""
    out = _extract_pins("I pinned my hopes on him")
    assert out == []


def test_starred_in_prose_not_action_footer():
    """``This show starred Alice`` is not a star action."""
    out = _extract_pins("This show starred Alice")
    assert out == []


def test_lowercase_name_action_rejected():
    """Action verbs require capitalised name (Alice not alice)."""
    out = _extract_pins("alice pinned a message")
    assert out == []


# ---- Cap enforcement ----------------------------------------------


def test_cap_at_30_entries():
    """Output is capped at 30 entries even when more markers are present."""
    lines = [f"📌 Pinned by User{i:02d}" for i in range(40)]
    text = "\n".join(lines)
    out = _extract_pins(text)
    assert len(out) == 30


# ---- Pipeline wiring ----------------------------------------------


def test_enrich_chat_populates_pins():
    text = """\
Alice: Welcome team!
📌 Pinned by Alice
"""
    out = enrich_chat(None, OCRResult(text=text))
    assert out.pins == [{"kind": "pin", "sender": "Alice", "actor": "Alice"}]


def test_enrich_chat_caller_pins_preserved_and_merged():
    existing = ChatFields(
        pins=[{"kind": "pin", "actor": "Carol"}],
    )
    text = "📌 Pinned by Dave"
    out = enrich_chat(existing, OCRResult(text=text))
    assert len(out.pins) == 2
    assert out.pins[0] == {"kind": "pin", "actor": "Carol"}
    assert out.pins[1] == {"kind": "pin", "actor": "Dave"}


def test_enrich_chat_dedupes_identical_pins():
    existing = ChatFields(pins=[{"kind": "pin", "actor": "Alice"}])
    text = "📌 Pinned by Alice"
    out = enrich_chat(existing, OCRResult(text=text))
    assert len(out.pins) == 1


def test_enrich_chat_no_pins_returns_empty():
    out = enrich_chat(None, OCRResult(text="Alice: hello there"))
    assert out.pins == []
