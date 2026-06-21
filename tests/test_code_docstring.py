"""Code docstring / JSDoc extraction.

A new ``CodeFields.docstring`` slot carries the top-level
documentation block found at the start of the snippet:

* Python triple-quoted docstrings (``\"\"\"...\"\"\"`` / ``'''...'''``)
  either at module level (the very first non-blank statement) or as
  the first statement inside the first top-level ``def`` / ``class``
  body. Single-line and multi-line forms are both accepted.
* JSDoc-style ``/** ... */`` blocks immediately above the first
  top-level declaration (``function`` / ``class`` / ``func`` /
  ``fn`` / ``const`` / etc). The ``/**`` / ``*/`` delimiters and
  per-line ``*`` continuation prefixes are stripped so the surfaced
  body reads as natural prose.
* Rust ``///`` line-doc-comments (collapsed) and ``//!`` inner-doc
  comments.

Stored as the cleaned docstring body; ``None`` when no docstring
is present.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import detect_docstring, enrich_code

# ---- detect_docstring: empty / edge cases -------------------------


def test_empty_string_returns_none():
    assert detect_docstring("") is None


def test_whitespace_only_returns_none():
    assert detect_docstring("   \n\n  \n") is None


def test_plain_code_returns_none():
    code = "x = 1\nprint(x)\n"
    assert detect_docstring(code, language="python") is None


def test_line_comment_only_returns_none():
    """A regular comment is not a docstring."""
    code = "# This is a regular comment.\nx = 1\n"
    assert detect_docstring(code, language="python") is None


# ---- Python: module-level docstring ------------------------------


def test_python_module_docstring_single_line():
    code = '"""Summary line."""\nimport os\n'
    assert detect_docstring(code, language="python") == "Summary line."


def test_python_module_docstring_single_quotes():
    code = "'''Single-quoted docstring.'''\nimport os\n"
    assert detect_docstring(code, language="python") == "Single-quoted docstring."


def test_python_module_docstring_multi_line():
    code = '"""Summary.\n\nLonger description here.\n"""\nimport os\n'
    body = detect_docstring(code, language="python")
    assert body is not None
    assert body.startswith("Summary.")
    assert "Longer description here." in body


def test_python_module_docstring_with_leading_blank_lines():
    code = '\n\n"""Top of module."""\nimport os\n'
    assert detect_docstring(code, language="python") == "Top of module."


def test_python_module_docstring_after_shebang_and_encoding():
    code = '#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n"""Top of module."""\nimport os\n'
    assert detect_docstring(code, language="python") == "Top of module."


# ---- Python: function-level docstring ----------------------------


def test_python_function_docstring():
    code = 'def foo():\n    """Do something."""\n    return 1\n'
    assert detect_docstring(code, language="python") == "Do something."


def test_python_class_docstring():
    code = 'class Foo:\n    """A class."""\n    pass\n'
    assert detect_docstring(code, language="python") == "A class."


def test_python_function_docstring_with_decorators():
    code = (
        "@app.route('/')\n"
        "@cache.memoize()\n"
        "def index():\n"
        '    """Render the index page."""\n'
        "    return 'hi'\n"
    )
    assert detect_docstring(code, language="python") == "Render the index page."


def test_python_async_function_docstring():
    code = (
        "async def fetch():\n"
        '    """Fetch resource asynchronously."""\n'
        "    return 42\n"
    )
    assert detect_docstring(code, language="python") == "Fetch resource asynchronously."


def test_python_function_without_docstring_returns_none():
    code = "def foo():\n    return 1\n"
    assert detect_docstring(code, language="python") is None


def test_python_multiline_function_docstring_dedented():
    code = (
        "def foo():\n"
        '    """Summary.\n'
        "\n"
        "    Longer description.\n"
        '    """\n'
        "    return 1\n"
    )
    body = detect_docstring(code, language="python")
    assert body is not None
    # Dedented: should NOT carry the 4-space indent from the surrounding block.
    assert "    Longer description" not in body
    assert "Longer description" in body


# ---- JSDoc: function above ---------------------------------------


def test_jsdoc_block_above_function():
    code = (
        "/**\n"
        " * Add two numbers.\n"
        " *\n"
        " * @param a First number.\n"
        " * @param b Second number.\n"
        " */\n"
        "function add(a, b) {\n"
        "  return a + b;\n"
        "}\n"
    )
    body = detect_docstring(code, language="javascript")
    assert body is not None
    assert body.startswith("Add two numbers.")
    assert "@param a First number." in body


def test_jsdoc_block_above_class():
    code = (
        "/** A widget class. */\n"
        "class Widget {\n"
        "  constructor() {}\n"
        "}\n"
    )
    assert detect_docstring(code, language="javascript") == "A widget class."


