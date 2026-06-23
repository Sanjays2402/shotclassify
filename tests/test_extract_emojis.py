"""Cross-category emoji-codepoint tally extractor tests.

A new cross-category extractor tallies every distinct emoji
codepoint found in the OCR text under
``ExtractedFields.raw["emojis"]``.

Output shape: list of ``{"emoji", "codepoint", "count"}`` dicts
sorted by descending count (most common first), then by
first-seen-order on ties. Capped at 50 distinct entries.

Detected codepoint ranges:

* Miscellaneous Symbols and Pictographs (U+1F300..U+1F5FF)
* Emoticons (U+1F600..U+1F64F)
* Transport and Map Symbols (U+1F680..U+1F6FF)
* Supplemental Symbols and Pictographs (U+1F900..U+1F9FF)
* Symbols and Pictographs Extended-A (U+1FA70..U+1FAFF)
* Miscellaneous Symbols (U+2600..U+26FF)
* Dingbats (U+2700..U+27BF)
* Enclosed Alphanumerics (U+1F1E0..U+1F1FF) for flags

Compound emoji (ZWJ sequences, skin-tone modifiers, variation
selectors) are kept as one logical unit.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_emojis

# ---- Basic single-emoji counts -----------------------------------


def test_single_face_emoji():
    out = extract_emojis("Hello 😀 world")
    assert out == [{"emoji": "😀", "codepoint": "U+1F600", "count": 1}]


def test_single_thumbs_up():
    out = extract_emojis("Looks good 👍")
    assert out == [{"emoji": "👍", "codepoint": "U+1F44D", "count": 1}]


def test_single_party_popper():
    out = extract_emojis("Congrats 🎉")
    assert out == [{"emoji": "🎉", "codepoint": "U+1F389", "count": 1}]


def test_single_red_heart_with_variation_selector():
    """``❤️`` is U+2764 (heart) + U+FE0F (emoji variation)."""
    out = extract_emojis("Love this ❤️")
    assert out == [
        {"emoji": "❤️", "codepoint": "U+2764 U+FE0F", "count": 1}
    ]


def test_single_thinking_face():
    out = extract_emojis("🤔")
    assert out == [{"emoji": "🤔", "codepoint": "U+1F914", "count": 1}]


def test_single_rocket():
    out = extract_emojis("Launch 🚀 today")
    assert out == [{"emoji": "🚀", "codepoint": "U+1F680", "count": 1}]


def test_single_warning_sign():
    out = extract_emojis("Be careful ⚠️")
    assert out == [
        {"emoji": "⚠️", "codepoint": "U+26A0 U+FE0F", "count": 1}
    ]


# ---- Counting -----------------------------------------------------


def test_repeated_emoji():
    out = extract_emojis("👍 👍 👍 nice")
    assert out == [{"emoji": "👍", "codepoint": "U+1F44D", "count": 3}]


def test_multiple_distinct_emoji():
    """Different emoji ordered by count descending."""
    out = extract_emojis("🎉 🎉 🎉 👍 👍 ❤️")
    counts = [e["count"] for e in out]
    assert counts == [3, 2, 1]
    assert out[0]["emoji"] == "🎉"
    assert out[1]["emoji"] == "👍"
    assert out[2]["emoji"] == "❤️"


def test_first_seen_order_on_tie():
    """Equal counts preserve first-seen order."""
    out = extract_emojis("👍 ❤️ 🎉")
    emojis = [e["emoji"] for e in out]
    assert emojis == ["👍", "❤️", "🎉"]


def test_mixed_with_text():
    text = "Build pipeline 🟢 PASS\nTests 🟢 OK\nDeploy 🚀"
    out = extract_emojis(text)
    counts_by_emoji = {e["emoji"]: e["count"] for e in out}
    assert counts_by_emoji["🟢"] == 2
    assert counts_by_emoji["🚀"] == 1


# ---- ZWJ compound sequences --------------------------------------


def test_family_zwj_sequence():
    """``👨‍👩‍👧‍👦`` = man + ZWJ + woman + ZWJ + girl + ZWJ + boy
    -- one logical unit."""
    family = "\U0001F468\u200D\U0001F469\u200D\U0001F467\u200D\U0001F466"
    out = extract_emojis(f"Hello {family}")
    assert len(out) == 1
    assert out[0]["count"] == 1
    assert "U+200D" in out[0]["codepoint"]


def test_man_technologist_compound():
    """``👨‍💻`` = man + ZWJ + laptop -- one unit."""
    compound = "\U0001F468\u200D\U0001F4BB"
    out = extract_emojis(compound)
    assert len(out) == 1
    assert out[0]["count"] == 1
    # Codepoint string includes both base chars + the ZWJ.
    assert out[0]["codepoint"] == "U+1F468 U+200D U+1F4BB"


def test_rainbow_flag_zwj():
    """``🏳️‍🌈`` = white flag + variation selector + ZWJ + rainbow."""
    flag = "\U0001F3F3\uFE0F\u200D\U0001F308"
    out = extract_emojis(flag)
    assert len(out) == 1
    assert out[0]["count"] == 1


def test_multiple_family_compounds_same_unit():
    """Same compound family repeated counts as one unit with N."""
    family = "\U0001F468\u200D\U0001F469\u200D\U0001F466"  # man+woman+boy
    out = extract_emojis(f"{family} {family} {family}")
    assert len(out) == 1
    assert out[0]["count"] == 3


# ---- Skin-tone modifiers -----------------------------------------


def test_thumbs_up_light_skin_tone():
    """``👍🏻`` = thumbs up + light skin modifier."""
    out = extract_emojis("\U0001F44D\U0001F3FB")
    assert len(out) == 1
    assert out[0]["count"] == 1
    assert out[0]["codepoint"] == "U+1F44D U+1F3FB"


def test_thumbs_up_dark_skin_tone():
    """``👍🏿`` = thumbs up + dark skin modifier."""
    out = extract_emojis("\U0001F44D\U0001F3FF")
    assert len(out) == 1
    assert out[0]["codepoint"] == "U+1F44D U+1F3FF"


def test_skin_tones_create_distinct_units():
    """Same base + different skin tone = 2 distinct entries."""
    text = "\U0001F44D\U0001F3FB \U0001F44D\U0001F3FF"
    out = extract_emojis(text)
    assert len(out) == 2
    assert all(e["count"] == 1 for e in out)


def test_thumbs_up_no_modifier_vs_with_modifier():
    """Bare thumbs up vs modified are distinct units."""
    text = "\U0001F44D \U0001F44D\U0001F3FB"
    out = extract_emojis(text)
    assert len(out) == 2


def test_waving_hand_medium_skin_tone():
    out = extract_emojis("\U0001F44B\U0001F3FD")
    assert len(out) == 1
    assert out[0]["codepoint"] == "U+1F44B U+1F3FD"


# ---- Variation selectors -----------------------------------------


def test_emoji_variation_selector_combined():
    """``❤️`` = ❤ (U+2764) + U+FE0F (emoji style)."""
    out = extract_emojis("\u2764\uFE0F")
    assert out == [{"emoji": "❤️", "codepoint": "U+2764 U+FE0F", "count": 1}]


def test_bare_heart_without_variation_selector():
    """Just U+2764 without VS-16 also counts (in the emoji range)."""
    out = extract_emojis("\u2764")
    assert out == [{"emoji": "❤", "codepoint": "U+2764", "count": 1}]


def test_bare_and_vs_heart_distinct():
    """``❤`` and ``❤️`` count as distinct codepoint sequences."""
    text = "\u2764 \u2764\uFE0F"
    out = extract_emojis(text)
    assert len(out) == 2


# ---- Range coverage ----------------------------------------------


def test_misc_symbols_pictographs_range():
    """U+1F300..U+1F5FF: cyclone."""
    out = extract_emojis("\U0001F300")
    assert out == [{"emoji": "🌀", "codepoint": "U+1F300", "count": 1}]


def test_emoticons_range():
    """U+1F600..U+1F64F: grinning face."""
    out = extract_emojis("\U0001F600")
    assert out == [{"emoji": "😀", "codepoint": "U+1F600", "count": 1}]


def test_transport_map_range():
    """U+1F680..U+1F6FF: rocket."""
    out = extract_emojis("\U0001F680")
    assert out == [{"emoji": "🚀", "codepoint": "U+1F680", "count": 1}]


def test_supplemental_pictographs():
    """U+1F900..U+1F9FF: brain emoji."""
    out = extract_emojis("\U0001F9E0")
    assert out == [{"emoji": "🧠", "codepoint": "U+1F9E0", "count": 1}]


def test_extended_a_pictographs():
    """U+1FA70..U+1FAFF: sewing needle."""
    out = extract_emojis("\U0001FAA1")
    assert out == [{"emoji": "🪡", "codepoint": "U+1FAA1", "count": 1}]


def test_misc_symbols_2600_range():
    """U+2600..U+26FF: sun with rays."""
    out = extract_emojis("\u2600")
    assert out == [{"emoji": "☀", "codepoint": "U+2600", "count": 1}]


def test_dingbats_range():
    """U+2700..U+27BF: heavy check mark."""
    out = extract_emojis("\u2714")
    assert out == [{"emoji": "✔", "codepoint": "U+2714", "count": 1}]


def test_regional_indicator_for_flag_chars():
    """U+1F1E6..U+1F1FF: regional indicator chars (used in pairs
    to form country flags). We count each as an emoji."""
    out = extract_emojis("\U0001F1FA\U0001F1F8")  # US flag (US)
    # The two regional indicators count as separate emoji because
    # there's no ZWJ between them -- this is the raw shape.
    assert len(out) == 2
    assert all(e["count"] == 1 for e in out)


# ---- Non-emoji rejection -----------------------------------------


def test_no_emoji_returns_empty():
    out = extract_emojis("just plain text")
    assert out == []


def test_empty_string_returns_empty():
    out = extract_emojis("")
    assert out == []


def test_whitespace_only_returns_empty():
    out = extract_emojis("   \n  \t  ")
    assert out == []


def test_plain_ascii_punctuation_rejected():
    out = extract_emojis("Hello, world! This is plain text.")
    assert out == []


def test_currency_symbols_rejected():
    """``$`` ``€`` ``£`` ``¥`` are not in emoji ranges."""
    out = extract_emojis("Price: $5.00, €4.50, £3.50")
    assert out == []


def test_arrows_outside_emoji_range_rejected():
    """``→`` (U+2192) is just an arrow, not emoji."""
    out = extract_emojis("Step 1 \u2192 Step 2")
    assert out == []


def test_copyright_symbol_rejected():
    """``©`` (U+00A9) is not in emoji ranges."""
    out = extract_emojis("\u00A9 2024 Acme")
    assert out == []


def test_math_symbols_rejected():
    """``∑`` (U+2211), ``∞`` (U+221E) not in emoji ranges."""
    out = extract_emojis("\u2211 x = \u221E")
    assert out == []


# ---- Sorting / ordering ------------------------------------------


def test_sorted_by_descending_count():
    text = "🎉 🎉 🎉 🎉 👍 👍 ❤️"
    out = extract_emojis(text)
    counts = [e["count"] for e in out]
    assert counts == [4, 2, 1]


def test_first_seen_breaks_tie():
    text = "❤️ 👍 🎉"
    out = extract_emojis(text)
    emojis = [e["emoji"] for e in out]
    assert emojis == ["❤️", "👍", "🎉"]


def test_complex_ordering():
    text = "👍 ❤️ ❤️ 🎉 🎉 🎉 👍"
    out = extract_emojis(text)
    # Counts: 🎉=3, 👍=2, ❤️=2
    # First-seen of 👍 before ❤️
    counts = [e["count"] for e in out]
    assert counts == [3, 2, 2]
    assert out[0]["emoji"] == "🎉"
    assert out[1]["emoji"] == "👍"
    assert out[2]["emoji"] == "❤️"


# ---- Cap enforcement ---------------------------------------------


def test_cap_at_50_distinct_entries():
    """Only 50 distinct emoji are returned even when more exist."""
    # Build 60 distinct emoji using consecutive codepoints from
    # the emoticons range.
    text = " ".join(chr(0x1F600 + i) for i in range(60))
    out = extract_emojis(text)
    assert len(out) == 50


# ---- Real-world content fixtures ---------------------------------


def test_realistic_meme_caption():
    """A meme caption with heavy emoji usage."""
    text = "POV: you finally fix the bug 🎉🎉🎉 only to find 3 more 😱"
    out = extract_emojis(text)
    counts = {e["emoji"]: e["count"] for e in out}
    assert counts["🎉"] == 3
    assert counts["😱"] == 1


def test_realistic_pr_review():
    """A code review with thumbs up reactions."""
    text = "LGTM 👍 👍 great work ❤️"
    out = extract_emojis(text)
    counts = {e["emoji"]: e["count"] for e in out}
    assert counts["👍"] == 2
    assert counts["❤️"] == 1


def test_realistic_chat_celebration():
    text = (
        "Alice: 🎉🎂 happy birthday Bob!\n"
        "Carol: 🎉🎂🥳\n"
        "Dave: 🎉🎂🥳 happy bday!\n"
    )
    out = extract_emojis(text)
    counts = {e["emoji"]: e["count"] for e in out}
    assert counts["🎉"] == 3
    assert counts["🎂"] == 3
    assert counts["🥳"] == 2


def test_realistic_status_indicators():
    text = (
        "Service health:\n"
        "API ✅\n"
        "DB ✅\n"
        "Cache ❌\n"
        "Queue ⚠️\n"
    )
    out = extract_emojis(text)
    counts = {e["emoji"]: e["count"] for e in out}
    assert counts["✅"] == 2
    assert counts["❌"] == 1
    assert counts["⚠️"] == 1


# ---- Pipeline wiring ---------------------------------------------


def test_pipeline_writes_emojis_under_raw():
    """The pipeline writes raw[\"emojis\"] for every category."""
    fields = ExtractedFields()
    ocr = OCRResult(text="Great job 🎉 well done 👍 👍")
    out = enrich(Category.other, fields, ocr)
    assert "emojis" in (out.raw or {})
    emojis_data = {e["emoji"]: e["count"] for e in out.raw["emojis"]}
    assert emojis_data["🎉"] == 1
    assert emojis_data["👍"] == 2


def test_pipeline_no_emojis_no_raw_key():
    """When no emoji is found, the raw[\"emojis\"] key is absent."""
    fields = ExtractedFields()
    ocr = OCRResult(text="plain text screenshot")
    out = enrich(Category.other, fields, ocr)
    assert "emojis" not in (out.raw or {})


def test_pipeline_writes_emojis_for_chat_category():
    """Cross-category: chat screenshots populate emojis too."""
    fields = ExtractedFields()
    ocr = OCRResult(text="Alice: hi 👋\nBob: 👋 morning")
    out = enrich(Category.chat_screenshot, fields, ocr)
    assert "emojis" in (out.raw or {})
    assert out.raw["emojis"][0]["count"] == 2


def test_pipeline_writes_emojis_for_meme_category():
    """Meme screenshots are the obvious target."""
    fields = ExtractedFields()
    ocr = OCRResult(text="WHEN THE 🐛 IS A FEATURE 😅")
    out = enrich(Category.meme, fields, ocr)
    assert "emojis" in (out.raw or {})
    emojis_data = {e["emoji"]: e["count"] for e in out.raw["emojis"]}
    assert "🐛" in emojis_data
    assert "😅" in emojis_data


def test_pipeline_writes_emojis_for_receipt_category():
    """Even receipt category writes raw[\"emojis\"] (cross-category)."""
    fields = ExtractedFields()
    ocr = OCRResult(text="Thanks 🙏 Total: $25.00")
    out = enrich(Category.receipt, fields, ocr)
    assert "emojis" in (out.raw or {})


# ---- Edge cases --------------------------------------------------


def test_emoji_at_start_and_end():
    out = extract_emojis("🎉 in the middle 👍")
    assert len(out) == 2


def test_emoji_adjacent_no_space():
    """Adjacent emojis without space still count separately."""
    out = extract_emojis("🎉🎉👍")
    counts = {e["emoji"]: e["count"] for e in out}
    assert counts["🎉"] == 2
    assert counts["👍"] == 1


def test_very_long_text_with_few_emoji():
    """Bulk text with sparse emoji."""
    text = ("word " * 1000) + "🎉" + (" word" * 1000)
    out = extract_emojis(text)
    assert out == [{"emoji": "🎉", "codepoint": "U+1F389", "count": 1}]


def test_only_emoji():
    out = extract_emojis("🎉🎉🎉")
    assert out == [{"emoji": "🎉", "codepoint": "U+1F389", "count": 3}]


def test_non_string_input_returns_empty():
    """Defensive: non-string input returns []."""
    assert extract_emojis(None) == []
    assert extract_emojis(123) == []
    assert extract_emojis(["🎉"]) == []
