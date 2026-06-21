"""Code TODO / FIXME marker counting.

A new ``CodeFields.todo_count`` slot carries the count of
TODO / FIXME / XXX / HACK / BUG / NOTE / OPTIMIZE action-comment
markers in the snippet. Useful for code-review screenshots where
a reviewer wants to surface "this file has 7 TODOs" annotations
without re-reading the snippet line by line.

Marker matching rules:

1. ALL-CAPS spelling (case-sensitive). Prose mentions of the
   lowercase word ``bug`` / ``note`` / ``hack`` do NOT count.
2. Must be preceded somewhere on the same line by a comment
   leader for the language (or ``#`` for unknown languages).
3. Followed by a non-alphanumeric / non-underscore boundary so
   ``TODOIST`` / ``BUGGY`` / ``XXXX`` do NOT count.

Multiple markers on the same line count separately. Pure data
languages (JSON / CSV / TSV) return 0 because they have no
comment syntax.

Markers inside string literals are NOT excluded because we don't
tokenise -- this is a conservative overcount we accept as the
trade-off for keeping the detector deterministic and fast.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import detect_todo_count, enrich_code

# ---- detect_todo_count: empty / edge cases -------------------------


def test_empty_string_returns_zero():
    assert detect_todo_count("") == 0


def test_whitespace_only_returns_zero():
    assert detect_todo_count("   \n\n  \n") == 0


def test_no_comments_returns_zero():
    code = "def foo():\n    return 42\n"
    assert detect_todo_count(code, language="python") == 0


def test_pure_data_language_returns_zero():
    """JSON / CSV have no comment syntax -> count is always 0."""
    code = '{"todo": "TODO: not a real comment"}\n'
    assert detect_todo_count(code, language="json") == 0
    assert detect_todo_count(code, language="csv") == 0


# ---- detect_todo_count: each marker -------------------------------


def test_todo_marker():
    assert detect_todo_count("# TODO: fix this\n", language="python") == 1


def test_fixme_marker():
    assert detect_todo_count("# FIXME: broken\n", language="python") == 1


def test_xxx_marker():
    assert detect_todo_count("# XXX dangerous\n", language="python") == 1


def test_hack_marker():
    assert detect_todo_count("# HACK: workaround\n", language="python") == 1


def test_bug_marker():
    assert detect_todo_count("# BUG: known issue\n", language="python") == 1


def test_note_marker():
    assert detect_todo_count("# NOTE: see docs\n", language="python") == 1


def test_optimize_marker():
    assert detect_todo_count("# OPTIMIZE: O(n^2)\n", language="python") == 1


# ---- detect_todo_count: multiple markers -------------------------


def test_multiple_markers_same_line():
    """Multiple markers on the same line each count."""
    assert detect_todo_count("# TODO / FIXME / XXX combined\n", language="python") == 3


def test_multiple_markers_different_lines():
    code = (
        "# TODO: first\n"
        "def foo():\n"
        "    # FIXME: second\n"
        "    pass\n"
        "# XXX: third\n"
    )
    assert detect_todo_count(code, language="python") == 3


def test_repeated_same_marker_counts_each():
    code = "# TODO TODO TODO\n"
    assert detect_todo_count(code, language="python") == 3


# ---- detect_todo_count: language families ------------------------


def test_javascript_slash_slash_marker():
    assert detect_todo_count("// TODO: fix later\n", language="javascript") == 1


def test_typescript_slash_slash_marker():
    code = "function foo() {\n  // FIXME: type\n  return null;\n}\n"
    assert detect_todo_count(code, language="typescript") == 1


def test_java_slash_slash_marker():
    assert detect_todo_count("// TODO\n", language="java") == 1


def test_go_slash_slash_marker():
    assert detect_todo_count("// TODO: refactor\n", language="go") == 1


def test_rust_slash_slash_marker():
    assert detect_todo_count("// TODO: handle error\n", language="rust") == 1


def test_kotlin_slash_slash_marker():
    assert detect_todo_count("// TODO: coroutine\n", language="kotlin") == 1


def test_swift_slash_slash_marker():
    assert detect_todo_count("// TODO: ui polish\n", language="swift") == 1


def test_csharp_slash_slash_marker():
    assert detect_todo_count("// TODO: nullable\n", language="c#") == 1


def test_cpp_slash_slash_marker():
    assert detect_todo_count("// TODO: memory\n", language="c++") == 1


def test_ruby_hash_marker():
    assert detect_todo_count("# TODO: gem\n", language="ruby") == 1


def test_shell_hash_marker():
    assert detect_todo_count("# TODO: ci\n", language="shell") == 1


def test_yaml_hash_marker():
    assert detect_todo_count("# TODO: env\nfoo: 1\n", language="yaml") == 1


def test_sql_dash_dash_marker():
    assert detect_todo_count("-- TODO: index\n", language="sql") == 1


def test_lua_dash_dash_marker():
    assert detect_todo_count("-- TODO: refactor\n", language="lua") == 1


def test_haskell_dash_dash_marker():
    assert detect_todo_count("-- TODO: types\n", language="haskell") == 1


def test_lisp_semicolon_marker():
    assert detect_todo_count(";; TODO: refactor\n", language="lisp") == 1


def test_clojure_semicolon_marker():
    assert detect_todo_count(";; TODO\n", language="clojure") == 1


def test_php_double_slash_marker():
    assert detect_todo_count("// TODO: refactor\n", language="php") == 1


def test_php_hash_marker():
    """PHP accepts both ``//`` and ``#`` as comment leaders."""
    assert detect_todo_count("# TODO: legacy\n", language="php") == 1


