"""Per-message emoji reaction footer detection (``ChatFields.reactions``).

The new ``ChatFields.reactions`` slot captures the reaction
counters that chat platforms render below message bodies. Each
entry is a ``{"sender", "reactions": [{emoji, count}, ...]}`` dict
where ``sender`` is the speaker the reactions belong to (or
``None`` for bare lines / iMessage reaction-by attributes where
the reactor is recorded instead).

Recognised shapes:
- Slack: ``:eyes: 3   :+1: 2   :tada: 1`` shortcode + count pairs
- Discord: ``👀 3   👍 2   🎉 1`` inline Unicode emoji + count
- iMessage: ``❤️ by Alice`` / ``👍 by Bob`` reaction-by lines
"""
from __future__ import annotations

from shotclassify_common import ChatFields, OCRResult
from shotclassify_extract import enrich_chat
from shotclassify_extract.chat import _extract_reactions

# ---- Slack shortcode + count ------------------------------------


def test_slack_eyes_shortcode():
    out = _extract_reactions(":eyes: 3")
    assert len(out) == 1
    assert out[0]["reactions"] == [{"emoji": ":eyes:", "count": 3}]


def test_slack_multiple_shortcodes():
    out = _extract_reactions(":eyes: 3   :+1: 2   :tada: 1")
    assert len(out) == 1
    reactions = out[0]["reactions"]
    emojis = sorted(r["emoji"] for r in reactions)
    assert emojis == [":+1:", ":eyes:", ":tada:"]


def test_slack_shortcode_with_underscore():
    out = _extract_reactions(":thumbs_up: 5")
    assert {"emoji": ":thumbs_up:", "count": 5} in out[0]["reactions"]


def test_slack_shortcode_with_dash():
    out = _extract_reactions(":heart-eyes: 2")
    assert {"emoji": ":heart-eyes:", "count": 2} in out[0]["reactions"]


def test_slack_counts_preserved():
    out = _extract_reactions(":eyes: 42   :+1: 17")
    counts = sorted(r["count"] for r in out[0]["reactions"])
    assert counts == [17, 42]


# ---- Discord / iMessage Unicode emoji + count -------------------


def test_discord_eyes_emoji():
    out = _extract_reactions("👀 3")
    assert len(out) == 1
    assert out[0]["reactions"][0]["emoji"] == "👀"
    assert out[0]["reactions"][0]["count"] == 3


def test_discord_multiple_emojis():
    out = _extract_reactions("👀 3   👍 2   🎉 1")
    assert len(out) == 1
    emojis = [r["emoji"] for r in out[0]["reactions"]]
    counts = [r["count"] for r in out[0]["reactions"]]
    assert "👀" in emojis
    assert "👍" in emojis
    assert "🎉" in emojis
    assert sum(counts) == 6


def test_heart_with_variation_selector():
    """``❤️`` is U+2764 + U+FE0F (variation selector)."""
    out = _extract_reactions("❤️ 5")
    assert len(out) == 1
    assert out[0]["reactions"][0]["count"] == 5


def test_high_emoji_with_count():
    """``💯`` is U+1F4AF (non-BMP)."""
    out = _extract_reactions("💯 10")
    assert {"emoji": "💯", "count": 10} in out[0]["reactions"]


# ---- iMessage reaction-by line ---------------------------------


def test_imessage_heart_by_alice():
    """``❤️ by Alice`` -- the speaker is Alice (the reactor)."""
    out = _extract_reactions("❤️ by Alice")
    assert len(out) == 1
    assert out[0]["sender"] == "Alice"
    assert out[0]["reactions"][0]["emoji"] == "❤️"
    assert out[0]["reactions"][0]["count"] == 1


def test_imessage_thumbs_by_bob():
    out = _extract_reactions("👍 by Bob")
    assert out[0]["sender"] == "Bob"


def test_imessage_multi_word_name():
    out = _extract_reactions("👍 by Alice Smith")
    assert out[0]["sender"].startswith("Alice")


# ---- per-sender attribution -----------------------------------


def test_sender_attached_to_following_reactions():
    """The reactions footer attaches to the nearest preceding sender."""
    text = (
        "Alice: ship it now\n"
        ":eyes: 3   :+1: 2\n"
    )
    out = _extract_reactions(text)
    assert len(out) == 1
    assert out[0]["sender"] == "Alice"


def test_sender_switches_between_messages():
    """Two messages, each with their own reactions, attribute correctly."""
    text = (
        "Alice: first message\n"
        ":eyes: 3\n"
        "Bob: second message\n"
        ":+1: 5\n"
    )
    out = _extract_reactions(text)
    assert len(out) == 2
    assert out[0]["sender"] == "Alice"
    assert out[0]["reactions"][0]["emoji"] == ":eyes:"
    assert out[1]["sender"] == "Bob"
    assert out[1]["reactions"][0]["emoji"] == ":+1:"


def test_bare_reaction_line_has_no_sender():
    out = _extract_reactions("👀 3")
    assert out[0]["sender"] is None


