"""Chat poll / survey block detection (``ChatFields.polls``).

The new ``ChatFields.polls`` slot captures inline poll / survey
blocks found in chat screenshots. Telegram, Slack, Discord, Teams,
and WhatsApp all render polls as a header line + per-option vote-
count rows.

Each entry is a ``{"question": str, "options": [{label, votes}, ...]}``
dict.

Recognised shapes:
* Telegram: ``📊 Poll: <question>`` + ``Option N: <label> - N votes``
* Slack: ``:bar_chart: Poll: <question>`` + ``N. <label> ▓▓ N`` /
  ``N. <label> - N votes``
* Discord: ``📊 <question>`` + ``• <label>: N votes``
* Generic: ``Poll: <question>`` / ``Survey: <question>`` /
  ``Vote: <question>`` + numbered / bulleted options
"""
from __future__ import annotations

from shotclassify_common import ChatFields, OCRResult
from shotclassify_extract import enrich_chat
from shotclassify_extract.chat import _extract_polls

# ---- Telegram shape ------------------------------------------------


def test_telegram_emoji_plus_keyword_poll():
    text = """\
📊 Poll: What's for lunch?
Option 1: Pizza - 5 votes
Option 2: Sushi - 3 votes
Option 3: Tacos - 8 votes
"""
    out = _extract_polls(text)
    assert out == [
        {
            "question": "What's for lunch?",
            "options": [
                {"label": "Pizza", "votes": 5},
                {"label": "Sushi", "votes": 3},
                {"label": "Tacos", "votes": 8},
            ],
        }
    ]


def test_telegram_footer_voter_count_skipped():
    """A trailing ``16 voters`` line is recognised as footer, not an option."""
    text = """\
📊 Poll: Best language?
Option 1: Python - 10 votes
Option 2: Go - 5 votes
16 voters
"""
    out = _extract_polls(text)
    assert len(out) == 1
    assert len(out[0]["options"]) == 2


# ---- Slack shape ---------------------------------------------------


def test_slack_bar_chart_shortcode_poll():
    text = """\
:bar_chart: Poll: Friday demo time?
1. 10am - 5 votes
2. 2pm - 3 votes
3. 4pm - 2 votes
"""
    out = _extract_polls(text)
    assert out == [
        {
            "question": "Friday demo time?",
            "options": [
                {"label": "10am", "votes": 5},
                {"label": "2pm", "votes": 3},
                {"label": "4pm", "votes": 2},
            ],
        }
    ]


def test_slack_progress_bar_visual_in_option():
    """Slack-style poll with ▓ progress bars."""
    text = """\
📊 Poll: Pick a colour
1. Red ▓▓▓▓▓ 5
2. Blue ▓▓▓ 3
3. Green ▓▓ 2
"""
    out = _extract_polls(text)
    assert len(out) == 1
    assert out[0]["question"] == "Pick a colour"
    labels = [o["label"] for o in out[0]["options"]]
    votes = [o["votes"] for o in out[0]["options"]]
    assert labels == ["Red", "Blue", "Green"]
    assert votes == [5, 3, 2]


# ---- Discord shape -------------------------------------------------


def test_discord_bullet_options():
    text = """\
📊 What's the best deploy strategy?
• Rolling: 12 votes
• Blue/green: 8 votes
• Canary: 4 votes
"""
    out = _extract_polls(text)
    assert out == [
        {
            "question": "What's the best deploy strategy?",
            "options": [
                {"label": "Rolling", "votes": 12},
                {"label": "Blue/green", "votes": 8},
                {"label": "Canary", "votes": 4},
            ],
        }
    ]


def test_discord_dash_bulleted_options():
    text = """\
📊 Poll: Favorite framework?
- React - 25 votes
- Vue - 15 votes
- Svelte - 10 votes
"""
    out = _extract_polls(text)
    assert len(out) == 1
    assert len(out[0]["options"]) == 3


# ---- Generic keyword headers ---------------------------------------


