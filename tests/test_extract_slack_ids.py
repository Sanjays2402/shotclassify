"""Cross-category Slack ID extractor tests.

A new cross-category extractor surfaces Slack channel / DM / user /
private-channel / enterprise-user / bot / team / enterprise / file /
usergroup IDs found in the OCR text under
``ExtractedFields.raw["slack_ids"]``.

Output shape: list of ``{"kind", "id"}`` dicts. Recognised prefixes
and their kind tags:

  * ``C`` -> ``channel`` (public)
  * ``D`` -> ``dm``
  * ``G`` -> ``private_channel`` (legacy private / multi-party DM)
  * ``U`` -> ``user``
  * ``W`` -> ``enterprise_user``
  * ``B`` -> ``bot``
  * ``T`` -> ``team`` (workspace)
  * ``E`` -> ``enterprise`` (grid)
  * ``F`` -> ``file``
  * ``S`` -> ``usergroup``

Shape rules:

* Single uppercase prefix from the recognised set, then 8..10
  uppercase-alphanumeric chars. Tail must contain at least ONE
  digit to keep all-letter prose words from misfiring.
* Word-boundary isolation on both ends so a "C012345ABCD" embedded
  inside a longer hex blob does not misfire.
* Output preserves first-seen order, dedupes on ``id`` value,
  capped at 50.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_slack_ids

# ---- Basic kind detection -----------------------------------------


def test_channel_id():
    out = extract_slack_ids("See C012345ABCD for details")
    assert out == [{"kind": "channel", "id": "C012345ABCD"}]


def test_dm_id():
    out = extract_slack_ids("DM to D012345ABCD")
    assert out == [{"kind": "dm", "id": "D012345ABCD"}]


def test_private_channel_id():
    out = extract_slack_ids("Private channel G012345ABCD")
    assert out == [{"kind": "private_channel", "id": "G012345ABCD"}]


def test_user_id():
    out = extract_slack_ids("User U012345ABCD")
    assert out == [{"kind": "user", "id": "U012345ABCD"}]


def test_enterprise_user_id():
    out = extract_slack_ids("Enterprise user W012345ABCD")
    assert out == [{"kind": "enterprise_user", "id": "W012345ABCD"}]


def test_bot_id():
    out = extract_slack_ids("Bot B012345ABCD")
    assert out == [{"kind": "bot", "id": "B012345ABCD"}]


def test_team_id():
    out = extract_slack_ids("Workspace T012345ABCD")
    assert out == [{"kind": "team", "id": "T012345ABCD"}]


def test_enterprise_id():
    out = extract_slack_ids("Enterprise grid E012345ABCD")
    assert out == [{"kind": "enterprise", "id": "E012345ABCD"}]


def test_file_id():
    out = extract_slack_ids("File F012345ABCD")
    assert out == [{"kind": "file", "id": "F012345ABCD"}]


def test_usergroup_id():
    out = extract_slack_ids("Usergroup S012345ABCD")
    assert out == [{"kind": "usergroup", "id": "S012345ABCD"}]


# ---- Length variants ----------------------------------------------


def test_id_with_9_chars_total():
    """A 9-char total ID (prefix + 8-char tail) -- the lower bound."""
    out = extract_slack_ids("Channel C01234567")
    assert out == [{"kind": "channel", "id": "C01234567"}]


def test_id_with_11_chars_total():
    """An 11-char total ID (prefix + 10-char tail) -- the upper bound.
    ``C012345ABCD`` is C + 0123456789ABCD's first 10 -- exactly the
    upper bound that the rest of the test suite exercises."""
    out = extract_slack_ids("Channel C0123456789")
    assert out == [{"kind": "channel", "id": "C0123456789"}]


def test_id_with_12_chars_rejected():
    """A 12-char total run is too long."""
    out = extract_slack_ids("Hex blob C0123456789X")
    assert out == []


def test_id_with_7_chars_rejected():
    """A 7-char tail (8 chars total) is below the minimum."""
    out = extract_slack_ids("Hex C012345A")
    assert out == []


# ---- Tail-digit requirement ---------------------------------------


def test_all_letter_prose_rejected():
    """An all-letter 9-char uppercase word starting with C/D/G/U/W/B/
    T/E/F/S should NOT match -- real Slack IDs always carry at least
    one digit."""
    assert extract_slack_ids("CHEAPCODE in prose") == []
    assert extract_slack_ids("DESPAIRED nothing") == []
    assert extract_slack_ids("UNFORESEEN word") == []


def test_single_digit_in_tail_accepted():
    """A single digit anywhere in the tail is enough to satisfy the
    rule -- letter-heavy IDs are legitimate."""
    out = extract_slack_ids("User U2ABCDEFGH")
    assert out == [{"kind": "user", "id": "U2ABCDEFGH"}]


def test_digit_at_end_of_tail_accepted():
    out = extract_slack_ids("User UABCDEFGH2")
    assert out == [{"kind": "user", "id": "UABCDEFGH2"}]


def test_all_digit_tail_accepted():
    out = extract_slack_ids("Channel C012345678")
    assert out == [{"kind": "channel", "id": "C012345678"}]


# ---- Word-boundary defence ----------------------------------------


def test_word_boundary_left_rejects_alpha_prefix():
    """A leading alpha letter blocks the match -- 'AC012345ABCD' is
    not 'C012345ABCD' with surrounding noise, it's a longer hex blob
    we don't want to misread."""
    assert extract_slack_ids("AC012345ABCDEF hex") == []


