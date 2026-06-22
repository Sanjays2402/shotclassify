"""TODO / FIXME ticket-link extraction tests.

Many codebases include a JIRA / GitHub-issue / Linear / Asana ticket
reference alongside a TODO so the comment links back to the work
item:

  # TODO(JIRA-1234): wire up retry logic
  // FIXME: ABC-99 - off-by-one
  /* HACK: see #issue-42 */
  // TODO PROJ-100 deprecate this once Foo is replaced

The new ``CodeFields.todo_tickets`` slot captures these as a list of
``{"marker", "ticket"}`` dicts. Three ticket shapes recognised:

* JIRA-style PROJECT-NUMBER (JIRA-1234, ABC-99, ENG-455)
* GitHub-style hash-number (#1234, #42)
* Hash-slug (#issue-42, #bug-99)

Distinct from ``todo_authors`` which captures ``MARKER(author)``
human handles.
"""
from __future__ import annotations

from shotclassify_common import Category, CodeFields, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_todo_tickets

# ---- JIRA-style tickets ---------------------------------------


def test_jira_basic():
    code = "# TODO JIRA-1234 fix retry\n"
    assert extract_todo_tickets(code) == [
        {"marker": "TODO", "ticket": "JIRA-1234"}
    ]


def test_jira_with_short_project():
    code = "# TODO ABC-99 off-by-one\n"
    assert extract_todo_tickets(code) == [
        {"marker": "TODO", "ticket": "ABC-99"}
    ]


def test_jira_with_long_project():
    code = "# FIXME PROJECTID-12345 issue\n"
    assert extract_todo_tickets(code) == [
        {"marker": "FIXME", "ticket": "PROJECTID-12345"}
    ]


def test_jira_in_parentheses_form():
    code = "# TODO(JIRA-1234): wire up retry\n"
    result = extract_todo_tickets(code)
    assert len(result) == 1
    assert result[0]["marker"] == "TODO"
    assert result[0]["ticket"] == "JIRA-1234"


def test_jira_in_jsdoc_block():
    code = "/* HACK: see ABC-42 */\n"
    result = extract_todo_tickets(code, language="javascript")
    assert len(result) == 1
    assert result[0]["marker"] == "HACK"
    assert result[0]["ticket"] == "ABC-42"


def test_jira_in_js_double_slash():
    code = "// FIXME: ABC-99 - off-by-one\n"
    result = extract_todo_tickets(code, language="javascript")
    assert len(result) == 1
    assert result[0]["ticket"] == "ABC-99"


# ---- GitHub-style hash-number tickets -------------------------


def test_hash_number_basic():
    code = "# TODO #1234 buy bread\n"
    assert extract_todo_tickets(code) == [
        {"marker": "TODO", "ticket": "#1234"}
    ]


def test_hash_number_in_jsdoc():
    code = "/* TODO: closes #42 */\n"
    result = extract_todo_tickets(code, language="javascript")
    assert len(result) == 1
    assert result[0]["ticket"] == "#42"


def test_hash_number_short():
    code = "// FIXME #1\n"
    result = extract_todo_tickets(code, language="javascript")
    assert len(result) == 1
    assert result[0]["ticket"] == "#1"


def test_hash_number_in_python_comment():
    code = "# TODO #99 - rewrite this\n"
    result = extract_todo_tickets(code, language="python")
    assert len(result) == 1
    assert result[0]["ticket"] == "#99"


# ---- Hash-slug tickets ----------------------------------------


def test_hash_slug_basic():
    code = "# TODO see #issue-42 for details\n"
    result = extract_todo_tickets(code)
    assert len(result) == 1
    assert result[0]["marker"] == "TODO"
    assert result[0]["ticket"] == "#issue-42"


def test_hash_slug_bug():
    code = "# FIXME #bug-99\n"
    result = extract_todo_tickets(code)
    assert len(result) == 1
    assert result[0]["ticket"] == "#bug-99"


def test_hash_slug_in_jsdoc():
    code = "/* HACK: blocked by #ticket-100 */\n"
    result = extract_todo_tickets(code, language="javascript")
    assert len(result) == 1
    assert result[0]["ticket"] == "#ticket-100"


# ---- All 7 markers --------------------------------------------


def test_marker_todo():
    code = "# TODO JIRA-1\nx = 1\n"
    assert extract_todo_tickets(code)[0]["marker"] == "TODO"


def test_marker_fixme():
    code = "# FIXME JIRA-1\nx = 1\n"
    assert extract_todo_tickets(code)[0]["marker"] == "FIXME"


