"""Cross-category colour-value extractor tests.

A new ``ExtractedFields.raw["colors"]`` slot captures the colours
referenced in design / frontend / brand captures. Output is a list
of ``{"model": str, "value": str}`` dicts where model is one of:
hex / rgb / hsl / hsv / oklch / oklab / lab / lch / named.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_colors

# ---- Hex ---------------------------------------------------------


def test_hex_6_digit_uppercase():
    out = extract_colors("#FF5733")
    assert out == [{"model": "hex", "value": "#ff5733"}]


def test_hex_6_digit_lowercase():
    out = extract_colors("#ff5733")
    assert out == [{"model": "hex", "value": "#ff5733"}]


def test_hex_3_digit_short_form_expanded():
    """``#fa3`` expands to ``#ffaa33``."""
    out = extract_colors("#fa3")
    assert out == [{"model": "hex", "value": "#ffaa33"}]


def test_hex_4_digit_short_form_alpha_expanded():
    """``#fa3c`` expands to ``#ffaa33cc``."""
    out = extract_colors("#fa3c")
    assert out == [{"model": "hex", "value": "#ffaa33cc"}]


def test_hex_8_digit_alpha():
    out = extract_colors("#FF5733AA")
    assert out == [{"model": "hex", "value": "#ff5733aa"}]


def test_hex_0x_prefix():
    """``0xFF5733`` (Android / Java colour literal form)."""
    out = extract_colors("0xFF5733")
    assert out == [{"model": "hex", "value": "#ff5733"}]


def test_hex_5_digit_rejected():
    """5 hex chars is not a valid colour."""
    out = extract_colors("#12345")
    assert out == []


def test_hex_7_digit_rejected():
    """7 hex chars is not a valid colour."""
    out = extract_colors("#1234567")
    assert out == []


def test_hex_without_prefix_rejected():
    """Bare ``FF5733`` without # or 0x prefix is rejected."""
    out = extract_colors("FF5733")
    assert out == []


def test_hex_inside_url_word_boundary():
    """A hex inside a URL fragment (#sectionId) is rejected because
    it doesn't have 6/8 hex chars."""
    out = extract_colors("https://example.com/page#section")
    assert out == []


def test_multiple_hexes():
    out = extract_colors("background: #ff5733; color: #336699;")
    assert {"model": "hex", "value": "#ff5733"} in out
    assert {"model": "hex", "value": "#336699"} in out


# ---- rgb() / rgba() ---------------------------------------------


def test_rgb_comma_separated():
    out = extract_colors("rgb(255, 87, 51)")
    assert out == [{"model": "rgb", "value": "rgb(255, 87, 51)"}]


def test_rgb_space_separated_css4():
    """CSS-4 space-separated syntax."""
    out = extract_colors("rgb(255 87 51)")
    assert out == [{"model": "rgb", "value": "rgb(255, 87, 51)"}]


def test_rgba_with_alpha():
    out = extract_colors("rgba(255, 87, 51, 0.5)")
    assert out == [{"model": "rgb", "value": "rgba(255, 87, 51, 0.5)"}]


def test_rgba_with_alpha_percent():
    out = extract_colors("rgba(255, 87, 51, 50%)")
    assert out == [{"model": "rgb", "value": "rgba(255, 87, 51, 50)"}]


def test_rgba_with_slash_separator_alpha():
    """CSS-4 form: ``rgb(R G B / A)``."""
    out = extract_colors("rgb(255 87 51 / 0.5)")
    assert out == [{"model": "rgb", "value": "rgba(255, 87, 51, 0.5)"}]


def test_rgb_value_out_of_range_rejected():
    """``rgb(256, ...)`` is invalid because channels max at 255."""
    out = extract_colors("rgb(256, 87, 51)")
    assert out == []


def test_rgb_function_name_required():
    """Bare ``(255, 87, 51)`` without the rgb() prefix is rejected."""
    out = extract_colors("(255, 87, 51)")
    assert out == []


# ---- hsl() / hsla() ---------------------------------------------


def test_hsl_basic():
    out = extract_colors("hsl(11, 100%, 60%)")
    assert out == [{"model": "hsl", "value": "hsl(11, 100%, 60%)"}]


def test_hsl_space_separated_css4():
    out = extract_colors("hsl(11 100% 60%)")
    assert out == [{"model": "hsl", "value": "hsl(11, 100%, 60%)"}]


def test_hsla_with_alpha():
    out = extract_colors("hsla(11, 100%, 60%, 0.5)")
    assert out == [{"model": "hsl", "value": "hsla(11, 100%, 60%, 0.5)"}]


