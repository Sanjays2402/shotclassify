"""Cross-category Discord snowflake ID extractor tests.

A new cross-category extractor surfaces Discord IDs (user / channel /
role / guild / message / webhook / raw) found in the OCR text under
``ExtractedFields.raw["discord_ids"]``.

Output shape: list of ``{"kind", "id"}`` dicts.

Recognised forms:

* ``<@id>``   -- user mention
* ``<@!id>``  -- legacy nickname mention (also tagged as ``user``)
* ``<#id>``   -- channel mention
* ``<@&id>``  -- role mention
* ``discord.com/channels/G/C/M`` -- jump URL (guild + channel + msg)
* ``discord.com/api/webhooks/<ID>/<TOKEN>`` -- webhook URL (ID only;
  TOKEN NEVER captured)
* bare 17..19 digit snowflake with a Discord-context anchor on the
  same or previous line.

Output preserves first-seen order, dedupes on ``id`` value
(first-seen kind wins), capped at 50.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_discord_ids

# ---- Typed mentions ---------------------------------------------


def test_user_mention():
    out = extract_discord_ids("Hi <@123456789012345678>!")
    assert out == [{"kind": "user", "id": "123456789012345678"}]


def test_user_legacy_nick_mention():
    # <@!id> is the legacy nickname-mention form -- same user, we
    # tag as ``user`` for consistency.
    out = extract_discord_ids("Hi <@!123456789012345678>!")
    assert out == [{"kind": "user", "id": "123456789012345678"}]


def test_channel_mention():
    out = extract_discord_ids("Post in <#987654321098765432>")
    assert out == [{"kind": "channel", "id": "987654321098765432"}]


def test_role_mention():
    out = extract_discord_ids("Hey <@&111222333444555666>")
    assert out == [{"kind": "role", "id": "111222333444555666"}]


# ---- Jump URLs --------------------------------------------------


def test_jump_url():
    out = extract_discord_ids(
        "Check https://discord.com/channels/"
        "111222333444555666/777888999000111222/333444555666777888"
    )
    assert len(out) == 3
    assert out[0] == {"kind": "guild", "id": "111222333444555666"}
    assert out[1] == {"kind": "channel", "id": "777888999000111222"}
    assert out[2] == {"kind": "message", "id": "333444555666777888"}


def test_jump_url_legacy_discordapp_domain():
    out = extract_discord_ids(
        "Check https://discordapp.com/channels/"
        "111222333444555666/777888999000111222/333444555666777888"
    )
    assert len(out) == 3
    assert {x["kind"] for x in out} == {"guild", "channel", "message"}


def test_jump_url_no_scheme():
    out = extract_discord_ids(
        "discord.com/channels/111222333444555666/777888999000111222/333444555666777888"
    )
    assert len(out) == 3


# ---- Webhook URLs -----------------------------------------------


def test_webhook_url_captures_id_only():
    text = (
        "Webhook: https://discord.com/api/webhooks/"
        "123456789012345678/super-secret-token-abc-DEF-12345"
    )
    out = extract_discord_ids(text)
    assert out == [{"kind": "webhook", "id": "123456789012345678"}]


def test_webhook_token_never_in_output():
    text = (
        "Webhook: https://discord.com/api/webhooks/"
        "123456789012345678/MyVerySecretWebhookToken_ABC123"
    )
    out = extract_discord_ids(text)
    # The token must NEVER appear in any field of the output.
    for entry in out:
        for value in entry.values():
            assert "MyVerySecretWebhookToken" not in value
            assert "ABC123" not in value


# ---- Bare snowflake with context anchor ----------------------


def test_bare_snowflake_with_context_anchor_same_line():
    out = extract_discord_ids("discord user_id: 123456789012345678")
    assert len(out) == 1
    assert out[0] == {"kind": "raw", "id": "123456789012345678"}


def test_bare_snowflake_with_context_anchor_prev_line():
    text = "Discord snowflake:\n123456789012345678"
    out = extract_discord_ids(text)
    assert len(out) == 1
    assert out[0] == {"kind": "raw", "id": "123456789012345678"}


def test_bare_snowflake_without_context_rejected():
    # 17..19 decimal digits are too common; without a Discord
    # anchor we must NOT misfire.
    out = extract_discord_ids("Just a number 123456789012345678 here.")
    assert out == []


def test_bare_snowflake_python_sdk_context():
    out = extract_discord_ids(
        "import discord.py\nuser = 123456789012345678"
    )
    assert len(out) == 1
    assert out[0]["id"] == "123456789012345678"


# ---- Dedupe across forms (first-seen kind wins) --------------


def test_dedupe_user_mention_then_jump_url():
    # Same user ID appears as a mention then as a jump-URL guild.
    # We dedupe on id and the first-seen kind (``user``) wins.
    text = (
        "<@111222333444555666>\n"
        "https://discord.com/channels/111222333444555666/"
        "777888999000111222/333444555666777888"
    )
    out = extract_discord_ids(text)
    # Two unique IDs: the first one is the user mention, then the
    # jump URL adds channel + message (because guild dupes the user).
    assert len(out) == 3
    assert out[0] == {"kind": "user", "id": "111222333444555666"}
    assert {x["kind"] for x in out} == {"user", "channel", "message"}


def test_dedupe_same_user_twice():
    out = extract_discord_ids(
        "<@123456789012345678> and again <@123456789012345678>"
    )
    assert out == [{"kind": "user", "id": "123456789012345678"}]


# ---- Snowflake length bounds -----------------------------------


def test_17_digit_snowflake_accepted():
    # 17-digit snowflakes are the earliest issued IDs.
    out = extract_discord_ids("<@12345678901234567>")
    assert out == [{"kind": "user", "id": "12345678901234567"}]


def test_19_digit_snowflake_accepted():
    out = extract_discord_ids("<@1234567890123456789>")
    assert out == [{"kind": "user", "id": "1234567890123456789"}]


def test_16_digit_rejected():
    out = extract_discord_ids("<@1234567890123456>")
    assert out == []


def test_20_digit_rejected():
    out = extract_discord_ids("<@12345678901234567890>")
    assert out == []


# ---- Multiple mentions and ordering ---------------------------


def test_preserves_first_seen_order():
    text = (
        "First: <@111222333444555666>\n"
        "Second: <#777888999000111222>\n"
        "Third: <@&333444555666777888>\n"
    )
    out = extract_discord_ids(text)
    # All three pass 1 matchers (mentions) -- they're added in
    # pass-1 order: user, channel, role.
    assert out == [
        {"kind": "user", "id": "111222333444555666"},
        {"kind": "channel", "id": "777888999000111222"},
        {"kind": "role", "id": "333444555666777888"},
    ]


def test_multiple_users_in_one_message():
    text = (
        "<@111222333444555666> and <@777888999000111222> "
        "discussing in <#333444555666777888>"
    )
    out = extract_discord_ids(text)
    assert {x["kind"] for x in out} == {"user", "channel"}
    assert len(out) == 3


def test_cap_at_50():
    # Build 60 distinct user mentions.
    text = " ".join(f"<@{1000000000000000000 + i}>" for i in range(60))
    out = extract_discord_ids(text)
    assert len(out) == 50


# ---- Rejection tests ------------------------------------------


def test_malformed_mention_no_angle_bracket():
    out = extract_discord_ids("@123456789012345678")
    # No angle brackets and no context anchor -> rejected.
    assert out == []


def test_malformed_mention_no_at_inside():
    out = extract_discord_ids("<123456789012345678>")
    # Channel mentions need ``#``, role mentions need ``@&``,
    # users need ``@``. A bare ``<id>`` is not a Discord form.
    assert out == []


def test_empty_text():
    assert extract_discord_ids("") == []
    assert extract_discord_ids(None) == []  # type: ignore[arg-type]


def test_no_ids():
    assert extract_discord_ids("Just prose with no IDs at all.") == []


# ---- Pipeline integration ------------------------------------


def test_pipeline_writes_raw_discord_ids():
    text = "User <@111222333444555666> joined channel <#777888999000111222>"
    ocr = OCRResult(text=text)
    out = enrich(Category.chat_screenshot, ExtractedFields(), ocr)
    assert out.raw is not None
    assert "discord_ids" in out.raw
    assert len(out.raw["discord_ids"]) == 2


def test_pipeline_no_raw_key_when_no_ids():
    ocr = OCRResult(text="Just a sentence with no Discord IDs.")
    out = enrich(Category.chat_screenshot, ExtractedFields(), ocr)
    if out.raw is not None:
        assert "discord_ids" not in out.raw


def test_pipeline_writes_for_every_category():
    text = "Discord channel <#777888999000111222>"
    ocr = OCRResult(text=text)
    for cat in Category:
        out = enrich(cat, ExtractedFields(), ocr)
        assert out.raw is not None
        assert "discord_ids" in out.raw


# ---- Real-world contexts -------------------------------------


def test_discord_py_traceback_context():
    text = (
        "Traceback (most recent call last):\n"
        '  File "bot.py", line 42, in on_message\n'
        '    await channel.send(f"<@{user_id}>")\n'
        "discord.errors.NotFound: 404 Not Found (error code: 10003): "
        "Unknown Channel for channel_id 123456789012345678"
    )
    out = extract_discord_ids(text)
    # The ``channel_id`` anchor on the last line should let the
    # bare 18-digit snowflake land as ``raw``.
    assert any(x["id"] == "123456789012345678" for x in out)


def test_discord_api_json_response():
    text = (
        '{"id": "111222333444555666", "type": 0, "guild_id": '
        '"777888999000111222", "name": "general"}'
    )
    out = extract_discord_ids(text)
    # Two snowflakes; the ``guild_id`` context anchor on the same
    # line should let both bare snowflakes land as ``raw``.
    ids = {x["id"] for x in out}
    assert "111222333444555666" in ids
    assert "777888999000111222" in ids


def test_distinct_from_unix_timestamps():
    # A bare UNIX nanosecond timestamp (19 digits) without
    # Discord context must NOT misfire.
    text = "timestamp_ns=1718915123456789012"
    out = extract_discord_ids(text)
    assert out == []