def test_marker_xxx():
    code = "# XXX JIRA-1\nx = 1\n"
    assert extract_todo_tickets(code)[0]["marker"] == "XXX"


def test_marker_hack():
    code = "# HACK JIRA-1\nx = 1\n"
    assert extract_todo_tickets(code)[0]["marker"] == "HACK"


def test_marker_bug():
    code = "# BUG JIRA-1\nx = 1\n"
    assert extract_todo_tickets(code)[0]["marker"] == "BUG"


def test_marker_note():
    code = "# NOTE JIRA-1\nx = 1\n"
    assert extract_todo_tickets(code)[0]["marker"] == "NOTE"


def test_marker_optimize():
    code = "# OPTIMIZE JIRA-1\nx = 1\n"
    assert extract_todo_tickets(code)[0]["marker"] == "OPTIMIZE"


# ---- Multiple tickets per marker line -------------------------


def test_multiple_jira_one_line():
    code = "# TODO JIRA-1 and JIRA-2 both blocked\n"
    result = extract_todo_tickets(code)
    assert len(result) == 2
    assert {r["ticket"] for r in result} == {"JIRA-1", "JIRA-2"}


def test_jira_and_hash_one_line():
    code = "# TODO JIRA-1 closes #42\n"
    result = extract_todo_tickets(code)
    assert len(result) == 2
    tickets = {r["ticket"] for r in result}
    assert "JIRA-1" in tickets
    assert "#42" in tickets


def test_multiple_lines_each_marker():
    code = (
        "# TODO JIRA-1 fix retry\n"
        "x = 1\n"
        "# FIXME ABC-99 off-by-one\n"
    )
    result = extract_todo_tickets(code)
    assert len(result) == 2
    assert result[0] == {"marker": "TODO", "ticket": "JIRA-1"}
    assert result[1] == {"marker": "FIXME", "ticket": "ABC-99"}


# ---- Priority: JIRA wins over hash-num --------------------------


def test_jira_not_misread_as_hash_num():
    # JIRA-1234 should not also produce ticket "#1234" via the
    # hash-num matcher because JIRA-1234 doesn't have a # prefix.
    code = "# TODO JIRA-1234\n"
    result = extract_todo_tickets(code)
    assert len(result) == 1
    assert result[0]["ticket"] == "JIRA-1234"


def test_hash_slug_not_misread_as_hash_num():
    # #issue-42 should land as the slug form, not also as #42.
    code = "# TODO #issue-42\n"
    result = extract_todo_tickets(code)
    assert len(result) == 1
    assert result[0]["ticket"] == "#issue-42"


# ---- Marker discipline: ALL-CAPS only --------------------------


def test_lowercase_todo_rejected():
    code = "# todo JIRA-1\nx = 1\n"
    assert extract_todo_tickets(code) == []


def test_mixed_case_todo_rejected():
    code = "# Todo JIRA-1\nx = 1\n"
    assert extract_todo_tickets(code) == []


def test_todoist_not_misread_as_marker():
    code = "# TODOIST JIRA-1\nx = 1\n"
    # TODOIST has trailing alphanumerics so it's not a marker.
    assert extract_todo_tickets(code) == []


def test_xxxx_not_misread_as_marker():
    code = "# XXXX JIRA-1\nx = 1\n"
    assert extract_todo_tickets(code) == []


# ---- Comment-leader discipline ---------------------------------


def test_marker_outside_comment_rejected():
    # TODO outside a comment context isn't an action marker.
    code = "x = TODO_JIRA_1\n"
    assert extract_todo_tickets(code) == []


def test_python_hash_leader_works():
    code = "# TODO JIRA-1\n"
    assert len(extract_todo_tickets(code, language="python")) == 1


def test_javascript_double_slash_works():
    code = "// TODO JIRA-1\n"
    assert len(extract_todo_tickets(code, language="javascript")) == 1


def test_block_comment_works():
    code = "/* TODO JIRA-1 fix this */\n"
    assert len(extract_todo_tickets(code, language="javascript")) == 1


def test_sql_dash_dash_leader():
    code = "-- TODO JIRA-1\n"
    assert len(extract_todo_tickets(code, language="sql")) == 1


def test_ruby_hash_leader():
    code = "# TODO JIRA-1\n"
    assert len(extract_todo_tickets(code, language="ruby")) == 1


# ---- Pure data languages return empty -------------------------


def test_json_returns_empty():
    code = '{"todo": "TODO JIRA-1"}\n'
    assert extract_todo_tickets(code, language="json") == []


def test_csv_returns_empty():
    code = "name,note\nfoo,TODO JIRA-1\n"
    assert extract_todo_tickets(code, language="csv") == []


