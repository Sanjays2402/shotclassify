"""Cross-category emoji-density tally tests.

A new ``ExtractedFields.raw["emoji_density"]`` slot captures a
single float in [0.0, 1.0] representing the share of non-whitespace
characters that are part of an emoji codepoint sequence.

Useful as a quick "this capture is meme-heavy" signal without having
to scan the per-emoji raw["emojis"] tally.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_emoji_density

# ---- Plain text ratios ------------------------------------------


def test_no_emoji_returns_zero():
    """Text with zero emoji content returns 0.0."""
    assert extract_emoji_density("plain text no emojis") == 0.0


def test_only_emoji_returns_one():
    """Text that is entirely emoji returns 1.0."""
    # 4 emoji chars, all of them count -- density = 1.0
    assert extract_emoji_density("🎉🎉🎉🎉") == 1.0


def test_half_emoji_returns_half():
    """50/50 split returns ~0.5."""
    # 4 emoji + 4 non-ws = 0.5
    text = "abcd🎉🎉🎉🎉"
    result = extract_emoji_density(text)
    assert result is not None
    assert 0.4 <= result <= 0.6


def test_one_emoji_among_many_chars_returns_low():
    """1 emoji among 20 non-ws chars returns ~0.048 (1/21)."""
    text = "abcdefghijklmnopqrst🎉"
    result = extract_emoji_density(text)
    assert result is not None
    # 1 emoji codepoint / 21 non-ws chars
    assert 0.04 <= result <= 0.06


# ---- Whitespace exclusion ---------------------------------------


def test_whitespace_excluded_from_denominator():
    """Whitespace doesn't count in the denominator."""
    # 1 emoji, 1 'a' = 2 non-ws chars -> 0.5
    text = "a   \n\n   🎉"
    result = extract_emoji_density(text)
    assert result is not None
    assert 0.45 <= result <= 0.55


def test_whitespace_only_returns_zero():
    """Pure whitespace returns 0.0 (no emoji, no non-ws chars)."""
    assert extract_emoji_density("   \n\t   ") == 0.0


def test_newlines_dont_skew_density():
    """Adding newlines around text doesn't change density."""
    text1 = "abc🎉"
    text2 = "abc🎉\n\n\n\n"
    assert extract_emoji_density(text1) == extract_emoji_density(text2)


# ---- Compound emoji counting ------------------------------------


def test_zwj_family_counts_all_codepoints():
    """A ZWJ family ``👨‍👩‍👧‍👦`` counts all 4 base + 3 ZWJ = 7."""
    text = "👨‍👩‍👧‍👦"
    # All 7 codepoints are non-ws AND emoji, so density = 1.0
    assert extract_emoji_density(text) == 1.0


def test_skin_tone_modifier_counts():
    """``👍🏻`` (thumbs-up + skin-tone) counts 2 codepoints."""
    text = "👍🏻"
    assert extract_emoji_density(text) == 1.0


def test_variation_selector_counts():
    """``❤️`` (heart + variation selector) counts 2 codepoints."""
    text = "❤️"
    assert extract_emoji_density(text) == 1.0


def test_compound_emoji_with_text():
    """``hello 👨‍💻`` -- emoji compound (3 chars) vs 5 ascii letters."""
    text = "hello 👨‍💻"
    result = extract_emoji_density(text)
    assert result is not None
    # 3 emoji codepoints / 8 non-ws (h-e-l-l-o + 3 emoji) = 0.375
    assert 0.30 <= result <= 0.45


# ---- None / empty input -----------------------------------------


def test_empty_string_returns_none():
    """Empty string returns None (no signal)."""
    assert extract_emoji_density("") is None


def test_none_returns_none():
    assert extract_emoji_density(None) is None  # type: ignore[arg-type]


def test_non_string_returns_none():
    assert extract_emoji_density(12345) is None  # type: ignore[arg-type]


def test_only_whitespace_returns_zero_not_none():
    """Whitespace-only is a legitimate signal, returns 0.0 not None."""
    result = extract_emoji_density("   ")
    # Non-ws count is 0 so result is 0.0 (early return inside function)
    assert result == 0.0


# ---- Rounding ----------------------------------------------------


def test_result_rounded_to_three_decimal_places():
    """Density is rounded to 3 decimals for stable storage."""
    text = "abc🎉defg"
    result = extract_emoji_density(text)
    assert result is not None
    # Should have at most 3 decimal places.
    assert result == round(result, 3)


def test_clip_to_valid_range():
    """Density is always in [0.0, 1.0]."""
    text = "🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉"  # all emoji
    result = extract_emoji_density(text)
    assert result is not None
    assert 0.0 <= result <= 1.0


