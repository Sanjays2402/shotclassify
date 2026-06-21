"""Code comment-density heuristic.

A new ``CodeFields.comment_density`` slot carries the fraction of
NON-BLANK lines in the snippet whose first non-whitespace token
opens a comment for the snippet's language. Returns a float in
``[0.0, 1.0]`` rounded to 2 decimal places.

Recognised comment leaders by language family:

* ``#`` family: Python / Ruby / Shell / Perl / Elixir / R / YAML /
  TOML / Makefile / Dockerfile.
* ``//`` family: C / C++ / Java / JS / TS / Go / Rust / C# /
  Kotlin / Swift / Scala / Dart / Groovy / PHP.
* ``--`` family: SQL / Lua / Haskell.
* ``;`` family: Lisp / Scheme / Clojure.
* ``%`` family: Erlang / MATLAB / LaTeX.
* ``<!--`` family: HTML / XML / SVG.

Block-comment openers (``/*``, ``\"\"\"``, ``'''``, ``=begin``) are
counted when they sit at the start of a line. Python triple-quoted
docstrings tag as comments on the opening line.

Pure data languages (JSON, CSV, TSV) return 0.0 because they have
no comment syntax. Unknown languages default to the ``#`` leader
because that's the most common single-char leader across
configuration / scripting files.

Blank lines are excluded from the denominator so a snippet padded
with blank rows doesn't artificially lower the density.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import detect_comment_density, enrich_code

# ---- detect_comment_density: empty / edge cases ----------------------


def test_empty_string_returns_zero():
    assert detect_comment_density("") == 0.0


def test_whitespace_only_returns_zero():
    assert detect_comment_density("   \n\n  \n") == 0.0


def test_no_language_defaults_to_hash():
    """Unknown language defaults to the ``#`` leader."""
    code = "# this is a comment\nfoo = 1\n"
    assert detect_comment_density(code) == 0.5


def test_pure_data_language_returns_zero():
    """JSON / CSV have no comment syntax -> density is always 0.0."""
    code = '{"foo": 1}\n{"bar": 2}\n'
    assert detect_comment_density(code, language="json") == 0.0


def test_text_language_falls_through_to_hash():
    """``text`` (the catchall fallback) defaults to the ``#`` leader
    because a script-like snippet whose language was undetectable is
    usually still readable with the ``#`` rule. Pure data languages
    (json / csv) zero out instead."""
    code = "# header\nplain line\n"
    assert detect_comment_density(code, language="text") == 0.5


# ---- detect_comment_density: Python -------------------------------


def test_python_no_comments():
    code = "def foo():\n    return 42\n"
    assert detect_comment_density(code, language="python") == 0.0


def test_python_one_comment_of_two():
    code = "# greet\ndef foo():\n    return 42\n"
    # 3 non-blank lines, 1 comment -> 0.33
    assert detect_comment_density(code, language="python") == 0.33


def test_python_all_comments():
    code = "# line one\n# line two\n# line three\n"
    assert detect_comment_density(code, language="python") == 1.0


def test_python_docstring_triple_quoted():
    """The ``\"\"\"`` line at the start of a function counts as comment."""
    code = '"""module docstring."""\nfoo = 1\n'
    assert detect_comment_density(code, language="python") == 0.5


def test_python_blank_lines_excluded():
    """Blank rows don't dilute the density."""
    code = "# hi\n\n\nfoo = 1\n\n\n"
    # 2 non-blank lines, 1 comment -> 0.5
    assert detect_comment_density(code, language="python") == 0.5


def test_python_indented_comment_counts():
    """Indented ``#`` lines also count as comments."""
    code = "def foo():\n    # inner comment\n    return 42\n"
    # 3 non-blank lines, 1 comment -> 0.33
    assert detect_comment_density(code, language="python") == 0.33


# ---- detect_comment_density: JS / TS / C-family --------------------


def test_javascript_double_slash():
    code = "// log result\nconsole.log(foo);\n"
    assert detect_comment_density(code, language="javascript") == 0.5


