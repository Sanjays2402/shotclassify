"""CSS vendor-prefix detection.

A new ``CodeFields.css_vendor_prefixes`` slot surfaces the unique
set of CSS vendor prefixes used in a CSS-family snippet. Each
entry is one of:

  ``-webkit-`` -- Chrome / Safari / Edge
  ``-moz-``    -- Firefox
  ``-ms-``     -- Internet Explorer / legacy Edge
  ``-o-``      -- Opera Presto
  ``-khtml-``  -- Konqueror

The detector is language-gated to CSS-family snippets (``css`` /
``scss`` / ``sass`` / ``less`` / ``stylus``) with a content-based
fallback for snippets whose language detection is incorrect:
when the snippet contains BOTH a vendor-prefix candidate AND a
CSS-like property declaration (``property: value;``) nearby, the
matcher runs even without a CSS language tag.

First-seen-in-text order preserved. Output is the prefix WITH
hyphens so dashboards can render the canonical property form
directly.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import detect_css_vendor_prefixes, enrich_code

# ---- edge cases --------------------------------------------------


def test_empty_string_returns_empty_list():
    assert detect_css_vendor_prefixes("", "css") == []


def test_whitespace_only_returns_empty_list():
    assert detect_css_vendor_prefixes("   \n  ", "css") == []


def test_no_prefix_in_css_returns_empty_list():
    code = ".btn { color: red; font-size: 14px; }"
    assert detect_css_vendor_prefixes(code, "css") == []


def test_none_language_no_content_fallback_returns_empty():
    """A bare ``-webkit-`` string with no CSS context yields nothing."""
    code = "this has -webkit-transform in it but no CSS"
    assert detect_css_vendor_prefixes(code, None) == []


# ---- Per-prefix tests --------------------------------------------


def test_webkit_prefix_detected():
    code = ".btn { -webkit-transform: scale(1.1); }"
    out = detect_css_vendor_prefixes(code, "css")
    assert out == ["-webkit-"]


def test_moz_prefix_detected():
    code = ".btn { -moz-appearance: none; }"
    out = detect_css_vendor_prefixes(code, "css")
    assert out == ["-moz-"]


def test_ms_prefix_detected():
    code = ".btn { -ms-flex: 1; }"
    out = detect_css_vendor_prefixes(code, "css")
    assert out == ["-ms-"]


def test_o_prefix_detected():
    code = ".btn { -o-transition: opacity 0.3s; }"
    out = detect_css_vendor_prefixes(code, "css")
    assert out == ["-o-"]


def test_khtml_prefix_detected():
    code = ".btn { -khtml-user-select: none; }"
    out = detect_css_vendor_prefixes(code, "css")
    assert out == ["-khtml-"]


# ---- Multi-prefix snippets ---------------------------------------


def test_multiple_prefixes_each_recorded():
    code = """
.btn {
  -webkit-transform: scale(1.1);
  -moz-appearance: none;
  -ms-flex: 1;
}
"""
    out = detect_css_vendor_prefixes(code, "css")
    assert set(out) == {"-webkit-", "-moz-", "-ms-"}


def test_all_five_prefixes_recorded():
    code = """
.legacy {
  -webkit-transition: all 0.3s;
  -moz-transition: all 0.3s;
  -ms-transition: all 0.3s;
  -o-transition: all 0.3s;
  -khtml-transition: all 0.3s;
}
"""
    out = detect_css_vendor_prefixes(code, "css")
    assert set(out) == {"-webkit-", "-moz-", "-ms-", "-o-", "-khtml-"}


def test_same_prefix_used_many_times_deduped():
    """5 -webkit- properties surface as one entry."""
    code = """
.btn {
  -webkit-transform: scale(1.1);
  -webkit-transition: all 0.3s;
  -webkit-text-fill-color: red;
  -webkit-user-select: none;
  -webkit-tap-highlight-color: transparent;
}
"""
    out = detect_css_vendor_prefixes(code, "css")
    assert out == ["-webkit-"]


def test_first_seen_order_preserved():
    code = """
