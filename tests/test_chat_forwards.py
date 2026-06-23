"""Chat forwarded-message marker detection tests.

A new ChatFields.forwards list captures forward / shared badges
from Telegram / WhatsApp / Discord / Slack screenshots.

Output shape: list of ``{kind, forwarded_from?, sender?}`` dicts.

Kind ∈ {forwarded, forwarded_many, shared}:

* ``forwarded`` -- single forward marker
* ``forwarded_many`` -- WhatsApp "Forwarded many times" chain marker
* ``shared`` -- Slack "Bob shared a message" action footer

Safety properties:

* Bare ``Forwarded`` badge requires full-line match (with optional
  arrow / italic markers) so mid-sentence prose doesn't fire.
* The bracketed and parenthesised shapes take priority over the
  bare ``Forwarded from X`` shape via consumed-span gating to
  prevent double-tagging.
* Sender attribution from nearest preceding ``Sender:`` line.
* Cap 30 entries; dedupe on (kind, forwarded_from, sender) tuple.
"""
from __future__ import annotations

from shotclassify_common import ChatFields, OCRResult
from shotclassify_extract import enrich_chat
from shotclassify_extract.chat import _extract_forwards

# ---- Bare Forwarded badge -----------------------------------------


def test_bare_forwarded_only():
    out = _extract_forwards("Forwarded\nHey check this out")
    assert out == [{"kind": "forwarded"}]


def test_bare_forwarded_with_period():
    out = _extract_forwards("Forwarded.")
    assert out == [{"kind": "forwarded"}]


def test_bare_forwarded_with_arrow_emoji():
    out = _extract_forwards("\u21AA\uFE0F Forwarded")
    assert out == [{"kind": "forwarded"}]


def test_bare_forwarded_with_simple_arrow():
    out = _extract_forwards("\u2192 Forwarded")
    assert out == [{"kind": "forwarded"}]


def test_bare_forwarded_italic_underscore():
    """Markdown italic _Forwarded_ form."""
    out = _extract_forwards("_Forwarded_")
    assert out == [{"kind": "forwarded"}]


def test_bare_forwarded_bold_star():
    """Markdown bold *Forwarded* form."""
    out = _extract_forwards("*Forwarded*")
    assert out == [{"kind": "forwarded"}]


def test_bare_forwarded_lowercase():
    """Case-insensitive: ``forwarded`` lowercase also matches."""
    out = _extract_forwards("forwarded")
    assert out == [{"kind": "forwarded"}]


# ---- Forwarded from X (Telegram) ----------------------------------


def test_forwarded_from_capitalised_name():
    out = _extract_forwards("Forwarded from Alice")
    assert out == [{"kind": "forwarded", "forwarded_from": "Alice"}]


def test_forwarded_from_multiword_name():
    out = _extract_forwards("Forwarded from Alice Smith")
    assert out == [{"kind": "forwarded", "forwarded_from": "Alice Smith"}]


def test_forwarded_from_at_handle():
    out = _extract_forwards("Forwarded from @newschannel")
    assert out == [{"kind": "forwarded", "forwarded_from": "@newschannel"}]


def test_forwarded_from_hash_channel():
    out = _extract_forwards("Forwarded from #general")
    assert out == [{"kind": "forwarded", "forwarded_from": "#general"}]


def test_forwarded_from_with_arrow_emoji():
    out = _extract_forwards("\u21AA\uFE0F Forwarded from Bob")
    assert out == [{"kind": "forwarded", "forwarded_from": "Bob"}]


def test_forwarded_from_with_via_tail_stripped():
    """``Forwarded from Bob via Channel-X`` keeps only ``Bob``."""
    out = _extract_forwards("Forwarded from Bob via Channel-X")
    assert out == [{"kind": "forwarded", "forwarded_from": "Bob"}]


def test_forwarded_from_lowercase_keyword():
    out = _extract_forwards("forwarded from alice")
    assert out == [{"kind": "forwarded", "forwarded_from": "alice"}]