def test_erlang_percent_marker():
    assert detect_todo_count("% TODO: gen_server\n", language="erlang") == 1


# ---- detect_todo_count: boundary / negative cases ----------------


def test_inline_marker_after_code():
    """``foo = 1  # TODO`` should count the TODO inline."""
    code = "foo = 1  # TODO: rename\n"
    assert detect_todo_count(code, language="python") == 1


def test_lowercase_todo_does_not_count():
    """Prose mention of lowercase ``todo`` is not a marker."""
    code = "# todo: but written as prose\n"
    assert detect_todo_count(code, language="python") == 0


def test_lowercase_bug_does_not_count():
    code = "# this fixes the bug we noticed\n"
    assert detect_todo_count(code, language="python") == 0


def test_todoist_does_not_count():
    """``TODOIST`` is a longer identifier -- not a marker."""
    code = "# TODOIST is a product name\n"
    assert detect_todo_count(code, language="python") == 0


def test_buggy_does_not_count():
    code = "# BUGGY behaviour we should address\n"
    assert detect_todo_count(code, language="python") == 0


def test_xxxx_does_not_count():
    """Four-X identifier is a longer token; doesn't trigger the XXX marker."""
    code = "# XXXX placeholder header\n"
    assert detect_todo_count(code, language="python") == 0


def test_marker_outside_comment_does_not_count():
    """A bare ``TODO`` not preceded by a comment leader doesn't count.
    The line must have a comment opener somewhere before the marker."""
    code = "TODO = 'a variable name in code'\n"
    assert detect_todo_count(code, language="python") == 0


def test_marker_in_string_literal_still_counts_when_in_comment():
    """We don't tokenise -- a TODO inside a string inside a comment
    still counts. Documented trade-off."""
    code = "# the marker 'TODO' inside quotes still counts\n"
    assert detect_todo_count(code, language="python") == 1


# ---- detect_todo_count: unknown language fallback ----------------


def test_unknown_language_falls_back_to_hash():
    """No language specified -> use ``#`` as the leader."""
    assert detect_todo_count("# TODO: configure\n") == 1


