"""Chat link-preview / OG-card extraction tests.

ChatFields.link_previews surfaces the inline preview cards that
Slack / Discord / Teams / WhatsApp / Telegram render below shared
URLs. Each entry is a {sender, domain, title, description, url}
dict.
"""
from __future__ import annotations

from shotclassify_common import ChatFields, OCRResult
from shotclassify_extract.chat import _extract_link_previews, enrich_chat

# ---- Empty / no-preview cases ------------------------------------


def test_empty_text():
    assert _extract_link_previews("") == []


def test_none_text():
    assert _extract_link_previews(None) == []  # type: ignore[arg-type]


def test_plain_chat_no_preview():
    text = (
        "Alice: hey\n"
        "Bob: hi there\n"
        "Alice: how are you\n"
    )
    assert _extract_link_previews(text) == []


def test_url_but_no_preview_card():
    """A URL in a message body but no preview block below -- no entry."""
    text = "Alice: check out https://example.com"
    assert _extract_link_previews(text) == []


# ---- Basic preview detection ------------------------------------


def test_basic_preview_with_three_lines():
    text = (
        "Alice: check this https://example.com/article\n"
        "\n"
        "example.com\n"
        "How LLMs Are Changing Search\n"
        "A deep dive into the new search landscape.\n"
    )
    out = _extract_link_previews(text)
    assert len(out) == 1
    assert out[0]["domain"] == "example.com"
    assert out[0]["title"] == "How LLMs Are Changing Search"
    assert out[0]["description"] == "A deep dive into the new search landscape."
    assert out[0]["url"] == "https://example.com/article"
    assert out[0]["sender"] == "Alice"


def test_preview_with_no_description():
    text = (
        "Bob: github link https://github.com/openai/foo\n"
        "\n"
        "github.com\n"
        "openai/foo: An example repository\n"
    )
    out = _extract_link_previews(text)
    assert len(out) == 1
    assert out[0]["domain"] == "github.com"
    assert out[0]["description"] is None


def test_preview_with_www_prefix():
    text = (
        "Alice: shared this https://www.nytimes.com/2024/article\n"
        "\n"
        "www.nytimes.com\n"
        "AI Breakthrough Changes Everything\n"
        "The latest in AI research is here.\n"
    )
    out = _extract_link_previews(text)
    assert len(out) == 1
    assert out[0]["domain"] == "nytimes.com"  # www. stripped


def test_preview_with_uppercase_domain():
    text = (
        "Alice: shared\n"
        "\n"
        "EXAMPLE.COM\n"
        "How LLMs Are Changing Search\n"
        "Body text here.\n"
    )
    out = _extract_link_previews(text)
    assert len(out) == 1
    assert out[0]["domain"] == "example.com"  # lowercased


def test_preview_with_subdomain():
    text = (
        "Alice: shared https://docs.python.org/3/\n"
        "\n"
        "docs.python.org\n"
        "Python 3 Documentation Index\n"
        "Reference and tutorials.\n"
    )
    out = _extract_link_previews(text)
    assert len(out) == 1
    assert out[0]["domain"] == "docs.python.org"


# ---- Multiple previews -------------------------------------------


def test_multiple_previews():
    text = (
        "Alice: two links\n"
        "https://example.com/article\n"
        "\n"
        "example.com\n"
        "First Article Title Here\n"
        "First description here.\n"
        "\n"
        "github.com\n"
        "Second Repo Title Here\n"
        "Second description here.\n"
    )
    out = _extract_link_previews(text)
    assert len(out) == 2
    domains = [e["domain"] for e in out]
    assert "example.com" in domains
    assert "github.com" in domains


def test_chronological_order():
    text = (
        "first.com\n"
        "First Article Title Here\n"
        "Description one here.\n"
        "\n"
        "second.com\n"
        "Second Article Title Here\n"
        "Description two here.\n"
    )
    out = _extract_link_previews(text)
    assert len(out) == 2
    assert out[0]["domain"] == "first.com"
    assert out[1]["domain"] == "second.com"


# ---- Safety / false-positive defences ----------------------------


def test_email_address_rejected_as_header():
    """A line starting with @ is an email, not a preview header."""
    text = (
        "Alice: @bob check this\n"
        "@example.com\n"
        "Some title here today\n"
    )
    assert _extract_link_previews(text) == []


def test_file_path_rejected_as_header():
    """A line starting with / is a path, not a domain."""
    text = (
        "Alice: see /etc/hosts\n"
        "/usr/bin/python\n"
        "Some title text here\n"
    )
    assert _extract_link_previews(text) == []


def test_messaging_platform_domain_rejected():
    """slack.com / discord.com etc. are reject-listed."""
    text = (
        "slack.com\n"
        "Some Title Goes Here\n"
        "Some description text here.\n"
    )
    assert _extract_link_previews(text) == []


def test_telegram_t_me_rejected():
    text = (
        "t.me\n"
        "Some Title Goes Here\n"
        "Some description text here.\n"
    )
    assert _extract_link_previews(text) == []


def test_lone_domain_no_title_skipped():
    """A standalone domain without a title line below skips."""
    text = "example.com\n"
    assert _extract_link_previews(text) == []


def test_short_title_one_word_rejected():
    """Title must contain at least 3 words."""
    text = (
        "example.com\n"
        "Hi\n"
    )
    assert _extract_link_previews(text) == []


def test_short_title_two_words_rejected():
    text = (
        "example.com\n"
        "Brief Title\n"
    )
    assert _extract_link_previews(text) == []