def test_tsv_returns_empty():
    code = "col1\tcol2\nTODO\tJIRA-1\n"
    assert extract_todo_tickets(code, language="tsv") == []


# ---- Edge cases -----------------------------------------------


def test_empty_code():
    assert extract_todo_tickets("") == []


def test_whitespace_only_code():
    assert extract_todo_tickets("   \n  \n") == []


def test_code_without_markers():
    code = "x = 1\ny = 2\n# Just a comment\n"
    assert extract_todo_tickets(code) == []


def test_marker_without_ticket():
    # A TODO without any ticket reference produces no entries.
    code = "# TODO: fix this\n"
    assert extract_todo_tickets(code) == []


def test_jira_pure_digit_project_rejected():
    # JIRA project tags must be letters; "123-456" is not a ticket.
    code = "# TODO 123-456\n"
    assert extract_todo_tickets(code) == []


def test_jira_lowercase_project_rejected():
    # JIRA project tags require ALL-CAPS letters.
    code = "# TODO abc-99\n"
    assert extract_todo_tickets(code) == []


def test_jira_too_long_project_rejected():
    # Project tag bounded at 10 chars.
    code = "# TODO ABCDEFGHIJKL-1\n"
    assert extract_todo_tickets(code) == []


def test_hash_num_too_long_rejected():
    # Hash-num bounded at 6 digits.
    code = "# TODO #1234567890\n"
    # The regex only captures 1..6 digits; trailing digits cause
    # the boundary check to fail. Document: this returns empty.
    # Actually \d{1,6} matches greedily 6 digits, then \b checks
    # boundary. A 10-digit run has \b failing after the 6th
    # digit (because the 7th is a word char). So no match.
    assert extract_todo_tickets(code) == []


def test_dedupe_not_done_intentionally():
    # The same JIRA ticket appearing on multiple lines produces
    # multiple entries.
    code = (
        "# TODO JIRA-1 fix\n"
        "x = 1\n"
        "# FIXME JIRA-1 still broken\n"
    )
    result = extract_todo_tickets(code)
    assert len(result) == 2
    assert all(r["ticket"] == "JIRA-1" for r in result)


# ---- Last marker wins on multi-marker line --------------------


def test_last_marker_attribution():
    # When a line has TWO markers, the later one is used.
    code = "# TODO and FIXME JIRA-1\n"
    result = extract_todo_tickets(code)
    assert len(result) == 1
    assert result[0]["marker"] == "FIXME"


# ---- Cap at 50 -----------------------------------------------


def test_cap_at_50():
    code = "\n".join([f"# TODO JIRA-{i}" for i in range(60)])
    result = extract_todo_tickets(code)
    assert len(result) == 50


# ---- CodeFields integration -----------------------------------


def test_enrich_pipeline_populates_todo_tickets():
    code = (
        "def foo():\n"
        "    # TODO JIRA-1234 hook up retry\n"
        "    return None\n"
        "def bar():\n"
        "    # FIXME #99 off-by-one\n"
        "    return None\n"
    )
    fields = ExtractedFields(code=CodeFields(code=code, language="python"))
    ocr = OCRResult(text=code)
    enriched = enrich(Category.code_snippet, fields, ocr)
    assert enriched.code is not None
    assert len(enriched.code.todo_tickets) == 2
    tickets = {t["ticket"] for t in enriched.code.todo_tickets}
    assert "JIRA-1234" in tickets
    assert "#99" in tickets


def test_enrich_pipeline_preserves_caller_tickets():
    code = "# TODO JIRA-1234 fix\n"
    caller = [{"marker": "TODO", "ticket": "CUSTOM-1"}]
    fields = ExtractedFields(
        code=CodeFields(code=code, language="python", todo_tickets=caller)
    )
    ocr = OCRResult(text=code)
    enriched = enrich(Category.code_snippet, fields, ocr)
    assert enriched.code is not None
    assert enriched.code.todo_tickets == caller


def test_enrich_pipeline_backfills_empty():
    code = "# TODO JIRA-42\n"
    fields = ExtractedFields(
        code=CodeFields(code=code, language="python", todo_tickets=[])
    )
    ocr = OCRResult(text=code)
    enriched = enrich(Category.code_snippet, fields, ocr)
    assert enriched.code is not None
    assert len(enriched.code.todo_tickets) == 1


def test_schema_default_empty():
    cf = CodeFields()
    assert cf.todo_tickets == []