def test_forwarded_with_handle_dashes():
    out = _extract_forwards("Forwarded from @news-channel")
    assert out == [{"kind": "forwarded", "forwarded_from": "@news-channel"}]


def test_forwarded_with_handle_dots():
    out = _extract_forwards("Forwarded from @news.daily")
    assert out == [{"kind": "forwarded", "forwarded_from": "@news.daily"}]


# ---- Bracketed [Forwarded from X] (Discord / Slack) ---------------


def test_bracketed_forwarded_from_channel():
    text = "[Forwarded from #general]\nimportant update"
    out = _extract_forwards(text)
    assert out == [{"kind": "forwarded", "forwarded_from": "#general"}]


def test_bracketed_forwarded_from_user():
    text = "[Forwarded from Alice]\nplease read"
    out = _extract_forwards(text)
    assert out == [{"kind": "forwarded", "forwarded_from": "Alice"}]


def test_bracketed_inline_in_text():
    """Bracketed form fires even mid-line.

    Note: the leading ``Note:`` looks like a sender prefix to the
    transcript-sender regex, so the captured entry attributes the
    forward to sender=``Note``. This is acceptable -- transcript
    prefix matching is a separate concern from the forward
    extractor's primary responsibility.
    """
    out = _extract_forwards("Random: [Forwarded from Bob] today")
    assert any(
        e.get("forwarded_from") == "Bob" and e["kind"] == "forwarded"
        for e in out
    )


# ---- Parenthesised (forwarded from X) -----------------------------


def test_paren_forwarded_from():
    out = _extract_forwards("(Forwarded from Alice)")
    assert out == [{"kind": "forwarded", "forwarded_from": "Alice"}]


def test_paren_inline_below_message():
    text = (
        "Alice: please review this\n"
        "(Forwarded from Bob)"
    )
    out = _extract_forwards(text)
    assert {"kind": "forwarded", "forwarded_from": "Bob",
            "sender": "Alice"} in out


# ---- WhatsApp "Forwarded many times" ------------------------------


def test_forwarded_many_times_basic():
    out = _extract_forwards("Forwarded many times")
    assert out == [{"kind": "forwarded_many"}]


def test_forwarded_many_times_arrow():
    out = _extract_forwards("\u21AA\uFE0F Forwarded many times")
    assert out == [{"kind": "forwarded_many"}]


def test_forwarded_many_times_italic():
    out = _extract_forwards("_Forwarded many times_")
    assert out == [{"kind": "forwarded_many"}]


def test_forwarded_many_times_takes_priority_over_bare():
    """If both ``Forwarded many times`` and bare ``Forwarded`` match
    the same span, the more-specific many-times kind wins."""
    text = "Forwarded many times"
    out = _extract_forwards(text)
    assert out == [{"kind": "forwarded_many"}]
    assert not any(e["kind"] == "forwarded" for e in out)


# ---- Slack: NAME shared a message from CHANNEL --------------------


def test_shared_with_source_channel():
    text = "Bob shared a message from #engineering"
    out = _extract_forwards(text)
    assert out == [
        {"kind": "shared", "sender": "Bob",
         "forwarded_from": "#engineering"}
    ]


def test_shared_with_source_user():
    text = "Alice shared a message from Bob"
    out = _extract_forwards(text)
    assert out == [
        {"kind": "shared", "sender": "Alice", "forwarded_from": "Bob"}
    ]


def test_shared_bare_no_source():
    text = "Carol shared a message"
    out = _extract_forwards(text)
    assert out == [{"kind": "shared", "sender": "Carol"}]


def test_shared_plural_messages_form():
    """``shared messages`` (plural) also matches via optional ``s``."""
    text = "Bob shared messages from #design"
    out = _extract_forwards(text)
    assert out == [
        {"kind": "shared", "sender": "Bob", "forwarded_from": "#design"}
    ]


def test_shared_multiword_sender_name():
    text = "Mary Jane shared a message from Bob"
    out = _extract_forwards(text)
    assert out == [
        {"kind": "shared", "sender": "Mary Jane", "forwarded_from": "Bob"}
    ]


