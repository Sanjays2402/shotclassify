"""TODO author extraction tests.

A new ``CodeFields.todo_authors`` slot surfaces ``MARKER(author):``
forms found in commented code lines. Each entry is a
``{"marker", "author"}`` dict preserving first-seen order; dedupe
is intentionally NOT done because the same author may legitimately
own multiple TODOs in one snippet.

Recognised markers (case-sensitive ALL-CAPS):

  TODO, FIXME, XXX, HACK, BUG, NOTE, OPTIMIZE

Recognised forms:

  # TODO(alice): hook up retries
  // FIXME(bob): off-by-one
  /* HACK(carol-87): rewrite once we drop py3.9 */
  ; XXX(@dave): clean up

Pure data languages (json / csv / tsv) return an empty list.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import enrich_code, extract_todo_authors

# ---- Basic per-marker tests --------------------------------------


def test_python_todo_author():
    code = "# TODO(alice): hook up retries\nx = 1\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "TODO", "author": "alice"}]


def test_python_fixme_author():
    code = "# FIXME(bob): off-by-one\nfor i in range(10): pass\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "FIXME", "author": "bob"}]


def test_python_xxx_author():
    code = "# XXX(charlie): clean up\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "XXX", "author": "charlie"}]


def test_python_hack_author():
    code = "# HACK(diana): rewrite later\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "HACK", "author": "diana"}]


def test_python_bug_author():
    code = "# BUG(erin): leaks memory\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "BUG", "author": "erin"}]


def test_python_note_author():
    code = "# NOTE(frank): see RFC 7231\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "NOTE", "author": "frank"}]


def test_python_optimize_author():
    code = "# OPTIMIZE(grace): use bisect\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "OPTIMIZE", "author": "grace"}]


# ---- Different comment leader styles ----------------------------


def test_js_double_slash_leader():
    code = "// FIXME(bob): off-by-one\nfunction foo() {}\n"
    out = extract_todo_authors(code, "javascript")
    assert out == [{"marker": "FIXME", "author": "bob"}]


def test_c_block_leader():
    code = "/* HACK(carol-87): rewrite once we drop py3.9 */\nint main() {}\n"
    out = extract_todo_authors(code, "c")
    assert out == [{"marker": "HACK", "author": "carol-87"}]


def test_lisp_semicolon_leader():
    code = "; XXX(@dave): clean up\n(defn foo [] nil)\n"
    out = extract_todo_authors(code, "clojure")
    assert out == [{"marker": "XXX", "author": "@dave"}]


def test_sql_double_dash_leader():
    code = "-- TODO(eve): add index on user_id\nSELECT * FROM users;\n"
    out = extract_todo_authors(code, "sql")
    assert out == [{"marker": "TODO", "author": "eve"}]


def test_elixir_percent_leader():
    # Elixir uses % only in special contexts; the catalogue
    # registers # for Elixir comments.
    code = "# NOTE(frank): see Plug.Conn docs\n"
    out = extract_todo_authors(code, "elixir")
    assert out == [{"marker": "NOTE", "author": "frank"}]


def test_no_language_defaults_to_hash_leader():
    code = "# TODO(alice): hook up retries\n"
    out = extract_todo_authors(code, None)
    assert out == [{"marker": "TODO", "author": "alice"}]


# ---- Author handle variants -----------------------------------


def test_github_at_prefix_preserved():
    code = "# TODO(@alice): see issue #42\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "TODO", "author": "@alice"}]


def test_author_with_digits():
    code = "# TODO(user42): bump version\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "TODO", "author": "user42"}]


def test_author_with_hyphen():
    code = "# HACK(carol-87): rewrite once we drop py3.9\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "HACK", "author": "carol-87"}]


def test_author_with_underscore():
    code = "# TODO(alice_bob): split responsibility\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "TODO", "author": "alice_bob"}]


def test_author_with_period():
    code = "# TODO(alice.smith): see her ticket\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "TODO", "author": "alice.smith"}]


def test_author_with_email():
    code = "# TODO(alice@example.com): ping for review\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "TODO", "author": "alice@example.com"}]


def test_author_with_full_name_no_handle():
    code = "# TODO(Alice Smith): hook up retries\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "TODO", "author": "Alice Smith"}]


def test_author_with_colon_inside_paren_drops_at_colon():
    # The matcher consumes everything up to the closing paren so
    # ``TODO(2024-01:alice)`` captures the full ``2024-01:alice``
    # as the author. We don't try to parse out date/handle splits
    # because there's no canonical convention.
    code = "# TODO(2024-01:alice): post-launch cleanup\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "TODO", "author": "2024-01:alice"}]


# ---- Whitespace and trailing-punctuation handling -------------


def test_leading_whitespace_stripped():
    code = "# TODO(  alice): hook up retries\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "TODO", "author": "alice"}]


def test_trailing_whitespace_stripped():
    code = "# TODO(alice  ): hook up retries\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "TODO", "author": "alice"}]


def test_trailing_comma_stripped():
    code = "# TODO(alice,): hook up retries\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "TODO", "author": "alice"}]


def test_empty_paren_rejected():
    code = "# TODO(): hook up retries\n"
    out = extract_todo_authors(code, "python")
    assert out == []


def test_whitespace_only_paren_rejected():
    code = "# TODO(   ): hook up retries\n"
    out = extract_todo_authors(code, "python")
    # The matcher needs at least 1 character inside parens; the
    # 3-space content passes the {1,64} bound but then strips to
    # empty -> rejected.
    assert out == []


# ---- Marker not in a comment ----------------------------------


def test_marker_not_in_comment_ignored():
    # ``TODO(alice)`` outside a commented line is not an action
    # marker -- it could be a function name, a literal, or noise.
    code = "TODO(alice): hook up\n"
    out = extract_todo_authors(code, "python")
    assert out == []


def test_marker_in_code_string_not_extracted_when_no_leader():
    # A string literal containing ``# TODO(alice)`` IS extracted
    # because we don't tokenise -- documented trade-off mirrored
    # from detect_todo_count.
    code = 'x = "# TODO(alice): fix this"\n'
    out = extract_todo_authors(code, "python")
    # The line contains a ``#`` so the matcher fires; this is
    # the documented overcount.
    assert out == [{"marker": "TODO", "author": "alice"}]


# ---- Multiple authors / markers per line / file ---------------


def test_multiple_markers_per_line():
    code = "# TODO(alice): one  FIXME(bob): two\n"
    out = extract_todo_authors(code, "python")
    assert out == [
        {"marker": "TODO", "author": "alice"},
        {"marker": "FIXME", "author": "bob"},
    ]


def test_multiple_markers_per_file():
    code = (
        "# TODO(alice): hook retries\n"
        "x = 1\n"
        "# FIXME(bob): off-by-one\n"
        "y = 2\n"
        "# HACK(carol): rewrite\n"
    )
    out = extract_todo_authors(code, "python")
    assert out == [
        {"marker": "TODO", "author": "alice"},
        {"marker": "FIXME", "author": "bob"},
        {"marker": "HACK", "author": "carol"},
    ]


def test_same_author_multiple_todos_not_deduped():
    code = (
        "# TODO(alice): first\n"
        "# TODO(alice): second\n"
        "# FIXME(alice): third\n"
    )
    out = extract_todo_authors(code, "python")
    # Three distinct TODOs for alice -- dedupe is intentionally NOT
    # done because we want the count to be accurate per dashboard.
    assert out == [
        {"marker": "TODO", "author": "alice"},
        {"marker": "TODO", "author": "alice"},
        {"marker": "FIXME", "author": "alice"},
    ]


def test_first_seen_order_preserved():
    code = (
        "# OPTIMIZE(grace): use bisect\n"
        "# TODO(alice): hook retries\n"
    )
    out = extract_todo_authors(code, "python")
    assert out == [
        {"marker": "OPTIMIZE", "author": "grace"},
        {"marker": "TODO", "author": "alice"},
    ]


# ---- Marker rejection conditions ------------------------------


def test_lowercase_marker_rejected():
    code = "# todo(alice): hook up retries\n"
    out = extract_todo_authors(code, "python")
    assert out == []


def test_mixed_case_marker_rejected():
    code = "# Todo(alice): hook up retries\n"
    out = extract_todo_authors(code, "python")
    assert out == []


def test_no_paren_after_marker_rejected():
    code = "# TODO alice: hook up retries\n"
    out = extract_todo_authors(code, "python")
    assert out == []


def test_marker_substring_rejected():
    # ``TODOIST`` is not a marker.
    code = "# TODOIST(alice): some note\n"
    out = extract_todo_authors(code, "python")
    assert out == []


# ---- Pure data languages return empty ------------------------


def test_json_returns_empty():
    code = '{"todo": "TODO(alice): fix"}\n'
    out = extract_todo_authors(code, "json")
    assert out == []


def test_csv_returns_empty():
    code = "a,b,c\nTODO(alice),x,y\n"
    out = extract_todo_authors(code, "csv")
    assert out == []


# ---- Empty input ---------------------------------------------


def test_empty_string():
    assert extract_todo_authors("", "python") == []


def test_whitespace_only():
    assert extract_todo_authors("   \n\n   ", "python") == []


def test_no_markers():
    code = "# Just a comment\nx = 1\n"
    out = extract_todo_authors(code, "python")
    assert out == []


# ---- enrich_code integration --------------------------------


def test_enrich_code_populates_todo_authors():
    code = "# TODO(alice): hook up retries\n# FIXME(bob): off-by-one\n"
    ocr = OCRResult(text=code)
    out = enrich_code(None, ocr)
    assert out.todo_authors == [
        {"marker": "TODO", "author": "alice"},
        {"marker": "FIXME", "author": "bob"},
    ]


def test_enrich_code_caller_supplied_wins():
    code = "# TODO(alice): hook up retries\n"
    ocr = OCRResult(text=code)
    pre = CodeFields(
        code=code,
        todo_authors=[{"marker": "TODO", "author": "caller-supplied"}],
    )
    out = enrich_code(pre, ocr)
    assert out.todo_authors == [
        {"marker": "TODO", "author": "caller-supplied"}
    ]


def test_enrich_code_empty_todo_authors_recomputed():
    code = "# TODO(alice): hook up retries\n"
    ocr = OCRResult(text=code)
    pre = CodeFields(code=code, todo_authors=[])
    out = enrich_code(pre, ocr)
    assert out.todo_authors == [{"marker": "TODO", "author": "alice"}]


def test_enrich_code_no_markers_stays_empty():
    code = "x = 1\nprint(x)\n"
    ocr = OCRResult(text=code)
    out = enrich_code(None, ocr)
    assert out.todo_authors == []


# ---- Real-world contexts -----------------------------------


def test_python_module_with_mixed_todos():
    code = '''
"""A short module summary."""

# TODO(alice): hook up retries
# This is a regular comment
# FIXME(bob): off-by-one in the binary search

def foo():
    # HACK(carol): rewrite once we drop py3.9
    return 1
'''
    out = extract_todo_authors(code, "python")
    assert out == [
        {"marker": "TODO", "author": "alice"},
        {"marker": "FIXME", "author": "bob"},
        {"marker": "HACK", "author": "carol"},
    ]


def test_typescript_module_with_jsdoc_and_todos():
    code = '''
/**
 * A short summary.
 */

// TODO(@alice): hook up the new endpoint
function foo() {
  // FIXME(bob-123): off-by-one on indexing
  return 1;
}
'''
    out = extract_todo_authors(code, "typescript")
    assert out == [
        {"marker": "TODO", "author": "@alice"},
        {"marker": "FIXME", "author": "bob-123"},
    ]


def test_inline_trailing_comment_with_author():
    code = "x = compute()  # TODO(alice): optimize this\n"
    out = extract_todo_authors(code, "python")
    assert out == [{"marker": "TODO", "author": "alice"}]


# ---- Cap defence -------------------------------------------


def test_cap_at_50():
    # Build 60 distinct author-tagged TODOs.
    code = "\n".join(
        f"# TODO(user{i:03d}): item {i}" for i in range(60)
    )
    out = extract_todo_authors(code, "python")
    assert len(out) == 50