def test_schema_accepts_list_of_dicts():
    cf = CodeFields(
        todo_tickets=[
            {"marker": "TODO", "ticket": "JIRA-1"},
            {"marker": "FIXME", "ticket": "#99"},
        ]
    )
    assert len(cf.todo_tickets) == 2


# ---- Coexistence with todo_authors ----------------------------


def test_author_and_ticket_on_same_marker():
    # TODO(alice) #1234 -- should populate BOTH todo_authors AND
    # todo_tickets.
    code = "# TODO(alice): #1234 fix it\n"
    fields = ExtractedFields(code=CodeFields(code=code, language="python"))
    ocr = OCRResult(text=code)
    enriched = enrich(Category.code_snippet, fields, ocr)
    assert enriched.code is not None
    assert len(enriched.code.todo_authors) == 1
    assert enriched.code.todo_authors[0]["author"] == "alice"
    assert len(enriched.code.todo_tickets) == 1
    assert enriched.code.todo_tickets[0]["ticket"] == "#1234"


# ---- Real-world cases -----------------------------------------


def test_realistic_python_module():
    code = (
        "import asyncio\n"
        "\n"
        "async def fetch(url):\n"
        "    # TODO ENG-455 add timeout\n"
        "    # FIXME(bob): #1234 race condition under load\n"
        "    return await http.get(url)\n"
        "\n"
        "# NOTE GH-789 covers the rewrite\n"
        "# HACK PROJ-100 remove once Foo is replaced\n"
    )
    result = extract_todo_tickets(code, language="python")
    tickets = [r["ticket"] for r in result]
    assert "ENG-455" in tickets
    assert "#1234" in tickets
    assert "GH-789" in tickets
    assert "PROJ-100" in tickets


def test_realistic_typescript_module():
    code = (
        "function processOrders() {\n"
        "    // TODO PROD-42 add retry logic\n"
        "    // FIXME: #1001 - validate input\n"
        "    /* HACK: see #ticket-99 */\n"
        "    return null;\n"
        "}\n"
    )
    result = extract_todo_tickets(code, language="typescript")
    tickets = [r["ticket"] for r in result]
    assert "PROD-42" in tickets
    assert "#1001" in tickets
    assert "#ticket-99" in tickets


def test_realistic_sql():
    code = (
        "-- TODO DB-15 add index for query optimisation\n"
        "-- BUG SLOW-99 N+1 query pattern below\n"
        "SELECT * FROM users WHERE active = true;\n"
    )
    result = extract_todo_tickets(code, language="sql")
    tickets = [r["ticket"] for r in result]
    assert "DB-15" in tickets
    assert "SLOW-99" in tickets


def test_no_false_positive_on_negative_number():
    # A negative number like "-1234" shouldn't be tagged as a ticket.
    code = "# TODO: handle -1234 case\n"
    result = extract_todo_tickets(code)
    # The hash-num matcher requires # prefix so -1234 doesn't match.
    # The JIRA matcher requires ALL-CAPS prefix so "1234" alone doesn't match.
    assert result == []


def test_no_false_positive_on_html_color():
    # "#FF0000" looks like a hash-num but has 6 hex digits, not pure
    # digits. The hash-num regex is \d{1,6} which doesn't include hex
    # letters.
    code = "# TODO: change color to #FF0000\n"
    result = extract_todo_tickets(code)
    assert result == []


def test_jira_in_url_extracted():
    # Documented trade-off: a URL like https://jira.example.com/browse/JIRA-1234
    # WILL have its trailing "JIRA-1234" captured. We accept this
    # because the JIRA matcher is intentionally permissive (the
    # surrounding URL chrome doesn't change what the ticket is).
    code = "# TODO see https://jira.example.com/browse/JIRA-1234 for details\n"
    result = extract_todo_tickets(code)
    assert len(result) == 1
    assert result[0]["ticket"] == "JIRA-1234"


def test_multiple_markers_separate_lines():
    code = (
        "# TODO JIRA-1\n"
        "# TODO JIRA-2\n"
        "# TODO JIRA-3\n"
    )
    result = extract_todo_tickets(code)
    assert len(result) == 3
    assert [r["ticket"] for r in result] == ["JIRA-1", "JIRA-2", "JIRA-3"]


def test_hash_num_with_word_boundary():
    # "#1234abc" should not capture "#1234" because the trailing chars
    # fail the word boundary check.
    code = "# TODO #1234abc\n"
    result = extract_todo_tickets(code)
    # The \d{1,6}\b means the digit run must be word-bounded.
    # In "#1234abc", \d{1,6} matches "1234" then \b checks if "a"
    # is non-word; "a" IS a word char so no boundary.
    assert result == []
