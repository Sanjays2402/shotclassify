"""Minified / bundled JS detection.

A new ``CodeFields.minified`` boolean flags snippets that look like
minified or bundled JavaScript / TypeScript output. Dashboards use
this to surface "looks bundled" annotations so a reviewer knows not
to read the snippet line-by-line.

Signals combined by the detector:

* known bundler preambles (webpack runtime, ``!function(...){...}()``
  IIFE wrappers, ``var __webpack_modules__`` markers),
* average non-empty line length > 250 chars OR any line > 500 chars,
* < 30% of ``;`` / ``{`` / ``}`` separators followed by a newline
  (hand-written code newlines after most of these).

The detector returns ``False`` unconditionally for non-JS languages
because the heuristic is tuned to bundle output -- a 2000-char SQL
query is not "minified" in this sense.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import detect_minified_js, enrich_code

# ---- detect_minified_js helper --------------------------------------


def test_empty_returns_false():
    assert detect_minified_js("") is False
    assert detect_minified_js("   ") is False


def test_pretty_printed_js_is_not_minified():
    code = """function add(a, b) {
    return a + b;
}

function sub(a, b) {
    return a - b;
}
"""
    assert detect_minified_js(code, "javascript") is False


def test_webpack_preamble_detected():
    """A snippet that opens with the webpack runtime is minified."""
    code = "(self.webpackChunkapp=self.webpackChunkapp||[]).push([[179],{...}]);"
    assert detect_minified_js(code, "javascript") is True


def test_webpack_bootstrap_detected():
    code = "/******/(function(modules){ /* webpackBootstrap */ ... })([])"
    assert detect_minified_js(code, "javascript") is True


def test_iife_bang_function_detected():
    """The ``!function(){...}()`` IIFE pattern is bundle output."""
    code = "!function(t,e){\"object\"==typeof exports&&\"object\"==typeof module?module.exports=e():\"function\"==typeof define&&define.amd?define([],e):\"object\"==typeof exports?exports.lib=e():t.lib=e()}(self,(function(){return n={}}))"  # noqa: E501
    assert detect_minified_js(code, "javascript") is True


def test_long_single_line_minified():
    """One ~1000-char line with no inline newlines is minified."""
    # Build a synthetic bundle: 50 statements packed onto one line.
    body = ";".join(f"var x{i}={i}" for i in range(50))
    code = "(function(){" + body + ";return x0+x49;})();"
    assert detect_minified_js(code, "javascript") is True


def test_short_pretty_code_returns_false():
    code = "var x = 1;\nvar y = 2;\nreturn x + y;\n"
    assert detect_minified_js(code, "javascript") is False


def test_no_separators_returns_false():
    """A snippet with zero JS separators is not minified."""
    code = "just a single line of plain prose without code separators"
    assert detect_minified_js(code, "javascript") is False


def test_high_separator_newline_ratio_returns_false():
    """If most separators have a newline after them, it's hand-written."""
    code = "var a = 1;\nvar b = 2;\nvar c = 3;\nvar d = 4;\nvar e = 5;\n"
    # Avg line length is small AND ratio is high -> not minified.
    assert detect_minified_js(code, "javascript") is False


def test_long_pretty_function_returns_false():
    """A long but pretty-printed function should NOT be flagged."""
    # 50 lines, each short, each ending in a separator with newline.
    code = "function foo() {\n" + "".join(
        f"    var x{i} = {i};\n" for i in range(50)
    ) + "}\n"
    assert detect_minified_js(code, "javascript") is False


def test_python_long_line_returns_false_with_language():
    """Python with a long line is NOT minified per our heuristic.

    Pass language='python' and we short-circuit to False.
    """
    code = "x = " + "1 + " * 200 + "1\n"
    assert detect_minified_js(code, "python") is False


def test_python_long_line_with_no_language_returns_false_too():
    """Without a language hint, a long Python line with one
    statement and one separator still falls through the rule because
    the avg line length AND low newline-ratio gate both apply.
    """
    # Python doesn't use semicolons / braces much so sep_total == 0
    # and the detector returns False.
    code = "x = " + "1 + " * 200 + "1\n"
    assert detect_minified_js(code) is False


def test_typescript_minified_detected():
    """TypeScript bundles get the same treatment as JS bundles."""
    code = "(self.webpackChunkapp=self.webpackChunkapp||[]).push([[179],{...}]);"
    assert detect_minified_js(code, "typescript") is True


def test_max_len_above_500_with_low_newline_ratio_detected():
    """One giant line above the 500-char branch even when other lines
    are short triggers minified.
    """
    short_comments = "// sourcemap\n// build: 2026\n"
    giant_line = "var " + ",".join(f"x{i}={i}" for i in range(120)) + ";"
    assert len(giant_line) > 500
    code = short_comments + giant_line
    assert detect_minified_js(code, "javascript") is True


def test_minified_marker_comment_detected():
    """The literal ``// minified`` annotation forces True."""
    code = "// minified\nfunction f() { return 1; }\n"
    assert detect_minified_js(code, "javascript") is True


def test_jsx_minified_detected():
    """jsx language tag is also handled like javascript."""
    code = "(self.webpackChunkapp=self.webpackChunkapp||[]).push([[179],{...}]);"
    assert detect_minified_js(code, "jsx") is True


def test_tsx_minified_detected():
    code = "(self.webpackChunkapp=self.webpackChunkapp||[]).push([[179],{...}]);"
    assert detect_minified_js(code, "tsx") is True


# ---- enrich_code wiring ----------------------------------------------


def test_enrich_code_pretty_js_minified_false():
    code = "function add(a, b) {\n    return a + b;\n}\n"
    out = enrich_code(None, OCRResult(text=code))
    assert out.minified is False


def test_enrich_code_bundle_minified_true():
    code = "(self.webpackChunkapp=self.webpackChunkapp||[]).push([[179],{...}]);"
    out = enrich_code(None, OCRResult(text=code))
    # detect_language may tag this as javascript via the const/let/function
    # needles; even if it falls through to pygments, the bundler-preamble
    # match still fires when language is js-family.
    assert out.language in {"javascript", "typescript"} or out.language is not None
    # Force language so we can assert minified independently of pygments.
    out2 = enrich_code(
        CodeFields(language="javascript", code=code), OCRResult(text=code)
    )
    assert out2.minified is True


def test_enrich_code_caller_supplied_minified_preserved():
    """An LLM that already said ``minified=True`` is respected even
    when our heuristic would say False.
    """
    existing = CodeFields(
        language="javascript",
        code="function add(a, b) { return a + b; }",
        minified=True,
    )
    out = enrich_code(existing, OCRResult(text=existing.code))
    assert out.minified is True


def test_enrich_code_python_minified_false():
    """Python snippet should never get flagged minified."""
    out = enrich_code(None, OCRResult(text="def add(a, b):\n    return a + b\n"))
    assert out.minified is False


def test_enrich_code_long_template_literal_not_minified():
    """A long template literal in pretty code should NOT trigger
    minified because the newline-after-separator ratio stays high.
    """
    code = (
        "function render() {\n"
        "    const s = `" + "x" * 600 + "`;\n"
        "    return s;\n"
        "}\n"
    )
    out = enrich_code(
        CodeFields(language="javascript", code=code), OCRResult(text=code)
    )
    # max line length > 500 but the surrounding code has high newline ratio.
    # The detector ANDs both conditions, so this returns False.
    assert out.minified is False