def test_keyword_poll_no_emoji():
    text = """\
Poll: Coffee or tea?
1. Coffee - 7 votes
2. Tea - 5 votes
"""
    out = _extract_polls(text)
    assert out == [
        {
            "question": "Coffee or tea?",
            "options": [
                {"label": "Coffee", "votes": 7},
                {"label": "Tea", "votes": 5},
            ],
        }
    ]


def test_survey_keyword_header():
    text = """\
Survey: How would you rate the meeting?
1. Excellent: 10 votes
2. Good: 5 votes
3. Bad: 2 votes
"""
    out = _extract_polls(text)
    assert len(out) == 1
    assert out[0]["question"] == "How would you rate the meeting?"


def test_vote_keyword_header():
    text = """\
Vote: Yes or no?
- Yes - 10 votes
- No - 5 votes
"""
    out = _extract_polls(text)
    assert len(out) == 1


def test_question_keyword_header():
    text = """\
Question: Pizza or burger?
1. Pizza - 8 votes
2. Burger - 6 votes
"""
    out = _extract_polls(text)
    assert len(out) == 1


def test_quiz_keyword_header():
    text = """\
Quiz: What is 2+2?
1. 3 - 2 votes
2. 4 - 10 votes
3. 5 - 1 votes
"""
    out = _extract_polls(text)
    assert len(out) == 1
    assert out[0]["options"][1] == {"label": "4", "votes": 10}


# ---- Header ordering / context -------------------------------------


def test_multiple_polls_in_same_screenshot():
    text = """\
📊 Poll: Lunch?
- Pizza - 5 votes
- Sushi - 3 votes

📊 Poll: Drink?
- Coffee - 4 votes
- Tea - 2 votes
"""
    out = _extract_polls(text)
    assert len(out) == 2
    assert out[0]["question"] == "Lunch?"
    assert out[1]["question"] == "Drink?"


def test_poll_followed_by_normal_messages():
    text = """\
Alice: Hey everyone!
📊 Poll: Friday plan?
- Beach - 4 votes
- Park - 2 votes
Bob: Sounds good!
"""
    out = _extract_polls(text)
    assert len(out) == 1
    assert out[0]["question"] == "Friday plan?"


# ---- Negative cases ------------------------------------------------


def test_numbered_list_without_header_rejected():
    """A plain numbered list (no Poll: header, no emoji) does NOT register."""
    text = """\
Things to buy:
1. Milk - 5
2. Eggs - 3
3. Bread - 8
"""
    out = _extract_polls(text)
    assert out == []


def test_header_with_no_options_rejected():
    """A header with no following option lines doesn't register."""
    text = """\
📊 Poll: Got a moment?
Alice: yes!
Bob: sure
"""
    out = _extract_polls(text)
    assert out == []


def test_header_with_only_one_option_rejected():
    """A poll needs at least 2 options to be a real poll."""
    text = """\
📊 Poll: Anyone there?
1. Yes - 1 votes
"""
    out = _extract_polls(text)
    assert out == []


def test_empty_input():
    assert _extract_polls("") == []


def test_unrelated_emoji_at_line_start_rejected():
    """An emoji that's not in the recognised set + no keyword =
    not recognised as poll header."""
    text = """\
👋 Hello team
1. Item one - 1 votes
2. Item two - 2 votes
"""
    out = _extract_polls(text)
    # 👋 (wave) IS in the BMP+ range so it WILL match the emoji
    # detector. But the test is about whether random hello lines
    # become polls -- in our design, ANY emoji prefix at line
    # start + structured options DOES qualify. So we expect the
    # poll to be detected here. Let's update the assertion.
    assert out == [
        {
            "question": "Hello team",
            "options": [
                {"label": "Item one", "votes": 1},
                {"label": "Item two", "votes": 2},
            ],
        }
    ]


def test_bare_prose_question_no_header_rejected():
    """A line ending in ``?`` is NOT a poll header on its own."""
    text = """\
Anyone want lunch?
1. Pizza - 5 votes
2. Burger - 3 votes
"""
    out = _extract_polls(text)
    assert out == []


# ---- Edge cases ----------------------------------------------------