# ---- order / dedupe / cap -------------------------------------


def test_order_preserved_within_line():
    out = _extract_reactions(":eyes: 3   :+1: 2   :tada: 1")
    emojis = [r["emoji"] for r in out[0]["reactions"]]
    assert emojis == [":eyes:", ":+1:", ":tada:"]


def test_dedupe_repeated_emoji_in_line():
    """``:eyes: 3 :eyes: 3`` collapses to one entry."""
    out = _extract_reactions(":eyes: 3   :eyes: 3")
    emojis = [r["emoji"] for r in out[0]["reactions"]]
    assert emojis.count(":eyes:") == 1


def test_cap_at_30_reaction_entries():
    """Many reaction lines -> entries cap at 30."""
    lines = [":eyes: 3" for _ in range(50)]
    text = "\n".join(lines)
    out = _extract_reactions(text)
    # Each line is a separate entry candidate; cap at 30.
    assert len(out) <= 30


# ---- rejection cases -----------------------------------------


def test_empty_text():
    assert _extract_reactions("") == []
    assert _extract_reactions(None) == []  # type: ignore[arg-type]


def test_non_reaction_line_not_matched():
    """A regular message body that mentions an emoji doesn't fire."""
    out = _extract_reactions("Alice: I love it 👀 because it works perfectly always")
    # The Sender: line is consumed by sender_re and skipped (no
    # standalone reactions follow).
    assert out == []


def test_just_emoji_no_count_not_matched():
    """Emoji without a count is not a reaction footer."""
    out = _extract_reactions("👀")
    assert out == []


def test_just_count_no_emoji_not_matched():
    out = _extract_reactions("3")
    assert out == []


def test_pure_prose_skipped():
    out = _extract_reactions("hello world how are you")
    assert out == []


# ---- enrich_chat integration --------------------------------


def test_enrich_chat_populates_reactions_slack():
    text = (
        "Alice: ship it!\n"
        ":eyes: 3   :+1: 2\n"
        "Bob: lgtm\n"
        ":tada: 5\n"
    )
    out = enrich_chat(None, OCRResult(text=text, word_count=12))
    senders = [r["sender"] for r in out.reactions]
    assert "Alice" in senders
    assert "Bob" in senders


def test_enrich_chat_populates_reactions_discord():
    text = (
        "Cara: party time\n"
        "🎉 5   🍰 3\n"
    )
    out = enrich_chat(None, OCRResult(text=text, word_count=6))
    assert len(out.reactions) == 1
    assert out.reactions[0]["sender"] == "Cara"
    emojis = [r["emoji"] for r in out.reactions[0]["reactions"]]
    assert "🎉" in emojis


def test_enrich_chat_imessage_reaction_by():
    text = (
        "Alice: how about lunch?\n"
        "❤️ by Bob\n"
        "👍 by Cara\n"
    )
    out = enrich_chat(None, OCRResult(text=text, word_count=10))
    senders = sorted(r["sender"] for r in out.reactions)
    assert senders == ["Bob", "Cara"]


def test_enrich_chat_preserves_caller_reactions():
    existing = ChatFields(
        reactions=[
            {"sender": "LLM", "reactions": [{"emoji": "🤖", "count": 1}]}
        ]
    )
    text = "Alice: hi\n:eyes: 3\n"
    out = enrich_chat(existing, OCRResult(text=text, word_count=4))
    assert out.reactions[0]["sender"] == "LLM"
    assert any(r.get("sender") == "Alice" for r in out.reactions)


def test_enrich_chat_dedupes_identical_reactions():
    existing = ChatFields(
        reactions=[
            {"sender": "Alice", "reactions": [{"emoji": ":eyes:", "count": 3}]}
        ]
    )
    text = "Alice: hi\n:eyes: 3\n"
    out = enrich_chat(existing, OCRResult(text=text, word_count=4))
    alice_entries = [r for r in out.reactions if r["sender"] == "Alice"]
    assert len(alice_entries) == 1


def test_enrich_chat_no_reactions_returns_empty_list():
    text = "Alice: hello\nBob: hi\n"
    out = enrich_chat(None, OCRResult(text=text, word_count=4))
    assert out.reactions == []


def test_enrich_chat_mixed_real_world_thread():
    """A realistic Slack-flavored thread with mixed reactions."""
    text = (
        "Alice: shipping the v2 release today\n"
        ":rocket: 5   :tada: 3   :eyes: 2\n"
        "Bob: nice!\n"
        ":+1: 4\n"
        "Cara: congrats team\n"
        "🎉 7\n"
    )
    out = enrich_chat(None, OCRResult(text=text, word_count=20))
    senders = [r["sender"] for r in out.reactions]
    assert senders == ["Alice", "Bob", "Cara"]
    alice = out.reactions[0]
    rocket_entry = next(r for r in alice["reactions"] if r["emoji"] == ":rocket:")
    assert rocket_entry["count"] == 5