def test_typescript_double_slash():
    code = "// type guard\nfunction foo(x: number): boolean {\n  return x > 0;\n}\n"
    assert detect_comment_density(code, language="typescript") == 0.25


def test_javascript_block_comment_start():
    """``/*`` at the start of a line counts."""
    code = "/* license */\nconsole.log('hi');\n"
    assert detect_comment_density(code, language="javascript") == 0.5


def test_go_double_slash():
    code = "// main entry\npackage main\nfunc main() {}\n"
    assert detect_comment_density(code, language="go") == 0.33


def test_rust_double_slash():
    code = "// outer\nfn main() {\n    println!(\"hi\");\n}\n"
    assert detect_comment_density(code, language="rust") == 0.25


def test_java_double_slash():
    code = "// note\npublic class Foo {\n  public static void main(String[] args) {}\n}\n"
    assert detect_comment_density(code, language="java") == 0.25


def test_csharp_double_slash():
    code = "// header\nusing System;\nclass Foo {}\n"
    assert detect_comment_density(code, language="c#") == 0.33


def test_swift_double_slash():
    code = "// note\nimport Foundation\nlet x = 1\n"
    assert detect_comment_density(code, language="swift") == 0.33


def test_php_accepts_both_slash_and_hash():
    """PHP allows ``//`` and ``#`` as line-comment leaders."""
    code = "<?php\n# old style\n// modern style\necho 'hi';\n"
    # 4 non-blank lines, 2 comments -> 0.5
    assert detect_comment_density(code, language="php") == 0.5


# ---- detect_comment_density: SQL / Lua / Haskell -------------------


def test_sql_double_dash():
    code = "-- list users\nSELECT * FROM users;\n"
    assert detect_comment_density(code, language="sql") == 0.5


def test_lua_double_dash():
    code = "-- entry\nlocal x = 1\nprint(x)\n"
    assert detect_comment_density(code, language="lua") == 0.33


def test_haskell_double_dash():
    code = "-- top\nmain :: IO ()\nmain = putStrLn \"hi\"\n"
    assert detect_comment_density(code, language="haskell") == 0.33


# ---- detect_comment_density: Lisp family ---------------------------


def test_lisp_semicolon():
    code = ";; header\n(defun foo () 42)\n"
    assert detect_comment_density(code, language="lisp") == 0.5


def test_clojure_semicolon():
    code = ";; note\n(defn foo [] 42)\n"
    assert detect_comment_density(code, language="clojure") == 0.5


# ---- detect_comment_density: Erlang / MATLAB -----------------------


def test_erlang_percent():
    code = "% header\nfoo() -> 42.\n"
    assert detect_comment_density(code, language="erlang") == 0.5


def test_matlab_percent():
    code = "% setup\nx = 1;\ndisp(x)\n"
    assert detect_comment_density(code, language="matlab") == 0.33


# ---- detect_comment_density: HTML / XML ----------------------------


def test_html_xml_comment():
    code = "<!-- header -->\n<html>\n<body>hi</body>\n</html>\n"
    # 4 non-blank lines, 1 comment -> 0.25
    assert detect_comment_density(code, language="html") == 0.25


def test_xml_comment():
    code = "<!-- root -->\n<config>\n  <value>1</value>\n</config>\n"
    assert detect_comment_density(code, language="xml") == 0.25


# ---- detect_comment_density: shell / yaml --------------------------


def test_shell_hash():
    code = "#!/bin/bash\n# helper\necho hello\n"
    # 3 non-blank lines; the shebang + comment count as comments,
    # leaving the echo as the only code line -> 0.67.
    assert detect_comment_density(code, language="bash") == 0.67


def test_yaml_hash():
    code = "# config file\nkey: value\nlist:\n  - one\n"
    assert detect_comment_density(code, language="yaml") == 0.25