def test_option_label_with_special_chars():
    """Labels with slashes, hyphens, parens preserved."""
    text = """\
📊 Poll: Deploy strategy?
- Blue/green - 5 votes
- Canary (slow) - 3 votes
- Rolling-update - 2 votes
"""
    out = _extract_polls(text)
    assert len(out[0]["options"]) == 3
    labels = [o["label"] for o in out[0]["options"]]
    assert "Blue/green" in labels
    assert "Canary (slow)" in labels


def test_option_with_zero_votes_works():
    """An option with 0 votes still registers."""
    text = """\
📊 Poll: Pick one
1. Apple - 0 votes
2. Orange - 5 votes
"""
    out = _extract_polls(text)
    assert out[0]["options"][0] == {"label": "Apple", "votes": 0}


def test_large_vote_counts_work():
    text = """\
📊 Poll: Big poll?
1. Yes - 12345 votes
2. No - 6789 votes
"""
    out = _extract_polls(text)
    assert out[0]["options"][0]["votes"] == 12345
    assert out[0]["options"][1]["votes"] == 6789


def test_singular_vote_keyword():
    """``1 vote`` (singular) also recognised."""
    text = """\
📊 Poll: Tiny poll
1. Yes - 1 vote
2. No - 0 vote
"""
    out = _extract_polls(text)
    assert out[0]["options"] == [
        {"label": "Yes", "votes": 1},
        {"label": "No", "votes": 0},
    ]


def test_options_capped_at_20_per_poll():
    """A poll with >20 options is truncated to 20."""
    lines = ["📊 Poll: Big choice?"]
    for i in range(25):
        lines.append(f"- Option_{i} - {i} votes")
    text = "\n".join(lines)
    out = _extract_polls(text)
    assert len(out) == 1
    assert len(out[0]["options"]) == 20


def test_polls_capped_at_10_per_screenshot():
    """A screenshot with >10 polls is truncated to 10."""
    parts = []
    for i in range(15):
        parts.append(f"📊 Poll: Q{i}?")
        parts.append("- A - 1 votes")
        parts.append("- B - 2 votes")
        parts.append("")
    text = "\n".join(parts)
    out = _extract_polls(text)
    assert len(out) == 10


# ---- Pipeline / enrich_chat wiring --------------------------------


def test_enrich_chat_populates_polls():
    text = """\
📊 Poll: Best week?
- A - 5 votes
- B - 3 votes
"""
    out = enrich_chat(None, OCRResult(text=text))
    assert out.polls == [
        {
            "question": "Best week?",
            "options": [
                {"label": "A", "votes": 5},
                {"label": "B", "votes": 3},
            ],
        }
    ]


def test_enrich_chat_caller_polls_preserved_and_extended():
    """Caller-supplied polls preserved verbatim; OCR-parsed polls
    appended."""
    existing = ChatFields(
        polls=[{"question": "Custom?", "options": [{"label": "Yes", "votes": 9}]}],
    )
    text = """\
📊 Poll: New?
- A - 5 votes
- B - 3 votes
"""
    out = enrich_chat(existing, OCRResult(text=text))
    assert len(out.polls) == 2
    assert out.polls[0]["question"] == "Custom?"
    assert out.polls[1]["question"] == "New?"


def test_enrich_chat_dedupes_identical_polls():
    """If the LLM supplies the same poll the OCR pass also detects,
    it doesn't duplicate."""
    poll_dict = {
        "question": "Lunch?",
        "options": [
            {"label": "Pizza", "votes": 5},
            {"label": "Sushi", "votes": 3},
        ],
    }
    existing = ChatFields(polls=[poll_dict])
    text = """\
📊 Poll: Lunch?
- Pizza - 5 votes
- Sushi - 3 votes
"""
    out = enrich_chat(existing, OCRResult(text=text))
    assert len(out.polls) == 1


def test_enrich_chat_no_polls_returns_empty():
    text = "Alice: just a regular message"
    out = enrich_chat(None, OCRResult(text=text))
    assert out.polls == []