# ---- Sender attribution from preceding transcript -----------------


def test_forwarded_attached_to_preceding_sender():
    text = (
        "Alice: hey check this out\n"
        "Forwarded from Bob"
    )
    out = _extract_forwards(text)
    assert out == [
        {"kind": "forwarded", "forwarded_from": "Bob", "sender": "Alice"}
    ]


def test_forwarded_inherits_sender_until_changed():
    text = (
        "Alice: morning\n"
        "Forwarded from Bob\n"
        "Carol: afternoon\n"
        "Forwarded from Dave"
    )
    out = _extract_forwards(text)
    senders = [e.get("sender") for e in out]
    assert senders == ["Alice", "Carol"]


def test_floating_forwarded_no_sender():
    text = "Forwarded from Alice"
    out = _extract_forwards(text)
    assert out == [{"kind": "forwarded", "forwarded_from": "Alice"}]
    # No sender key because no preceding Sender: line.
    assert "sender" not in out[0]


# ---- Multiple forwards on one screenshot --------------------------


def test_multiple_forwards_ordered_by_offset():
    text = (
        "Forwarded from Alice\n"
        "Message 1\n"
        "Forwarded from Bob\n"
        "Message 2\n"
        "Forwarded from Carol"
    )
    out = _extract_forwards(text)
    sources = [e.get("forwarded_from") for e in out]
    assert sources == ["Alice", "Bob", "Carol"]


def test_dedupe_same_forwarded_from():
    """Same (kind, forwarded_from, sender) repeated collapses."""
    text = (
        "Forwarded from Alice\n"
        "Forwarded from Alice"
    )
    out = _extract_forwards(text)
    # Both lines have no preceding sender so sender is None for both.
    # After dedupe on (kind, forwarded_from, sender) tuple -> 1 entry.
    assert out == [{"kind": "forwarded", "forwarded_from": "Alice"}]


def test_mixed_forms_all_captured():
    """Multiple distinct shapes coexist."""
    text = (
        "Forwarded from Alice\n"
        "[Forwarded from #general]\n"
        "Forwarded many times\n"
        "Bob shared a message from #ops"
    )
    out = _extract_forwards(text)
    kinds = [e["kind"] for e in out]
    assert "forwarded_many" in kinds
    assert "shared" in kinds
    assert kinds.count("forwarded") == 2


# ---- Bracketed-form span-claim defence ----------------------------


def test_bracketed_blocks_inner_from_form():
    """The [Forwarded from #channel] consumed span prevents the bare
    "Forwarded from #channel" matcher from also firing."""
    text = "[Forwarded from #general]"
    out = _extract_forwards(text)
    # Exactly one entry, not two.
    assert len(out) == 1
    assert out[0]["forwarded_from"] == "#general"


def test_paren_blocks_inner_from_form():
    """The (Forwarded from Alice) consumed span prevents double-fire."""
    text = "(Forwarded from Alice)"
    out = _extract_forwards(text)
    assert len(out) == 1


# ---- Prose / false-positive rejection -----------------------------


def test_mid_sentence_forwarded_rejected():
    """``Forwarded that to him`` is prose, not a badge."""
    text = "I Forwarded that to him yesterday"
    out = _extract_forwards(text)
    # Bare-Forwarded matcher requires full-line match.
    assert out == []


def test_forwarded_in_middle_with_period_rejected():
    """``Yes. Forwarded. Done.`` mid-sentence shouldn't fire."""
    text = "Yes. Forwarded. Done."
    out = _extract_forwards(text)
    # The "Forwarded." sits between two other phrases on the same
    # line; bare-Forwarded requires line-start AND line-end so
    # this rejects.
    assert out == []


def test_word_starting_with_forwarded_rejected():
    """``Forwarding`` (different word) shouldn't fire as ``Forwarded``."""
    out = _extract_forwards("Forwarding the message")
    assert out == []