def test_unknown_explicit_language_falls_back_to_hash():
    """An explicit but unknown language tag still uses the ``#`` leader."""
    assert detect_todo_count("# TODO: fix\n", language="banana_lang") == 1


def test_text_language_uses_hash():
    assert detect_todo_count("# TODO: notes\n", language="text") == 1


# ---- enrich_code integration -------------------------------------


def test_enrich_code_populates_todo_count_python():
    existing = CodeFields(language="python", code="# TODO: a\n# FIXME: b\nx = 1\n")
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.todo_count == 2


def test_enrich_code_zero_when_no_markers():
    existing = CodeFields(language="python", code="def f():\n    return 1\n")
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.todo_count == 0


def test_enrich_code_preserves_caller_supplied_todo_count():
    """LLM-supplied todo_count wins over the heuristic."""
    existing = CodeFields(
        language="python",
        code="# TODO: a\n# TODO: b\n",  # heuristic would see 2
        todo_count=99,  # LLM said 99
    )
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.todo_count == 99


def test_enrich_code_recomputes_when_caller_value_is_default_zero():
    """A caller that explicitly passes 0 -> we recount. The behaviour
    is consistent: if the recount yields 0 we keep 0; if the recount
    yields a real value we use it."""
    existing = CodeFields(language="python", code="# TODO: recount me\n", todo_count=0)
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.todo_count == 1


def test_enrich_code_strips_numbered_gutter_before_counting():
    """The line-numbering gutter is stripped FIRST so the TODO marker
    inside a copy-pasted numbered listing still counts."""
    existing = CodeFields(
        language="python",
        code="1: # TODO: numbered listing\n2: x = 1\n3: y = 2\n",
    )
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.numbered is True
    assert merged.todo_count == 1


def test_enrich_code_javascript_multiple_markers():
    existing = CodeFields(
        language="javascript",
        code=(
            "// TODO: refactor\n"
            "function foo() {\n"
            "  // FIXME: memory\n"
            "  return null;\n"
            "}\n"
            "// XXX dangerous\n"
        ),
    )
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.todo_count == 3


def test_enrich_code_sql_marker():
    existing = CodeFields(
        language="sql",
        code="-- TODO: add index on user_id\nSELECT * FROM users;\n",
    )
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.todo_count == 1


def test_enrich_code_json_returns_zero():
    """JSON has no comment syntax -> 0 even with markers in strings."""
    existing = CodeFields(
        language="json",
        code='{"todo": "TODO: fix", "fixme": "FIXME: now"}\n',
    )
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.todo_count == 0


def test_enrich_code_unknown_language_uses_hash_leader():
    existing = CodeFields(language=None, code="# TODO: configure\n")
    merged = enrich_code(existing, OCRResult(text=""))
    # Unknown language gets the ``#`` default; TODO counts.
    assert merged.todo_count == 1


def test_enrich_code_field_independent_from_comment_density():
    """A snippet with one TODO and 10 non-comment lines has both a
    low density AND a low TODO count. The two are independent
    metrics."""
    existing = CodeFields(
        language="python",
        code=(
            "# TODO: rename\n"
            "def a(): pass\n"
            "def b(): pass\n"
            "def c(): pass\n"
            "def d(): pass\n"
            "def e(): pass\n"
            "def f(): pass\n"
            "def g(): pass\n"
            "def h(): pass\n"
            "def i(): pass\n"
        ),
    )
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.todo_count == 1
    # density = 1/11 ~ 0.09
    assert 0.05 <= merged.comment_density <= 0.15


def test_enrich_code_block_comment_marker_at_start_of_line():
    """A block-comment opener at the start of a line is recognised
    as a leader. ``/* TODO ... */`` counts."""
    existing = CodeFields(
        language="javascript",
        code="/* TODO: docblock */\nfunction f() { return 1; }\n",
    )
    merged = enrich_code(existing, OCRResult(text=""))
    # The /* opener is a comment leader so the TODO inside counts.
    assert merged.todo_count == 1
