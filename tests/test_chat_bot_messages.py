"""Chat bot / app / integration message detection tests.

A new ChatFields.bot_messages slot captures messages from bots /
apps / integrations distinguishable by the platform's APP / BOT /
INTEGRATION badge next to the sender name.

Each entry is a ``{"sender", "badge", "platform", "text"}`` dict.
"""
from __future__ import annotations

from shotclassify_common import ChatFields, OCRResult
from shotclassify_extract.chat import _extract_bot_messages, enrich_chat

# ---- Empty / no-bot cases ----------------------------------------


def test_empty_text():
    assert _extract_bot_messages("") == []


def test_none_text():
    assert _extract_bot_messages(None) == []  # type: ignore[arg-type]


def test_human_chat_no_bots():
    text = "Alice: hey\nBob: hi\nAlice: how's it going?"
    assert _extract_bot_messages(text) == []


def test_plain_prose_no_bots():
    text = "Just some prose with no badges anywhere"
    assert _extract_bot_messages(text) == []


# ---- Slack APP badge detection -----------------------------------


def test_slack_github_app():
    text = "GitHub APP 9:32 AM\nPull request opened by sanjay"
    out = _extract_bot_messages(text)
    assert len(out) == 1
    assert out[0]["sender"] == "GitHub"
    assert out[0]["badge"] == "app"
    assert out[0]["platform"] == "slack"
    assert out[0]["text"] == "Pull request opened by sanjay"


def test_slack_circleci_app():
    text = "CircleCI APP 12:14 PM\nBuild #1234 passed."
    out = _extract_bot_messages(text)
    assert len(out) == 1
    assert out[0]["sender"] == "CircleCI"
    assert out[0]["badge"] == "app"
    assert out[0]["platform"] == "slack"


def test_slack_datadog_bot():
    text = "Datadog BOT 11:45 AM\nHigh memory usage on prod-1"
    out = _extract_bot_messages(text)
    assert len(out) == 1
    assert out[0]["sender"] == "Datadog"
    assert out[0]["badge"] == "bot"
    assert out[0]["platform"] == "slack"


def test_slack_integration():
    text = "PagerDuty INTEGRATION 11:30 AM\nIncident #123 triggered"
    out = _extract_bot_messages(text)
    assert len(out) == 1
    assert out[0]["sender"] == "PagerDuty"
    assert out[0]["badge"] == "integration"


def test_slack_multiple_apps():
    text = (
        "GitHub APP 9:32 AM\n"
        "PR opened\n"
        "CircleCI APP 9:45 AM\n"
        "Build passed\n"
    )
    out = _extract_bot_messages(text)
    assert len(out) == 2
    senders = [e["sender"] for e in out]
    assert "GitHub" in senders
    assert "CircleCI" in senders


# ---- Discord BOT badge detection ---------------------------------


def test_discord_mee6_bot():
    text = "MEE6 BOT — Today at 3:14 PM\nWelcome to the server!"
    out = _extract_bot_messages(text)
    assert len(out) == 1
    assert out[0]["sender"] == "MEE6"
    assert out[0]["badge"] == "bot"
    assert out[0]["platform"] == "discord"
    assert out[0]["text"] == "Welcome to the server!"


def test_discord_carl_bot():
    text = "Carl-bot BOT — Yesterday at 14:25\nServer rules updated"
    out = _extract_bot_messages(text)
    assert len(out) == 1
    assert out[0]["sender"] == "Carl-bot"
    assert out[0]["platform"] == "discord"


def test_discord_dot_in_name():
    text = "YAGPDB.xyz BOT — 2024-06-15 10:30\nAuto-mod ran"
    out = _extract_bot_messages(text)
    assert len(out) == 1
    assert out[0]["sender"] == "YAGPDB.xyz"


# ---- Telegram bot suffix detection -------------------------------


def test_telegram_examplebot():
    text = "ExampleBot - bot\nLatest deals"
    out = _extract_bot_messages(text)
    assert len(out) == 1
    assert out[0]["sender"] == "ExampleBot"
    assert out[0]["badge"] == "bot"
    assert out[0]["platform"] == "telegram"


def test_telegram_channel_bot():
    text = "ChannelBot - bot\nAuto-pin message"
    out = _extract_bot_messages(text)
    assert len(out) == 1
    assert out[0]["sender"] == "ChannelBot"
    assert out[0]["platform"] == "telegram"


def test_telegram_dealsbot():
    text = "DealsBot - bot\nNew deal!"
    out = _extract_bot_messages(text)
    assert len(out) == 1
    assert out[0]["sender"] == "DealsBot"


