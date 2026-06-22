"""Chat replied-to / quoted-message detection (``ChatFields.quotes``).

The new ``ChatFields.quotes`` slot captures messages that show a
quoted parent above the reply body. Each entry is a ``{"sender",
"quoted_sender", "quoted_text", "reply_text"}`` dict.

Three recognised shapes:
  * Line-leading ``>`` quote runs (Slack / IRC / email / Discord).
  * ``Replying to <name>: <body>`` preambles
    (iMessage / WhatsApp / Telegram / Discord).
  * ``> Sender: text`` attribution-inside-quote form (Slack).
"""
from __future__ import annotations

from shotclassify_common import ChatFields, OCRResult
from shotclassify_extract import enrich_chat
from shotclassify_extract.chat import _extract_quotes

# ---- bare line-leading `>` quote shapes -------------------------


def test_bare_gt_quote_with_reply():
    text = "> Original message body\nhere is my reply"
    out = _extract_quotes(text)
    assert out == [{"quoted_text": "Original message body", "reply_text": "here is my reply"}]


def test_bare_gt_quote_multiline():
    """Consecutive ``>`` lines collapse into one quote block joined by \\n."""
    text = "> first line\n> second line\n> third line\nReply body"
    out = _extract_quotes(text)
    assert out == [
        {"quoted_text": "first line\nsecond line\nthird line", "reply_text": "Reply body"}
    ]


def test_bare_gt_quote_with_blank_line_terminator():
    """A blank ``>`` line ends the quoted block (Slack convention)."""
    text = "> quoted body\n>\nthe reply"
    out = _extract_quotes(text)
    assert out == [{"quoted_text": "quoted body", "reply_text": "the reply"}]


def test_bare_gt_quote_no_reply_body():
    """A ``>`` quote with no following body still surfaces as quote-only."""
    text = "> orphaned quoted text"
    out = _extract_quotes(text)
    assert out == [{"quoted_text": "orphaned quoted text", "reply_text": ""}]


def test_bare_gt_quote_with_indent():
    """Up to 4 leading spaces before ``>`` are accepted (Discord shape)."""
    text = "   > Indented quoted body\n   the reply"
    out = _extract_quotes(text)
    assert out == [{"quoted_text": "Indented quoted body", "reply_text": "the reply"}]


def test_bare_gt_with_blank_lines_before_reply():
    """Blank lines between the quote block and the reply are skipped."""
    text = "> quoted body\n\n\nthe reply"
    out = _extract_quotes(text)
    assert out == [{"quoted_text": "quoted body", "reply_text": "the reply"}]


# ---- `> Sender: text` Slack attribution form --------------------


def test_quoted_with_attribution_slack():
    text = "> Alice: original body\nthanks for that"
    out = _extract_quotes(text)
    assert out == [
        {
            "quoted_sender": "Alice",
            "quoted_text": "original body",
            "reply_text": "thanks for that",
        }
    ]


def test_quoted_with_attribution_multiword_name():
    text = "> Alice Smith: original body\nreply"
    out = _extract_quotes(text)
    assert out == [
        {
            "quoted_sender": "Alice Smith",
            "quoted_text": "original body",
            "reply_text": "reply",
        }
    ]


def test_quoted_with_attribution_dash_underscore():
    """Slack/Discord usernames can carry dashes or underscores."""
    text = "> alice_smith: original body\nreply body"
    out = _extract_quotes(text)
    # ``alice_smith`` is lowercase so the attribution-with-uppercase regex
    # rejects it; the whole inside-quote body is treated as quoted text.
    assert out == [
        {
            "quoted_text": "alice_smith: original body",
            "reply_text": "reply body",
        }
    ]


def test_quoted_with_attribution_dash():
    text = "> Alice-Smith: original\nreply"
    out = _extract_quotes(text)
    assert out == [
        {
            "quoted_sender": "Alice-Smith",
            "quoted_text": "original",
            "reply_text": "reply",
        }
    ]


# ---- Discord `> @user body` reply-mention form ------------------