def test_hsl_with_deg_unit():
    out = extract_colors("hsl(11deg, 100%, 60%)")
    assert out == [{"model": "hsl", "value": "hsl(11deg, 100%, 60%)"}]


def test_hsl_negative_hue():
    out = extract_colors("hsl(-30, 50%, 50%)")
    assert out == [{"model": "hsl", "value": "hsl(-30, 50%, 50%)"}]


# ---- hsv() (non-CSS) --------------------------------------------


def test_hsv_basic():
    out = extract_colors("hsv(11, 80%, 100%)")
    assert out == [{"model": "hsv", "value": "hsv(11, 80%, 100%)"}]


def test_hsv_no_percent_signs():
    """HSV in design tools sometimes omits % on saturation/value."""
    out = extract_colors("hsv(11, 80, 100)")
    assert out == [{"model": "hsv", "value": "hsv(11, 80, 100)"}]


# ---- Perceptual: oklch / oklab / lab / lch ---------------------


def test_oklch_basic():
    out = extract_colors("oklch(0.8 0.1 30)")
    assert out == [{"model": "oklch", "value": "oklch(0.8 0.1 30)"}]


def test_oklab_basic():
    out = extract_colors("oklab(0.8 0.1 0.05)")
    assert out == [{"model": "oklab", "value": "oklab(0.8 0.1 0.05)"}]


def test_lab_with_percent():
    out = extract_colors("lab(50% 40 30)")
    assert out == [{"model": "lab", "value": "lab(50% 40 30)"}]


def test_lch_with_percent():
    out = extract_colors("lch(50% 40 30)")
    assert out == [{"model": "lch", "value": "lch(50% 40 30)"}]


def test_oklch_with_alpha():
    out = extract_colors("oklch(0.8 0.1 30 / 0.5)")
    assert out == [{"model": "oklch", "value": "oklch(0.8 0.1 30 / 0.5)"}]


# ---- Named colours (curated catalogue) --------------------------


def test_named_rebeccapurple():
    out = extract_colors("color: rebeccapurple;")
    assert out == [{"model": "named", "value": "rebeccapurple"}]


def test_named_cornflowerblue():
    out = extract_colors("color: cornflowerblue;")
    assert out == [{"model": "named", "value": "cornflowerblue"}]


def test_named_coral():
    out = extract_colors("border: 1px solid coral;")
    assert out == [{"model": "named", "value": "coral"}]


def test_named_case_insensitive():
    out = extract_colors("color: REBECCAPURPLE;")
    assert out == [{"model": "named", "value": "rebeccapurple"}]


def test_named_uses_longest_match():
    """``mediumaquamarine`` beats ``aquamarine`` and ``cadetblue``
    beats ``blue`` (if blue were in the catalogue)."""
    out = extract_colors("color: mediumaquamarine;")
    # Should be ONE entry, not multiple, and should be the long form.
    assert out == [{"model": "named", "value": "mediumaquamarine"}]


# ---- Excluded prose words ---------------------------------------


def test_named_red_rejected_as_prose():
    """``red`` is too common in prose to be a colour-extractor target."""
    out = extract_colors("The red car drove away.")
    assert out == []


def test_named_blue_rejected_as_prose():
    out = extract_colors("She felt blue today.")
    assert out == []


def test_named_green_rejected_as_prose():
    out = extract_colors("He's a green developer.")
    assert out == []


def test_named_black_rejected_as_prose():
    out = extract_colors("The black box theory")
    assert out == []


def test_named_white_rejected_as_prose():
    out = extract_colors("White noise filled the room.")
    assert out == []


def test_named_yellow_rejected_as_prose():
    out = extract_colors("She was yellow with envy.")
    assert out == []


def test_named_gray_grey_rejected_as_prose():
    out = extract_colors("Gray hair and grey skies.")
    assert out == []


# ---- Real-world combinations -----------------------------------


def test_css_rule_block():
    text = """
    .button {
      background: #ff5733;
      color: #ffffff;
      border: 1px solid rgba(0, 0, 0, 0.2);
    }
    """
    out = extract_colors(text)
    models = [c["model"] for c in out]
    values = [c["value"] for c in out]
    assert "hex" in models
    assert "rgb" in models
    assert "#ff5733" in values
    assert "#ffffff" in values


def test_tailwind_config_palette():
    text = """
    colors: {
      primary: "#3490dc",
      secondary: "#ffed4a",
      danger: "#e3342f",
    }
    """
    out = extract_colors(text)
    assert len(out) == 3
    assert all(c["model"] == "hex" for c in out)