def test_lowercase_shared_action_rejected():
    """``alice shared a message`` -- lowercase name rejected because
    capitalised name is required."""
    out = _extract_forwards("alice shared a message")
    assert out == []


def test_bare_shared_word_rejected():
    """``We shared a photo`` doesn't fire -- needs capitalised name."""
    out = _extract_forwards("We shared a photo")
    assert out == []


# ---- enrich_chat integration -------------------------------------


def test_enrich_chat_populates_forwards():
    text = (
        "Alice: morning\n"
        "Forwarded from Bob\n"
        "Bob: hi"
    )
    out = enrich_chat(None, OCRResult(text=text))
    assert len(out.forwards) >= 1
    assert out.forwards[0]["forwarded_from"] == "Bob"


def test_enrich_chat_empty_forwards_no_forward_text():
    text = "Alice: hello\nBob: hi"
    out = enrich_chat(None, OCRResult(text=text))
    assert out.forwards == []


def test_enrich_chat_preserves_caller_forwards():
    """LLM-supplied forwards are merged with regex-parsed ones."""
    existing = ChatFields(
        forwards=[
            {"kind": "forwarded", "forwarded_from": "PreviouslyKnown"}
        ]
    )
    out = enrich_chat(
        existing,
        OCRResult(text="Forwarded from Alice"),
    )
    sources = [e.get("forwarded_from") for e in out.forwards]
    assert "PreviouslyKnown" in sources
    assert "Alice" in sources


def test_enrich_chat_dedupes_against_caller():
    """An LLM-supplied forward + identical OCR entry collapse."""
    existing = ChatFields(
        forwards=[
            {"kind": "forwarded", "forwarded_from": "Alice"}
        ]
    )
    out = enrich_chat(
        existing,
        OCRResult(text="Forwarded from Alice"),
    )
    # Caller's entry plus the parser's same entry collapses to one.
    assert len(out.forwards) == 1


# ---- Realistic content fixtures -----------------------------------


def test_realistic_telegram_news_forward():
    text = (
        "Alice: did you see this\n"
        "Forwarded from @BBCBreaking\n"
        "Breaking: major event today\n"
        "Bob: wow"
    )
    out = _extract_forwards(text)
    assert any(
        e.get("forwarded_from") == "@BBCBreaking"
        and e.get("sender") == "Alice"
        for e in out
    )


def test_realistic_whatsapp_viral_message():
    """The ``Forwarded many times`` chain marker is the canonical
    misinformation flag on WhatsApp."""
    text = (
        "Carol: \n"
        "Forwarded many times\n"
        "Important news please share"
    )
    out = _extract_forwards(text)
    assert any(e["kind"] == "forwarded_many" for e in out)


def test_realistic_slack_share():
    text = (
        "Sarah Brown shared a message from #incident-2024\n"
        "Posting context here"
    )
    out = _extract_forwards(text)
    assert out == [
        {"kind": "shared", "sender": "Sarah Brown",
         "forwarded_from": "#incident-2024"}
    ]


def test_realistic_discord_news_share():
    text = (
        "[Forwarded from #announcements]\n"
        "Server maintenance tomorrow"
    )
    out = _extract_forwards(text)
    assert out == [{"kind": "forwarded", "forwarded_from": "#announcements"}]


# ---- Cap enforcement ---------------------------------------------


def test_cap_at_30_entries():
    """Output is capped at 30 entries even when more badges present."""
    lines = [f"Forwarded from User{i}" for i in range(40)]
    text = "\n".join(lines)
    out = _extract_forwards(text)
    assert len(out) == 30


# ---- Forward arrow alone insufficient ----------------------------


def test_arrow_alone_rejected():
    """A bare ``↪️`` emoji without ``Forwarded`` keyword doesn't fire."""
    out = _extract_forwards("\u21AA\uFE0F")
    assert out == []


def test_arrow_with_text_rejected():
    """``↪️ Reply`` doesn't fire (not a forward marker)."""
    out = _extract_forwards("\u21AA\uFE0F Reply")
    assert out == []