def test_discord_reply_mention():
    text = "> @bob hey did you see this\nyes I did"
    out = _extract_quotes(text)
    assert out == [
        {
            "quoted_sender": "bob",
            "quoted_text": "hey did you see this",
            "reply_text": "yes I did",
        }
    ]


def test_discord_reply_mention_with_dots():
    text = "> @alice.smith look at this\nok"
    out = _extract_quotes(text)
    assert out == [
        {
            "quoted_sender": "alice.smith",
            "quoted_text": "look at this",
            "reply_text": "ok",
        }
    ]


# ---- `Replying to <name>:` preamble forms ----------------------


def test_replying_to_preamble_inline():
    text = "Replying to Alice: original body\nreply body"
    out = _extract_quotes(text)
    assert out == [
        {
            "quoted_sender": "Alice",
            "quoted_text": "original body",
            "reply_text": "reply body",
        }
    ]


def test_in_reply_to_preamble():
    text = "In reply to Bob: original body\nreply body"
    out = _extract_quotes(text)
    assert out == [
        {
            "quoted_sender": "Bob",
            "quoted_text": "original body",
            "reply_text": "reply body",
        }
    ]


def test_quoting_preamble():
    text = "Quoting Cara: parent body\nthe reply"
    out = _extract_quotes(text)
    assert out == [
        {
            "quoted_sender": "Cara",
            "quoted_text": "parent body",
            "reply_text": "the reply",
        }
    ]


def test_reply_to_preamble():
    text = "Reply to Dave: parent body\nthe reply"
    out = _extract_quotes(text)
    assert out == [
        {
            "quoted_sender": "Dave",
            "quoted_text": "parent body",
            "reply_text": "the reply",
        }
    ]


def test_replying_to_case_insensitive():
    text = "REPLYING TO BOB: parent\nreply"
    out = _extract_quotes(text)
    assert len(out) == 1
    assert out[0]["quoted_sender"] == "BOB"


def test_replying_to_empty_body_no_reply():
    """A ``Replying to X:`` line with no body and no follow-up is still kept."""
    text = "Replying to Alice:"
    out = _extract_quotes(text)
    assert out == [
        {"quoted_sender": "Alice", "quoted_text": "", "reply_text": ""}
    ]


def test_replying_to_empty_body_with_next_line():
    text = "Replying to Alice:\nthe reply body"
    out = _extract_quotes(text)
    assert out == [
        {
            "quoted_sender": "Alice",
            "quoted_text": "",
            "reply_text": "the reply body",
        }
    ]


# ---- sender (reply author) attribution -------------------------


def test_reply_sender_tracked_from_transcript():
    """When the reply lives inside a ``Sender: text`` transcript, the
    nearest preceding speaker becomes the reply author."""
    text = "Alice: hello\nBob: hi\n> Original from Alice\nBob: I agree"
    out = _extract_quotes(text)
    assert len(out) == 1
    assert out[0].get("sender") == "Bob"
    assert out[0]["quoted_text"] == "Original from Alice"
    assert out[0]["reply_text"] == "I agree"


def test_reply_sender_none_outside_transcript():
    """No surrounding ``Sender:`` lines -> sender absent (no key)."""
    text = "> Quoted body\nreply body"
    out = _extract_quotes(text)
    assert "sender" not in out[0]


# ---- multiple chains preserved in OCR order --------------------


def test_multiple_quote_chains():
    text = (
        "> Alice: first quoted\nfirst reply\n"
        "> Bob: second quoted\nsecond reply"
    )
    out = _extract_quotes(text)
    assert len(out) == 2
    assert out[0]["quoted_sender"] == "Alice"
    assert out[0]["reply_text"] == "first reply"
    assert out[1]["quoted_sender"] == "Bob"
    assert out[1]["reply_text"] == "second reply"


def test_replying_to_then_gt_chain():
    """A mixed-form transcript with both shapes preserves order."""
    text = (
        "Replying to Alice: original A\nreply A\n"
        "> original B\nreply B"
    )
    out = _extract_quotes(text)
    assert len(out) == 2
    assert out[0]["quoted_sender"] == "Alice"
    assert "quoted_sender" not in out[1]