# ---- Teams (Bot) (App) detection ---------------------------------


def test_teams_pagerduty_bot():
    text = "PagerDuty (Bot) 11:42 AM\nIncident triggered"
    out = _extract_bot_messages(text)
    assert len(out) == 1
    assert out[0]["sender"] == "PagerDuty"
    assert out[0]["badge"] == "bot"
    assert out[0]["platform"] == "teams"


def test_teams_github_app():
    text = "GitHub (App) 14:30\nPR #5 merged"
    out = _extract_bot_messages(text)
    assert len(out) == 1
    assert out[0]["sender"] == "GitHub"
    assert out[0]["badge"] == "app"
    assert out[0]["platform"] == "teams"


def test_teams_integration():
    text = "Jira (Integration) 09:00\nIssue PROJ-123 created"
    out = _extract_bot_messages(text)
    assert len(out) == 1
    assert out[0]["sender"] == "Jira"
    assert out[0]["badge"] == "integration"
    assert out[0]["platform"] == "teams"


# ---- Sender name safety ------------------------------------------


def test_channel_header_rejected():
    text = "CHANNEL APP 9:30 AM\nshouldn't match"
    out = _extract_bot_messages(text)
    # CHANNEL is in the reject set so this should not produce
    # a bot message entry.
    assert out == []


def test_workflow_header_rejected():
    text = "WORKFLOW APP something"
    out = _extract_bot_messages(text)
    assert out == []


def test_short_sender_rejected():
    text = "A APP body"
    out = _extract_bot_messages(text)
    # Single-char sender too short.
    assert out == []


def test_dashed_sender_accepted():
    text = "Multi-Word-Bot BOT 10:00 AM\nSomething"
    out = _extract_bot_messages(text)
    # Limited to 32 chars and matches regex pattern.
    assert len(out) == 1


# ---- Text body extraction ----------------------------------------


def test_text_body_extracted():
    text = "GitHub APP 9:30 AM\nPR #123 opened by sanjay"
    out = _extract_bot_messages(text)
    assert out[0]["text"] == "PR #123 opened by sanjay"


def test_text_body_skips_bracketed():
    # The body extractor skips leading "[" / "(" so OCR
    # metadata like "[Image]" isn't treated as message body.
    text = "GitHub APP 9:30 AM\n[Date]\nActual message body"
    out = _extract_bot_messages(text)
    # Body should be None because the next line starts with [.
    assert out[0]["text"] is None


def test_text_body_long_truncated():
    text = "GitHub APP 9:30 AM\n" + ("x" * 300)
    out = _extract_bot_messages(text)
    # Long line >200 chars -> None.
    assert out[0]["text"] is None


def test_no_text_body_after_match():
    text = "GitHub APP 9:30 AM"
    out = _extract_bot_messages(text)
    assert out[0]["text"] is None


# ---- Multiple bots in one screenshot -----------------------------


def test_three_bot_messages_in_screenshot():
    text = (
        "GitHub APP 9:30 AM\n"
        "PR opened\n"
        "MEE6 BOT — 9:35 AM\n"
        "Welcome\n"
        "Datadog BOT 9:40 AM\n"
        "Alert fired\n"
    )
    out = _extract_bot_messages(text)
    assert len(out) == 3
    badges = [e["badge"] for e in out]
    assert "app" in badges
    assert badges.count("bot") == 2


def test_mixed_human_and_bot_messages():
    text = (
        "Alice: hey team\n"
        "GitHub APP 9:30 AM\n"
        "PR #5 opened\n"
        "Bob: nice\n"
        "CircleCI APP 9:45 AM\n"
        "Build passed\n"
    )
    out = _extract_bot_messages(text)
    # Only bot messages, not Alice / Bob.
    assert len(out) == 2
    senders = [e["sender"] for e in out]
    assert "GitHub" in senders
    assert "CircleCI" in senders
    assert "Alice" not in senders
    assert "Bob" not in senders


# ---- Cap enforcement ---------------------------------------------


def test_cap_at_30_entries():
    # 35 bot messages, expect 30 to be retained.
    lines = []
    for i in range(35):
        lines.append(f"Bot{i} APP {i}:00 AM")
        lines.append(f"Body {i}")
    text = "\n".join(lines)
    out = _extract_bot_messages(text)
    assert len(out) == 30


# ---- Dedupe behaviour --------------------------------------------