.a { -moz-foo: 1; }
.b { -webkit-foo: 2; }
.c { -ms-foo: 3; }
"""
    out = detect_css_vendor_prefixes(code, "css")
    assert out == ["-moz-", "-webkit-", "-ms-"]


# ---- CSS function calls ------------------------------------------


def test_vendor_prefixed_function_call_detected():
    """``-webkit-linear-gradient(...)`` is a function form."""
    code = ".bg { background: -webkit-linear-gradient(top, red, blue); }"
    out = detect_css_vendor_prefixes(code, "css")
    assert out == ["-webkit-"]


def test_moz_keyframes_at_rule_detected():
    code = "@-moz-keyframes spin { from { } to { } }"
    out = detect_css_vendor_prefixes(code, "css")
    assert out == ["-moz-"]


# ---- Language gate -----------------------------------------------


def test_scss_language_accepted():
    code = ".btn { -webkit-transform: scale(1.1); }"
    assert detect_css_vendor_prefixes(code, "scss") == ["-webkit-"]


def test_sass_language_accepted():
    code = ".btn { -webkit-transform: scale(1.1); }"
    assert detect_css_vendor_prefixes(code, "sass") == ["-webkit-"]


def test_less_language_accepted():
    code = ".btn { -webkit-transform: scale(1.1); }"
    assert detect_css_vendor_prefixes(code, "less") == ["-webkit-"]


def test_stylus_language_accepted():
    code = ".btn { -webkit-transform: scale(1.1); }"
    assert detect_css_vendor_prefixes(code, "stylus") == ["-webkit-"]


def test_case_insensitive_language_match():
    code = ".btn { -webkit-transform: scale(1.1); }"
    assert detect_css_vendor_prefixes(code, "CSS") == ["-webkit-"]
    assert detect_css_vendor_prefixes(code, "SCSS") == ["-webkit-"]


def test_non_css_language_with_bare_substring_rejected():
    """A JS file with -webkit- in a comment is NOT CSS."""
    code = """
// browser flag table:
// -webkit-something
const flag = true;
"""
    out = detect_css_vendor_prefixes(code, "javascript")
    assert out == []


def test_python_language_with_bare_substring_rejected():
    code = '''
"""Documentation referencing -webkit-transform property."""
def foo(): pass
'''
    out = detect_css_vendor_prefixes(code, "python")
    assert out == []


# ---- Content fallback --------------------------------------------


def test_content_fallback_fires_for_mis_classified_css():
    """A CSS snippet whose language detection went wrong still tags."""
    code = ".btn { -webkit-transform: scale(1.1); -moz-appearance: none; }"
    # Pretend the language detector returned "gas" (which happens for
    # short CSS bodies sometimes).
    out = detect_css_vendor_prefixes(code, "gas")
    assert set(out) == {"-webkit-", "-moz-"}


def test_content_fallback_fires_for_none_language_with_css_context():
    code = ".btn { -webkit-transform: scale(1.1); }"
    out = detect_css_vendor_prefixes(code, None)
    assert out == ["-webkit-"]


def test_content_fallback_rejects_prose_with_no_declaration():
    """A pure-text mention of ``-webkit-`` without a CSS declaration shape."""
    code = "We removed -webkit-transform support in version 2.0"
    out = detect_css_vendor_prefixes(code, None)
    assert out == []


def test_content_fallback_window_is_local():
    """The CSS declaration must be NEAR (within 200 chars) the vendor prefix.
    A faraway random declaration shouldn't trigger the fallback."""
    pad = " " * 500  # 500 chars of padding so the declaration is far away
    code = "We removed -webkit-transform" + pad + " color: red;"
    out = detect_css_vendor_prefixes(code, None)
    assert out == []


def test_content_fallback_with_nearby_declaration_fires():
    """A vendor-prefix candidate with a nearby CSS declaration triggers."""
    code = "background: url(...); -webkit-mask-image: linear-gradient(top); color: red;"
    out = detect_css_vendor_prefixes(code, None)
    assert out == ["-webkit-"]


# ---- Negative cases ----------------------------------------------