# ---- false-positive defences -----------------------------------


def test_arrow_not_quote():
    """``->`` arrow is not a quote marker."""
    text = "result -> success\nnext line"
    out = _extract_quotes(text)
    assert out == []


def test_double_arrow_not_quote():
    """``=>`` JS arrow is not a quote marker."""
    text = "value => success\nnext"
    out = _extract_quotes(text)
    assert out == []


def test_html_close_tag_not_quote():
    """A ``</div>`` close tag containing ``>`` is not a quote marker."""
    text = "</div>\nnext line"
    out = _extract_quotes(text)
    assert out == []


def test_stray_gt_no_body():
    """A bare ``>`` with no body and no reply is not surfaced."""
    text = ">\nfoo\nbar"
    # The first line has no quoted body; we should NOT emit a quote
    # since there's no quoted text to surface.
    out = _extract_quotes(text)
    assert out == []


def test_empty_text():
    assert _extract_quotes("") == []
    assert _extract_quotes("plain text only") == []


def test_no_quote_no_match():
    text = "Alice: hello\nBob: hi there\nAlice: how are you"
    assert _extract_quotes(text) == []


# ---- cap enforcement -------------------------------------------


def test_quote_cap_at_20():
    lines = []
    for i in range(30):
        lines.append(f"> quoted {i}")
        lines.append(f"reply {i}")
    out = _extract_quotes("\n".join(lines))
    assert len(out) == 20
    assert out[0]["quoted_text"] == "quoted 0"
    assert out[19]["quoted_text"] == "quoted 19"


# ---- enrich_chat integration -----------------------------------


def test_enrich_chat_populates_quotes():
    text = (
        "Alice: hello\n"
        "Bob: hi\n"
        "> Alice: original\n"
        "Bob: thanks"
    )
    out = enrich_chat(None, OCRResult(text=text))
    assert len(out.quotes) == 1
    q = out.quotes[0]
    assert q["quoted_sender"] == "Alice"
    assert q["quoted_text"] == "original"
    assert q["reply_text"] == "thanks"
    assert q.get("sender") == "Bob"


def test_enrich_chat_preserves_caller_quotes():
    text = "> orig\nreply"
    existing = ChatFields(quotes=[{"quoted_text": "caller", "reply_text": "caller-reply"}])
    out = enrich_chat(existing, OCRResult(text=text))
    # Caller quote preserved first; OCR-parsed quote appended.
    assert len(out.quotes) == 2
    assert out.quotes[0]["quoted_text"] == "caller"
    assert out.quotes[1]["quoted_text"] == "orig"


def test_enrich_chat_dedupes_identical_quote():
    text = "> orig\nreply"
    # The same quote pre-supplied: should NOT duplicate.
    existing = ChatFields(quotes=[{"quoted_text": "orig", "reply_text": "reply"}])
    out = enrich_chat(existing, OCRResult(text=text))
    assert len(out.quotes) == 1
    assert out.quotes[0]["quoted_text"] == "orig"


def test_enrich_chat_no_quotes_means_empty_list():
    out = enrich_chat(None, OCRResult(text="Alice: hi\nBob: hello"))
    assert out.quotes == []


# ---- whitespace robustness -------------------------------------


def test_quote_body_strips_whitespace():
    text = ">    extra spaces here    \nreply"
    out = _extract_quotes(text)
    assert out[0]["quoted_text"] == "extra spaces here"


def test_quote_marker_with_tab():
    text = ">\toriginal\nreply"
    out = _extract_quotes(text)
    assert out == [{"quoted_text": "original", "reply_text": "reply"}]


def test_blank_line_between_quote_runs_terminates():
    """A blank line splits two `>` runs into separate quote blocks."""
    text = "> first quote\n\n> second quote\nreply body"
    out = _extract_quotes(text)
    # First quote becomes its own block with no reply (the blank
    # line + second `>` is a separator + new block).
    assert len(out) == 2
    assert out[0]["quoted_text"] == "first quote"
    assert out[0]["reply_text"] == ""
    assert out[1]["quoted_text"] == "second quote"
    assert out[1]["reply_text"] == "reply body"