def test_jsdoc_block_above_const():
    code = (
        "/** Singleton instance. */\n"
        "const instance = new Foo();\n"
    )
    assert detect_docstring(code, language="javascript") == "Singleton instance."


def test_jsdoc_block_above_let():
    code = (
        "/** Default config. */\n"
        "let config = { debug: true };\n"
    )
    assert detect_docstring(code, language="javascript") == "Default config."


def test_jsdoc_block_above_export():
    code = (
        "/** Public API. */\n"
        "export function api() {}\n"
    )
    assert detect_docstring(code, language="typescript") == "Public API."


def test_jsdoc_block_above_typescript_interface():
    code = (
        "/** Represents a user. */\n"
        "interface User {\n"
        "  name: string;\n"
        "}\n"
    )
    assert detect_docstring(code, language="typescript") == "Represents a user."


def test_jsdoc_above_type_alias():
    code = (
        "/** A nullable string. */\n"
        "type MaybeStr = string | null;\n"
    )
    assert detect_docstring(code, language="typescript") == "A nullable string."


def test_jsdoc_block_above_go_func():
    code = (
        "/** Package main. */\n"
        "func main() {\n"
        "  fmt.Println(\"hi\")\n"
        "}\n"
    )
    assert detect_docstring(code, language="go") == "Package main."


def test_jsdoc_block_above_rust_fn():
    code = (
        "/** Compute something. */\n"
        "fn compute() -> i32 {\n"
        "  42\n"
        "}\n"
    )
    assert detect_docstring(code, language="rust") == "Compute something."


def test_jsdoc_block_above_java_class():
    code = (
        "/**\n"
        " * Represents a person.\n"
        " */\n"
        "public class Person {\n"
        "  public String name;\n"
        "}\n"
    )
    body = detect_docstring(code, language="java")
    assert body == "Represents a person."


def test_jsdoc_block_with_continuation_asterisks():
    code = (
        "/**\n"
        " * First sentence.\n"
        " * Second sentence.\n"
        " *\n"
        " * Third paragraph.\n"
        " */\n"
        "function foo() {}\n"
    )
    body = detect_docstring(code, language="javascript")
    assert body is not None
    assert "First sentence." in body
    assert "Second sentence." in body
    assert "Third paragraph." in body
    # The leading * markers should not survive.
    assert "*" not in body


def test_jsdoc_single_line_form():
    code = "/** One-liner. */\nfunction foo() {}\n"
    assert detect_docstring(code, language="javascript") == "One-liner."


def test_jsdoc_floating_with_no_following_declaration_returns_none():
    """A /** ... */ block with no top-level decl after it is not a docstring."""
    code = "/** Just a hovering note. */\n// some unrelated comment\n"
    assert detect_docstring(code, language="javascript") is None


def test_jsdoc_block_followed_by_decorator_then_class():
    """Decorators between docblock and class are recognised as part of the declaration."""
    code = (
        "/** Component summary. */\n"
        "@Component({ selector: 'app' })\n"
        "export class App {}\n"
    )
    body = detect_docstring(code, language="typescript")
    assert body == "Component summary."


# ---- Rust: line-doc comments -------------------------------------


def test_rust_triple_slash_above_fn():
    code = (
        "/// Square a number.\n"
        "fn square(x: i32) -> i32 {\n"
        "    x * x\n"
        "}\n"
    )
    assert detect_docstring(code, language="rust") == "Square a number."


def test_rust_triple_slash_multiline_above_fn():
    code = (
        "/// First line.\n"
        "/// Second line.\n"
        "///\n"
        "/// Third paragraph.\n"
        "pub fn foo() {}\n"
    )
    body = detect_docstring(code, language="rust")
    assert body is not None
    assert "First line." in body
    assert "Second line." in body
    assert "Third paragraph." in body


def test_rust_inner_doc_at_module_top():
    """``//!`` doc comments often sit at the top of a module without a follow."""
    code = "//! Crate-level documentation.\n//! Spans multiple lines.\nuse std::io;\n"
    body = detect_docstring(code, language="rust")
    assert body is not None
    assert "Crate-level documentation." in body


def test_rust_triple_slash_with_no_following_decl_returns_none():
    code = "/// Floating doc.\n// regular comment, no decl.\n"
    assert detect_docstring(code, language="rust") is None


def test_rust_with_jsdoc_falls_back():
    """A Rust snippet with a JSDoc-style block also gets a docstring."""
    code = (
        "/** Doc via JSDoc. */\n"
        "fn foo() {}\n"
    )
    body = detect_docstring(code, language="rust")
    assert body == "Doc via JSDoc."


# ---- language-agnostic default ordering --------------------------


def test_no_language_jsdoc_wins():
    code = (
        "/** Mixed file. */\n"
        "function foo() {}\n"
    )
    assert detect_docstring(code) == "Mixed file."