def test_just_hyphen_word_hyphen_not_vendor_prefix():
    """A token like ``-data-foo-`` is not a vendor prefix."""
    code = ".btn { -data-foo: 1; }"
    out = detect_css_vendor_prefixes(code, "css")
    assert out == []


def test_uppercase_vendor_token_not_matched():
    """Vendor prefixes are lowercase by spec."""
    code = ".btn { -WEBKIT-transform: scale(1.1); }"
    out = detect_css_vendor_prefixes(code, "css")
    assert out == []


def test_partial_vendor_token_with_no_trailing_hyphen_rejected():
    code = ".btn { -webkittransform: scale(1.1); }"
    out = detect_css_vendor_prefixes(code, "css")
    assert out == []


def test_no_property_char_after_prefix_rejected():
    """After ``-webkit-`` we need a letter to identify a real property."""
    # A bare ``-webkit-`` followed by digit or hyphen isn't a property.
    code = ".btn { -webkit-1: 1; }"
    out = detect_css_vendor_prefixes(code, "css")
    assert out == []


# ---- enrich_code integration -------------------------------------


def test_enrich_code_populates_css_vendor_prefixes_with_explicit_lang():
    """With an explicit CSS language, the field is populated."""
    code = ".btn { -webkit-transform: scale(1.1); -moz-appearance: none; }"
    fields = enrich_code(
        CodeFields(language="css", code=code), OCRResult(text=code)
    )
    assert set(fields.css_vendor_prefixes) == {"-webkit-", "-moz-"}


def test_enrich_code_empty_prefixes_for_python():
    code = "def foo():\n    # -webkit-something noted\n    return 1\n"
    fields = enrich_code(
        CodeFields(language="python", code=code), OCRResult(text=code)
    )
    assert fields.css_vendor_prefixes == []


def test_enrich_code_caller_supplied_prefixes_wins():
    code = ".btn { -webkit-transform: scale(1.1); }"
    existing = CodeFields(
        language="css",
        code=code,
        css_vendor_prefixes=["-custom-"],
    )
    fields = enrich_code(existing, OCRResult(text=code))
    assert fields.css_vendor_prefixes == ["-custom-"]


def test_default_field_value_is_empty_list():
    fields = CodeFields()
    assert fields.css_vendor_prefixes == []


# ---- Realistic snippets ------------------------------------------


def test_realistic_legacy_button_styles():
    code = """
.button {
  display: -webkit-flex;
  display: -moz-flex;
  display: -ms-flexbox;
  display: flex;
  -webkit-transform: translateZ(0);
  -moz-transform: translateZ(0);
  -ms-transform: translateZ(0);
  -webkit-transition: all 0.3s ease;
  -moz-transition: all 0.3s ease;
  -ms-transition: all 0.3s ease;
  transition: all 0.3s ease;
}
"""
    out = detect_css_vendor_prefixes(code, "css")
    assert set(out) == {"-webkit-", "-moz-", "-ms-"}


def test_realistic_keyframe_animation():
    code = """
@-webkit-keyframes spin {
  from { -webkit-transform: rotate(0); }
  to { -webkit-transform: rotate(360deg); }
}
@-moz-keyframes spin {
  from { -moz-transform: rotate(0); }
  to { -moz-transform: rotate(360deg); }
}
"""
    out = detect_css_vendor_prefixes(code, "css")
    assert set(out) == {"-webkit-", "-moz-"}


def test_realistic_input_appearance_reset():
    code = """
input[type="search"] {
  -webkit-appearance: textfield;
  -moz-appearance: textfield;
  appearance: textfield;
}
input[type="search"]::-webkit-search-decoration {
  -webkit-appearance: none;
}
"""
    out = detect_css_vendor_prefixes(code, "css")
    assert set(out) == {"-webkit-", "-moz-"}


def test_realistic_scss_with_mixins():
    code = """
@mixin transition($props...) {
  -webkit-transition: $props;
  -moz-transition: $props;
  -o-transition: $props;
  transition: $props;
}
.btn { @include transition(color 0.3s, background 0.3s); }
"""
    out = detect_css_vendor_prefixes(code, "scss")
    assert set(out) == {"-webkit-", "-moz-", "-o-"}