def test_design_system_doc():
    text = """
    Brand palette:
    Primary: oklch(0.7 0.15 240)
    Accent: oklch(0.85 0.1 30)
    Background: #fafafa
    Border: rgba(0, 0, 0, 0.1)
    """
    out = extract_colors(text)
    models = [c["model"] for c in out]
    assert models.count("oklch") == 2
    assert "hex" in models
    assert "rgb" in models


def test_figma_inspector_capture():
    """A Figma-style colour-picker capture lists multiple formats
    for one colour. We treat each format as a distinct entry."""
    text = """
    Fill
    HEX: #FF5733
    RGB: rgb(255, 87, 51)
    HSL: hsl(11, 100%, 60%)
    """
    out = extract_colors(text)
    assert len(out) == 3
    models = sorted(c["model"] for c in out)
    assert models == ["hex", "hsl", "rgb"]


def test_dedup_same_color_same_format():
    """Same colour written twice in identical form collapses."""
    out = extract_colors("#ff5733 #ff5733 #ff5733")
    assert out == [{"model": "hex", "value": "#ff5733"}]


def test_no_dedup_across_different_formats():
    """Same colour in different formats stays as distinct entries."""
    out = extract_colors("#ff5733 rgb(255, 87, 51)")
    assert len(out) == 2


def test_ordering_preserved():
    """Colours come out in source-text appearance order."""
    out = extract_colors("#aaa #bbb #ccc #ddd")
    values = [c["value"] for c in out]
    assert values == ["#aaaaaa", "#bbbbbb", "#cccccc", "#dddddd"]


def test_cap_at_100_colors():
    """When 150+ unique colours detected, cap at 100."""
    # Generate 150 unique 6-digit hex codes (use the hex prefix
    # explicitly so all are valid).
    codes = []
    for i in range(150):
        # Use zero-padded 6-digit codes -- all chars are hex digits.
        codes.append(f"#{i:06x}")
    text = " ".join(codes)
    out = extract_colors(text)
    assert len(out) == 100


# ---- Pipeline integration ---------------------------------------


def test_pipeline_populates_raw_colors():
    ocr = OCRResult(text="background: #ff5733; color: rebeccapurple;")
    result = enrich(Category.code_snippet, ExtractedFields(), ocr)
    assert "colors" in result.raw
    models = [c["model"] for c in result.raw["colors"]]
    assert "hex" in models
    assert "named" in models


def test_pipeline_empty_raw_when_no_colors():
    ocr = OCRResult(text="Just plain text without any colour mentions.")
    result = enrich(Category.code_snippet, ExtractedFields(), ocr)
    assert "colors" not in (result.raw or {})


def test_pipeline_runs_for_chat_category():
    """Cross-category extractor runs even for non-code categories."""
    ocr = OCRResult(text="Use #FF5733 for the button colour.")
    result = enrich(Category.chat_screenshot, ExtractedFields(), ocr)
    assert "colors" in result.raw


def test_pipeline_runs_for_document_category():
    ocr = OCRResult(text="Brand colour: rgb(0, 51, 102)")
    result = enrich(Category.document, ExtractedFields(), ocr)
    assert "colors" in result.raw


# ---- Safety / edge cases ----------------------------------------


def test_empty_text():
    assert extract_colors("") == []


def test_none_text():
    assert extract_colors(None) == []  # type: ignore[arg-type]


def test_non_string_input():
    assert extract_colors(12345) == []  # type: ignore[arg-type]


def test_random_hex_in_url_path_rejected():
    """A bare-hex inside an OAuth state or session ID doesn't have
    the # prefix so it rejects."""
    text = "https://example.com/callback?state=abc123def456"
    out = extract_colors(text)
    assert out == []


def test_long_alphanumeric_token_with_hash_inside():
    """``#FF5733-rest`` -- the trailing `-rest` is rejected by our
    no-word-char-boundary so we capture just ``#FF5733``."""
    out = extract_colors("token: abc#FF5733-other")
    # The leading ``abc`` makes the # not at word-boundary on left
    # so we expect no match. This is intentional safety.
    assert out == [] or all(c["value"] == "#ff5733" for c in out)


def test_inline_in_text():
    """Hex inside a sentence still parses."""
    text = "The primary brand colour is #FF5733 and the accent is #336699."
    out = extract_colors(text)
    assert len(out) == 2
    assert {"model": "hex", "value": "#ff5733"} in out
    assert {"model": "hex", "value": "#336699"} in out


def test_function_in_text():
    text = "Use rgb(255, 87, 51) for the active state."
    out = extract_colors(text)
    assert out == [{"model": "rgb", "value": "rgb(255, 87, 51)"}]