def test_word_boundary_left_rejects_digit_prefix():
    """A leading digit blocks the match too -- 1C012345ABCD is in
    the middle of a longer hex / number."""
    assert extract_slack_ids("1C012345ABCD nope") == []


def test_word_boundary_right_rejects_alpha_suffix():
    """A trailing alpha that would extend the ID past 11 chars
    blocks the match."""
    assert extract_slack_ids("C012345ABCDEF too long") == []


def test_word_boundary_right_allows_dash_suffix():
    """A dash terminator is a non-word boundary; URL-fragment style
    'C012345ABCD-suffix' still matches."""
    out = extract_slack_ids("ref C012345ABCD-suffix")
    assert out == [{"kind": "channel", "id": "C012345ABCD"}]


def test_word_boundary_underscore_blocks():
    """An underscore is alpha-numeric-like; we want the ID isolated."""
    assert extract_slack_ids("_C012345ABCD_ wrapped") == []


# ---- Slack mention syntax -----------------------------------------


def test_user_mention_syntax_with_angle_brackets():
    out = extract_slack_ids("Mention <@U012345ABCD> in a message")
    assert out == [{"kind": "user", "id": "U012345ABCD"}]


def test_channel_mention_syntax_with_pipe():
    out = extract_slack_ids("See <#C012345ABCD|general> for context")
    assert out == [{"kind": "channel", "id": "C012345ABCD"}]


def test_usergroup_mention_syntax():
    out = extract_slack_ids("Notify <!subteam^S012345ABCD>")
    assert out == [{"kind": "usergroup", "id": "S012345ABCD"}]


# ---- Multiple IDs, ordering, dedupe -------------------------------


def test_multiple_distinct_ids_preserve_order():
    out = extract_slack_ids(
        "First U012345ABCD, then C012345ABCD, then T012345ABCD"
    )
    assert out == [
        {"kind": "user", "id": "U012345ABCD"},
        {"kind": "channel", "id": "C012345ABCD"},
        {"kind": "team", "id": "T012345ABCD"},
    ]


def test_dedup_on_same_id():
    out = extract_slack_ids(
        "C012345ABCD and again C012345ABCD"
    )
    assert out == [{"kind": "channel", "id": "C012345ABCD"}]