def test_no_language_python_docstring():
    code = '"""Top of module."""\nimport os\n'
    assert detect_docstring(code) == "Top of module."


# ---- enrich_code wiring ------------------------------------------


def _ocr(text: str) -> OCRResult:
    return OCRResult(text=text, language="en", word_count=len(text.split()))


def test_enrich_code_pulls_python_docstring():
    code = '"""Hello world."""\nimport os\n'
    fields = enrich_code(None, _ocr(code))
    assert fields.docstring == "Hello world."


def test_enrich_code_pulls_jsdoc():
    code = "/** Summary. */\nfunction foo() {}\n"
    fields = enrich_code(None, _ocr(code))
    assert fields.docstring == "Summary."


def test_enrich_code_caller_value_wins():
    """A caller-supplied docstring is preserved verbatim."""
    code = '"""Auto-detected."""\nimport os\n'
    existing = CodeFields(code=code, docstring="LLM-supplied summary.")
    fields = enrich_code(existing, _ocr(code))
    assert fields.docstring == "LLM-supplied summary."


def test_enrich_code_no_docstring_stays_none():
    code = "x = 1\nprint(x)\n"
    fields = enrich_code(None, _ocr(code))
    assert fields.docstring is None


def test_enrich_code_docstring_with_other_fields():
    """Docstring extraction coexists with language detection and other detectors."""
    code = (
        "/**\n"
        " * Square a number.\n"
        " *\n"
        " * @param x The input.\n"
        " * @returns The square.\n"
        " */\n"
        "function square(x) {\n"
        "  return x * x;\n"
        "}\n"
    )
    fields = enrich_code(None, _ocr(code))
    assert fields.docstring is not None
    assert "Square a number." in fields.docstring
    assert fields.language == "javascript"


# ---- robustness --------------------------------------------------


def test_python_docstring_with_blank_lines_in_body():
    code = (
        'def foo():\n'
        '    """First line.\n'
        "\n"
        "    Paragraph two.\n"
        "\n"
        "    Paragraph three.\n"
        '    """\n'
        "    return 1\n"
    )
    body = detect_docstring(code, language="python")
    assert body is not None
    assert "First line." in body
    assert "Paragraph two." in body
    assert "Paragraph three." in body


def test_jsdoc_with_javadoc_tags_preserved():
    """JavaDoc-style ``@param`` tags survive cleaning."""
    code = (
        "/**\n"
        " * Compute thing.\n"
        " * @param x The first arg.\n"
        " * @return The result.\n"
        " */\n"
        "function thing(x) { return x; }\n"
    )
    body = detect_docstring(code, language="javascript")
    assert body is not None
    assert "@param x The first arg." in body
    assert "@return The result." in body


def test_python_docstring_caller_zero_string_recomputes():
    """A caller-supplied None docstring triggers detection."""
    code = '"""Detected."""\nimport os\n'
    existing = CodeFields(code=code, docstring=None)
    fields = enrich_code(existing, _ocr(code))
    assert fields.docstring == "Detected."


def test_python_docstring_deeper_than_window_returns_none():
    """A docstring on line 200 is not picked up because we cap the window."""
    pre = "\n".join(["x = 1"] * 80)
    code = f'{pre}\n"""Too late."""\n'
    assert detect_docstring(code, language="python") is None


def test_jsdoc_inside_function_body_not_top_level():
    """A JSDoc block buried inside a function body is not the top-level docstring."""
    code = (
        "function outer() {\n"
        "  /** Inner block. */\n"
        "  function inner() {}\n"
        "}\n"
    )
    # The first /**...*/ sits indented inside the outer function, not at top
    # level. We don't try to track indentation depth, but we DO require a
    # following declaration. The inner function does follow it, so this will
    # tag as "Inner block." -- an acceptable trade-off documented in STATE.md.
    body = detect_docstring(code, language="javascript")
    assert body == "Inner block."


def test_jsdoc_above_first_top_level_only():
    """We tag the FIRST docstring/decl, not subsequent ones."""
    code = (
        "/** First. */\n"
        "function alpha() {}\n"
        "\n"
        "/** Second. */\n"
        "function beta() {}\n"
    )
    assert detect_docstring(code, language="javascript") == "First."


def test_python_quotes_in_docstring_body_preserved():
    """Body text containing quote chars survives extraction."""
    code = '"""He said \'hi\' to me."""\nimport os\n'
    assert detect_docstring(code, language="python") == "He said 'hi' to me."


def test_python_unicode_in_docstring():
    """Non-ASCII docstring body is preserved verbatim."""
    code = '"""Café résumé naïve."""\nimport os\n'
    assert detect_docstring(code, language="python") == "Café résumé naïve."