def test_duplicate_lines_in_text_dedupe():
    text = (
        "GitHub APP 9:30 AM\n"
        "PR opened\n"
        "GitHub APP 9:30 AM\n"
        "PR opened\n"
    )
    out = _extract_bot_messages(text)
    # Same (sender, badge, text) -> the extractor itself does NOT
    # dedupe within a single call, but enrich_chat does. Here we
    # expect both to be returned by _extract_bot_messages.
    assert len(out) == 2


# ---- enrich_chat integration -------------------------------------


def test_enrich_chat_populates_bot_messages():
    text = "GitHub APP 9:30 AM\nPR opened\n"
    out = enrich_chat(None, OCRResult(text=text))
    assert len(out.bot_messages) == 1
    assert out.bot_messages[0]["sender"] == "GitHub"


def test_enrich_chat_no_bots_empty_list():
    text = "Alice: hey\nBob: hi"
    out = enrich_chat(None, OCRResult(text=text))
    assert out.bot_messages == []


def test_enrich_chat_caller_bots_preserved():
    caller = ChatFields(
        bot_messages=[
            {
                "sender": "CustomBot",
                "badge": "bot",
                "platform": "custom",
                "text": "Hello",
            }
        ]
    )
    text = "GitHub APP 9:30 AM\nPR opened\n"
    out = enrich_chat(caller, OCRResult(text=text))
    # Both caller's and OCR-discovered entries present.
    assert len(out.bot_messages) == 2
    senders = [e["sender"] for e in out.bot_messages]
    assert "CustomBot" in senders
    assert "GitHub" in senders


def test_enrich_chat_dedupes_bot_messages():
    # Caller and OCR both have the same bot message -> single
    # entry in the final list.
    caller = ChatFields(
        bot_messages=[
            {
                "sender": "GitHub",
                "badge": "app",
                "platform": "slack",
                "text": "PR opened",
            }
        ]
    )
    text = "GitHub APP 9:30 AM\nPR opened\n"
    out = enrich_chat(caller, OCRResult(text=text))
    assert len(out.bot_messages) == 1


# ---- Platform inference ------------------------------------------


def test_platform_slack_inferred_from_uppercase_badge():
    text = "Foo APP 9:30 AM\nBody"
    out = _extract_bot_messages(text)
    assert out[0]["platform"] == "slack"


def test_platform_discord_from_em_dash():
    text = "Foo BOT — Today\nBody"
    out = _extract_bot_messages(text)
    assert out[0]["platform"] == "discord"


def test_platform_teams_from_parens():
    text = "Foo (Bot) 9:30 AM\nBody"
    out = _extract_bot_messages(text)
    assert out[0]["platform"] == "teams"


def test_platform_telegram_from_bot_suffix():
    text = "FooBot - bot\nBody"
    out = _extract_bot_messages(text)
    assert out[0]["platform"] == "telegram"


# ---- Realistic screenshot scenarios ------------------------------


def test_realistic_slack_alerts_channel():
    text = """\
#alerts

PagerDuty INTEGRATION 11:30 AM
[Critical] API latency above 500ms

Datadog APP 11:31 AM
Alert: db-primary CPU 95%

CircleCI APP 11:35 AM
Build #4521 failed on main

GitHub APP 11:40 AM
PR #523 opened by alice
"""
    out = _extract_bot_messages(text)
    # Four bot messages.
    assert len(out) == 4
    badges = sorted(e["badge"] for e in out)
    assert "app" in badges
    assert "integration" in badges


def test_realistic_discord_mod_channel():
    text = """\
#general

MEE6 BOT — Today at 2:15 PM
Welcome @newuser to the server! Read the rules.

Dyno BOT — Today at 2:30 PM
@spammer has been muted.

Carl-bot BOT — Today at 3:00 PM
Server now has 1500 members!
"""
    out = _extract_bot_messages(text)
    assert len(out) == 3
    senders = sorted(e["sender"] for e in out)
    assert "Carl-bot" in senders
    assert "Dyno" in senders
    assert "MEE6" in senders
    assert all(e["platform"] == "discord" for e in out)


def test_priority_discord_over_slack_for_dash_form():
    # When a line carries both Slack-shape (NAME BOT) and Discord-
    # shape (NAME BOT —), Discord wins because it's checked first
    # in the matcher catalogue (more specific pattern).
    text = "GitHub BOT — Today at 9:30 PM\nPR opened"
    out = _extract_bot_messages(text)
    assert len(out) == 1
    # Discord match wins; platform is 'discord'.
    assert out[0]["platform"] == "discord"
    assert out[0]["badge"] == "bot"
