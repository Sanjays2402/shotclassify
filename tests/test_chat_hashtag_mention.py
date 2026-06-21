"""Tests for ChatFields.hashtags + mentions extraction.

The new fields capture every ``#tag`` and ``@user`` found in the
chat screenshot's OCR text, de-duped while preserving first-seen
order, capped at 50 each. Hashtags keep case (because case carries
meaning on most platforms — ``#OpenAI`` vs ``#openai``); mentions
are de-duped case-insensitively because Twitter / Slack treat
``@Sanjay`` and ``@sanjay`` as the same handle.

Email addresses must NOT produce a phantom mention (``foo@bar.com``
does not yield ``@bar``), and pure-digit hashtags must NOT be
captured (``#123`` is almost always an issue / list ref in a
screenshot, not a hashtag).
"""
from __future__ import annotations

from shotclassify_common import ChatFields, OCRResult
from shotclassify_extract import enrich_chat


def test_hashtag_basic():
    ocr = OCRResult(
        text="Alice: shipping #autoship today\n#launch goes Friday\n",
        word_count=8,
    )
    out = enrich_chat(None, ocr)
    assert out.hashtags == ["#autoship", "#launch"]


def test_hashtag_preserves_case():
    ocr = OCRResult(
        text="#OpenAI and #openai are different on most platforms\n",
        word_count=8,
    )
    out = enrich_chat(None, ocr)
    assert out.hashtags == ["#OpenAI", "#openai"]


def test_hashtag_rejects_pure_digits():
    """#123 is almost always an issue ref in screenshots, not a tag."""
    ocr = OCRResult(
        text="see #123 and #v2 and #2026wrap\n", word_count=6
    )
    out = enrich_chat(None, ocr)
    # #v2 and #2026wrap start with a letter so they win; #123 is rejected.
    assert "#123" not in out.hashtags
    assert "#v2" in out.hashtags


def test_hashtag_ignored_inside_url_fragment():
    """A URL fragment like ``https://x/y#frag`` must not yield ``#frag``."""
    ocr = OCRResult(text="docs at https://example.com/path#frag now\n", word_count=4)
    out = enrich_chat(None, ocr)
    assert out.hashtags == []


def test_mention_basic():
    ocr = OCRResult(
        text="Alice: hey @Bob can you review @Cara's PR?\n",
        word_count=8,
    )
    out = enrich_chat(None, ocr)
    assert out.mentions == ["@Bob", "@Cara"]


def test_mention_does_not_capture_email_local_part():
    """``foo@bar.com`` is an email; we must NOT produce ``@bar``."""
    ocr = OCRResult(
        text="Reach me at foo@bar.com or ping @sanjay\n", word_count=6
    )
    out = enrich_chat(None, ocr)
    assert out.mentions == ["@sanjay"]


def test_mention_case_insensitive_dedup():
    """Slack/Twitter treat @Sanjay and @sanjay as the same handle."""
    ocr = OCRResult(
        text="cc @Sanjay\nAlso @sanjay please\n", word_count=4
    )
    out = enrich_chat(None, ocr)
    # First occurrence wins (case preserved).
    assert out.mentions == ["@Sanjay"]


def test_channel_mentions_captured_with_prefix():
    """@channel / @here / @everyone surface with the prefix intact."""
    ocr = OCRResult(
        text="@channel ship it. @here who is on call? @everyone party\n",
        word_count=10,
    )
    out = enrich_chat(None, ocr)
    assert "@channel" in out.mentions
    assert "@here" in out.mentions
    assert "@everyone" in out.mentions


def test_mention_trims_trailing_punctuation():
    """Sentence punctuation drags along; we trim trailing dot / dash / underscore."""
    ocr = OCRResult(text="Hey @alice.\nAnd @bob,\n", word_count=4)
    out = enrich_chat(None, ocr)
    assert "@alice" in out.mentions
    assert "@bob" in out.mentions  # the comma is part of the surface text but the regex stops before it


def test_caller_supplied_tags_preserved_and_unioned_with_parsed():
    """LLM gave us some tags; OCR found more. Result is the union, caller-first."""
    existing = ChatFields(hashtags=["#caller"], mentions=["@caller"])
    ocr = OCRResult(
        text="Alice: #autoship and @bob and #caller again\n", word_count=8
    )
    out = enrich_chat(existing, ocr)
    assert out.hashtags == ["#caller", "#autoship"]
    assert out.mentions == ["@caller", "@bob"]


def test_no_tags_or_mentions_returns_empty_lists():
    ocr = OCRResult(text="just normal words here\n", word_count=4)
    out = enrich_chat(None, ocr)
    assert out.hashtags == []
    assert out.mentions == []


def test_full_chat_with_timestamp_tags_and_mentions():
    """All chat enrichment paths cooperate cleanly."""
    text = (
        "Alice: 12:34 PM hi @bob about #autoship\n"
        "Bob:   12:35 PM @alice cool, also cc @cara on #launch\n"
    )
    out = enrich_chat(None, OCRResult(text=text, word_count=15))
    assert out.messages[0]["time"] == "12:34"
    assert out.messages[1]["time"] == "12:35"
    assert out.hashtags == ["#autoship", "#launch"]
    # Case-insensitive dedup, first-seen-wins.
    lowered = [m.lower() for m in out.mentions]
    assert "@bob" in lowered
    assert "@alice" in lowered
    assert "@cara" in lowered


def test_hashtag_and_mention_caps_at_50():
    """Pathological input cannot balloon the lists past 50 each."""
    tags = " ".join(f"#tag{i}" for i in range(120))
    ments = " ".join(f"@user{i}" for i in range(120))
    ocr = OCRResult(text=f"Header: {tags}\nFooter: {ments}\n", word_count=240)
    out = enrich_chat(None, ocr)
    assert len(out.hashtags) == 50
    assert len(out.mentions) == 50