def test_dockerfile_hash():
    code = "# Dockerfile\nFROM python:3.11\nWORKDIR /app\n"
    assert detect_comment_density(code, language="dockerfile") == 0.33


# ---- detect_comment_density: rounding -----------------------------


def test_rounding_to_two_decimals():
    """1/3 of lines as comments rounds to 0.33."""
    code = "# c\nfoo = 1\nbar = 2\n"
    assert detect_comment_density(code, language="python") == 0.33


def test_one_seventh_rounding():
    """1/7 rounds to 0.14."""
    code = "# c\n" + "\n".join(f"x{i} = {i}" for i in range(6)) + "\n"
    assert detect_comment_density(code, language="python") == 0.14


# ---- detect_comment_density: prefix-only matching ------------------


def test_inline_comment_does_not_count():
    """``foo = 1  # inline`` is NOT counted -- only line-leading."""
    code = "foo = 1  # inline\nbar = 2\n"
    assert detect_comment_density(code, language="python") == 0.0


def test_leading_whitespace_doesnt_stop_match():
    """``  # indented`` still starts with ``#`` after whitespace strip."""
    code = "if True:\n    # branch\n    foo = 1\n"
    assert detect_comment_density(code, language="python") == 0.33


# ---- enrich_code: wiring ------------------------------------------


def test_enrich_code_sets_comment_density_for_python():
    code = "# header\nfoo = 1\n"
    out = enrich_code(None, OCRResult(text=code))
    assert out.comment_density == 0.5


def test_enrich_code_sets_comment_density_for_javascript():
    code = "// header\nconsole.log('hi');\n"
    out = enrich_code(None, OCRResult(text=code))
    assert out.comment_density == 0.5


def test_enrich_code_zero_density_for_pure_code():
    code = "def foo():\n    return 42\n"
    out = enrich_code(None, OCRResult(text=code))
    assert out.comment_density == 0.0


def test_enrich_code_caller_supplied_density_wins():
    """Caller-supplied non-zero density is preserved."""
    existing = CodeFields(language="python", code="# c\nfoo = 1\n", comment_density=0.99)
    ocr = OCRResult(text="# c\nfoo = 1\n")
    out = enrich_code(existing, ocr)
    assert out.comment_density == 0.99


def test_enrich_code_zero_density_recomputed():
    """A 0.0 caller value triggers recompute (also yields 0.0 here)."""
    existing = CodeFields(language="python", code="foo = 1\n", comment_density=0.0)
    ocr = OCRResult(text="foo = 1\n")
    out = enrich_code(existing, ocr)
    assert out.comment_density == 0.0


def test_enrich_code_uses_detected_language():
    """When language is not provided, it's detected from the code."""
    code = "// header\nconsole.log('hi');\n"
    out = enrich_code(None, OCRResult(text=code))
    assert out.language is not None
    # Detector should pick javascript or typescript; either way the
    # // leader works.
    assert out.comment_density == 0.5


# ---- LLM wire-format passthrough ----------------------------------


def test_llm_wire_format_passes_through_comment_density():
    from shotclassify_classify.client import _parse_llm_payload

    payload = {
        "primary": "code_snippet",
        "confidences": [{"category": "code_snippet", "score": 0.9}],
        "rationale": "test",
        "fields": {
            "code": {
                "language": "python",
                "code": "# c\nfoo = 1\n",
                "line_count": 2,
                "comment_density": 0.5,
            }
        },
    }
    _, fields = _parse_llm_payload(payload)
    assert fields.code is not None
    assert fields.code.comment_density == 0.5


def test_llm_wire_format_defaults_density_to_zero():
    from shotclassify_classify.client import _parse_llm_payload

    payload = {
        "primary": "code_snippet",
        "confidences": [{"category": "code_snippet", "score": 0.9}],
        "rationale": "test",
        "fields": {
            "code": {
                "language": "python",
                "code": "foo = 1\n",
            }
        },
    }
    _, fields = _parse_llm_payload(payload)
    assert fields.code is not None
    assert fields.code.comment_density == 0.0