def test_sender_line_not_preview_header():
    """A `Sender: text` line shouldn't be treated as preview header."""
    text = (
        "Alice: chat message\n"
        "Bob: another message\n"
    )
    assert _extract_link_previews(text) == []


def test_inline_url_in_body_not_preview():
    """A URL inside a message body line is NOT a preview."""
    text = (
        "Alice: visit https://example.com today\n"
        "Bob: ok will do\n"
    )
    assert _extract_link_previews(text) == []


# ---- Sender attribution ------------------------------------------


def test_sender_attribution_from_preceding_speaker():
    text = (
        "Alice: shared https://news.com/foo\n"
        "\n"
        "news.com\n"
        "Some Breaking News Article\n"
        "More details below now.\n"
    )
    out = _extract_link_previews(text)
    assert out[0]["sender"] == "Alice"


def test_sender_none_for_bare_preview():
    text = (
        "news.com\n"
        "Some Breaking News Article\n"
        "More details below here.\n"
    )
    out = _extract_link_previews(text)
    assert out[0]["sender"] is None


def test_sender_updates_with_new_speaker():
    text = (
        "Alice: shared first link\n"
        "\n"
        "first.com\n"
        "First Article Title Here\n"
        "First description here.\n"
        "\n"
        "Bob: shared second link\n"
        "\n"
        "second.com\n"
        "Second Article Title Here\n"
        "Second description here.\n"
    )
    out = _extract_link_previews(text)
    assert len(out) == 2
    assert out[0]["sender"] == "Alice"
    assert out[1]["sender"] == "Bob"


# ---- URL extraction ---------------------------------------------


def test_url_from_preceding_line():
    text = (
        "Alice: https://specific.example.com/path?q=1\n"
        "\n"
        "example.com\n"
        "Title With More Words\n"
        "Description text here please.\n"
    )
    out = _extract_link_previews(text)
    assert out[0]["url"] == "https://specific.example.com/path?q=1"


def test_url_trailing_punctuation_stripped():
    text = (
        "Alice: https://example.com/article.\n"
        "\n"
        "example.com\n"
        "Title With More Words\n"
        "Description here friend.\n"
    )
    out = _extract_link_previews(text)
    assert out[0]["url"] == "https://example.com/article"


def test_no_url_when_none_nearby():
    text = (
        "example.com\n"
        "Title With Many Words\n"
        "Body description text.\n"
    )
    out = _extract_link_previews(text)
    assert out[0]["url"] is None


# ---- Cap at 20 entries ------------------------------------------


def test_cap_at_20_entries():
    chunks = []
    for i in range(30):
        chunks.append(
            f"site{i}.com\nArticle Title Number {i} Here\nBody text for {i}.\n"
        )
    text = "\n".join(chunks)
    out = _extract_link_previews(text)
    assert len(out) <= 20


# ---- enrich_chat integration -------------------------------------


def test_enrich_chat_writes_link_previews():
    text = (
        "Alice: check this https://example.com/article\n"
        "\n"
        "example.com\n"
        "How LLMs Are Changing Search\n"
        "A deep dive into the new search.\n"
    )
    out = enrich_chat(None, OCRResult(text=text))
    assert len(out.link_previews) == 1
    assert out.link_previews[0]["domain"] == "example.com"


def test_enrich_chat_caller_preserved():
    """Caller-supplied link_previews preserved verbatim."""
    text = (
        "Alice: shared\n"
        "\n"
        "example.com\n"
        "Title From OCR Here Today\n"
        "OCR description here.\n"
    )
    existing = ChatFields(
        link_previews=[
            {
                "sender": "From LLM",
                "domain": "llm-source.com",
                "title": "LLM Source Title",
                "description": "From LLM",
                "url": "https://llm-source.com",
            }
        ]
    )
    out = enrich_chat(existing, OCRResult(text=text))
    # 1 from caller + 1 from OCR = 2 entries
    assert len(out.link_previews) == 2


def test_enrich_chat_dedup_on_domain_title():
    """Caller-supplied entry matching OCR-parsed entry collapses."""
    text = (
        "example.com\n"
        "Same Title For Dedup\n"
        "Body here please.\n"
    )
    existing = ChatFields(
        link_previews=[
            {
                "sender": None,
                "domain": "example.com",
                "title": "Same Title For Dedup",
                "description": "Llm desc",
                "url": "https://example.com",
            }
        ]
    )
    out = enrich_chat(existing, OCRResult(text=text))
    assert len(out.link_previews) == 1


# ---- Real-world captures ----------------------------------------


def test_real_world_slack_capture():
    text = """Alice  9:42 AM
shared a link: https://stackoverflow.com/questions/12345

stackoverflow.com
How do I X in Python 3.12?
This question covers a common Python issue.

Bob  9:43 AM
nice find
"""
    out = _extract_link_previews(text)
    assert len(out) == 1
    assert out[0]["domain"] == "stackoverflow.com"


def test_real_world_discord_capture():
    text = """OWNER 2024-01-15
Check out this article: https://blog.example.com/post-42

blog.example.com
Why X Matters in 2024
A comprehensive breakdown of the topic.

USER 2024-01-15
agreed!
"""
    out = _extract_link_previews(text)
    assert len(out) == 1
    assert out[0]["domain"] == "blog.example.com"


def test_real_world_twitter_x_link():
    text = """Alice: read this thread https://x.com/user/status/12345

x.com
Author (@user) on X
Long thread post body text continues.
"""
    out = _extract_link_previews(text)
    assert len(out) == 1
    assert out[0]["domain"] == "x.com"