# ---- Different emoji ranges -------------------------------------


def test_emoticon_range():
    """Emoticons (U+1F600..U+1F64F) count."""
    text = "abc😀😀"
    result = extract_emoji_density(text)
    assert result is not None
    assert result > 0


def test_dingbat_range():
    """Dingbats (U+2700..U+27BF) like ✂️ count."""
    text = "abc✂"
    result = extract_emoji_density(text)
    assert result is not None
    assert result > 0


def test_transport_range():
    """Transport (U+1F680..U+1F6FF) like 🚀 counts."""
    text = "rocket 🚀"
    result = extract_emoji_density(text)
    assert result is not None
    assert result > 0


def test_misc_symbols_range():
    """Miscellaneous symbols (U+2600..U+26FF) like ⚠️ count."""
    text = "warning ⚠️"
    result = extract_emoji_density(text)
    assert result is not None
    assert result > 0


def test_plain_ascii_symbols_not_counted():
    """``$ € £ © ®`` are NOT counted as emoji (they're symbols)."""
    text = "$1.99 €2.99 £3.99 © Acme"
    assert extract_emoji_density(text) == 0.0


# ---- Pipeline integration ---------------------------------------


def test_pipeline_writes_emoji_density_under_raw():
    """The pipeline always writes raw["emoji_density"] for non-empty text."""
    fields = ExtractedFields()
    ocr = OCRResult(text="Great job 🎉")
    out = enrich(Category.other, fields, ocr)
    assert "emoji_density" in (out.raw or {})
    assert out.raw["emoji_density"] > 0


def test_pipeline_writes_zero_density_for_no_emoji():
    """Even when no emoji, density is 0.0 (legitimate signal)."""
    fields = ExtractedFields()
    ocr = OCRResult(text="plain text without any emoji")
    out = enrich(Category.other, fields, ocr)
    assert "emoji_density" in (out.raw or {})
    assert out.raw["emoji_density"] == 0.0


def test_pipeline_writes_density_for_chat_category():
    fields = ExtractedFields()
    ocr = OCRResult(text="Alice: hi 👋\nBob: 👋 morning")
    out = enrich(Category.chat_screenshot, fields, ocr)
    assert "emoji_density" in (out.raw or {})
    assert out.raw["emoji_density"] > 0


def test_pipeline_writes_density_for_meme_category():
    """Meme-heavy capture has high density."""
    fields = ExtractedFields()
    ocr = OCRResult(text="🤣🤣🤣😂😂😂🔥🔥🔥💯💯💯")
    out = enrich(Category.meme, fields, ocr)
    assert "emoji_density" in (out.raw or {})
    # All emoji -> density is 1.0
    assert out.raw["emoji_density"] == 1.0


def test_pipeline_writes_density_for_receipt():
    """Even receipts get density (rarely have emoji but if they do)."""
    fields = ExtractedFields()
    ocr = OCRResult(text="Starbucks ☕ 4.50")
    out = enrich(Category.receipt, fields, ocr)
    assert "emoji_density" in (out.raw or {})
    assert out.raw["emoji_density"] > 0


def test_pipeline_density_absent_for_empty_text():
    """Empty OCR text -> no density key (returns None)."""
    fields = ExtractedFields()
    ocr = OCRResult(text="")
    out = enrich(Category.other, fields, ocr)
    # extract_emoji_density returns None for empty -> not written
    assert "emoji_density" not in (out.raw or {})


# ---- Meme-heavy vs code-heavy comparison ----------------------


def test_meme_heavier_than_code():
    """A meme caption has higher density than a code snippet."""
    meme_text = "lol 🤣😂🤣😂🤣"
    code_text = "def foo(x):\n    return x + 1\n"
    meme_density = extract_emoji_density(meme_text)
    code_density = extract_emoji_density(code_text)
    assert meme_density is not None and code_density is not None
    assert meme_density > code_density
    assert code_density == 0.0


def test_chat_caption_moderate_density():
    """A chat message with one emoji has moderate density."""
    text = "Heading to lunch 🍕 BRB"
    result = extract_emoji_density(text)
    assert result is not None
    # 1 emoji / (15 non-ws chars + 1) = ~0.063
    assert 0.04 <= result <= 0.10


def test_thread_with_multiple_reactions():
    """A chat capture with reactions stuck on the end."""
    text = "Alice: great work! Bob: agreed Carol: 🎉👏🎉👏🎉"
    result = extract_emoji_density(text)
    assert result is not None
    # 5 emoji / ~30 non-ws chars = 0.16
    assert 0.10 <= result <= 0.20