def test_different_kinds_with_same_tail_treated_distinct():
    """C012345ABCD and U012345ABCD are different entities even with
    the same tail -- the prefix letter is part of the ID."""
    out = extract_slack_ids(
        "channel C012345ABCD and user U012345ABCD"
    )
    assert out == [
        {"kind": "channel", "id": "C012345ABCD"},
        {"kind": "user", "id": "U012345ABCD"},
    ]


def test_cap_at_50_entries():
    """The cap protects against pathological OCR output flooding."""
    text = " ".join(f"C{i:010d}" for i in range(60))
    out = extract_slack_ids(text)
    assert len(out) == 50


# ---- Empty / non-string inputs ------------------------------------


def test_empty_text_returns_empty_list():
    assert extract_slack_ids("") == []


def test_none_text_returns_empty_list():
    assert extract_slack_ids(None) == []  # type: ignore[arg-type]


def test_no_slack_ids_in_normal_text():
    assert extract_slack_ids("This is a normal sentence with no IDs.") == []


def test_lowercase_not_matched():
    """Slack IDs are always uppercase in real payloads."""
    assert extract_slack_ids("c012345abcd in lowercase") == []


def test_mixed_case_not_matched():
    """A mixed-case tail breaks the uppercase-only contract."""
    assert extract_slack_ids("C012345aBCD mixed") == []


# ---- Realistic Slack API URLs ------------------------------------


def test_slack_api_channel_url():
    out = extract_slack_ids(
        "https://slack.com/api/conversations.info?channel=C012345ABCD"
    )
    assert {"kind": "channel", "id": "C012345ABCD"} in out


def test_slack_archive_url():
    out = extract_slack_ids(
        "Archive https://example.slack.com/archives/C012345ABCD/p1234567890"
    )
    assert {"kind": "channel", "id": "C012345ABCD"} in out


def test_realistic_error_with_team_and_channel():
    out = extract_slack_ids(
        "Error: channel C012345ABCD not found in team T01ABCDEFG"
    )
    assert {"kind": "channel", "id": "C012345ABCD"} in out
    assert {"kind": "team", "id": "T01ABCDEFG"} in out


# ---- Pipeline integration ----------------------------------------


def test_pipeline_populates_raw_slack_ids_for_chat():
    ocr = OCRResult(text="Alice: see <#C012345ABCD|general>")
    fields = enrich(Category.chat_screenshot, ExtractedFields(), ocr)
    assert "slack_ids" in fields.raw
    assert {"kind": "channel", "id": "C012345ABCD"} in fields.raw["slack_ids"]


def test_pipeline_populates_raw_slack_ids_for_code():
    ocr = OCRResult(
        text="webhook_url = 'https://hooks.slack.com/T012345ABCD/B012345ABCD/abc'"
    )
    fields = enrich(Category.code_snippet, ExtractedFields(), ocr)
    assert "slack_ids" in fields.raw
    kinds = {entry["kind"] for entry in fields.raw["slack_ids"]}
    assert "team" in kinds
    assert "bot" in kinds


def test_pipeline_populates_raw_slack_ids_for_error():
    ocr = OCRResult(text="Error posting to <@U012345ABCD>: rate limited")
    fields = enrich(Category.error_stacktrace, ExtractedFields(), ocr)
    assert "slack_ids" in fields.raw
    assert {"kind": "user", "id": "U012345ABCD"} in fields.raw["slack_ids"]


def test_pipeline_omits_raw_slack_ids_when_none_present():
    """Don't populate the raw key when no IDs are present -- keeps
    the JSON column small for non-Slack screenshots."""
    ocr = OCRResult(text="Plain text with no Slack IDs.")
    fields = enrich(Category.document, ExtractedFields(), ocr)
    assert "slack_ids" not in fields.raw


def test_pipeline_preserves_existing_raw_entries():
    """The Slack extractor must not stomp on raw entries other
    extractors populated."""
    ocr = OCRResult(
        text="See <#C012345ABCD|general> and visit https://example.com"
    )
    fields = enrich(Category.chat_screenshot, ExtractedFields(), ocr)
    assert "slack_ids" in fields.raw
    assert "urls" in fields.raw
