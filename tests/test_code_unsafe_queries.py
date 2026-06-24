"""SQL-injection / unsafe-query construction detection tests.

CodeFields.unsafe_queries surfaces SQL-construction call sites
that use string interpolation / concatenation instead of
parameterised binds. Five recognised kinds:
fstring / template / concat / format / interpolate.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract.code import enrich_code, extract_unsafe_queries

# ---- Empty / no-SQL cases ----------------------------------------


def test_empty_code():
    assert extract_unsafe_queries("") == []


def test_none_code():
    assert extract_unsafe_queries(None) == []  # type: ignore[arg-type]


def test_no_sql_keywords():
    code = '''def greet(name):
    return f"Hello, {name}"'''
    assert extract_unsafe_queries(code, "python") == []


def test_safe_parameterised_query():
    """Standard parameterised query -- no interpolation, no detection."""
    code = '''cursor.execute("SELECT * FROM users WHERE id = %s", (uid,))'''
    assert extract_unsafe_queries(code, "python") == []


def test_safe_named_params():
    code = '''cursor.execute("SELECT * FROM users WHERE id = :id", {"id": uid})'''
    assert extract_unsafe_queries(code, "python") == []


# ---- Python f-string detection -----------------------------------


def test_python_fstring_select():
    code = '''cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")'''
    out = extract_unsafe_queries(code, "python")
    assert len(out) == 1
    assert out[0]["kind"] == "fstring"
    assert out[0]["language"] == "python"
    assert "{user_id}" in out[0]["snippet"]


def test_python_fstring_insert():
    code = '''sql = f"INSERT INTO logs (msg) VALUES ('{message}')"
cursor.execute(sql)'''
    out = extract_unsafe_queries(code, "python")
    assert any(e["kind"] == "fstring" for e in out)


def test_python_fstring_update():
    code = '''cursor.execute(f"UPDATE users SET name = '{name}' WHERE id = {uid}")'''
    out = extract_unsafe_queries(code, "python")
    assert len(out) == 1


def test_python_fstring_delete():
    code = '''cursor.execute(f"DELETE FROM users WHERE id = {uid}")'''
    out = extract_unsafe_queries(code, "python")
    assert len(out) == 1


def test_python_fstring_uppercase_f():
    code = '''cursor.execute(F"SELECT * FROM users WHERE id = {uid}")'''
    out = extract_unsafe_queries(code, "python")
    assert len(out) == 1


def test_python_fstring_single_quote():
    code = """cursor.execute(f'SELECT * FROM users WHERE id = {uid}')"""
    out = extract_unsafe_queries(code, "python")
    assert len(out) == 1


def test_python_fstring_with_complex_interpolation():
    code = '''cursor.execute(f"SELECT * FROM {table} WHERE {col} = {val}")'''
    out = extract_unsafe_queries(code, "python")
    assert len(out) == 1


# ---- JavaScript / TypeScript template literal --------------------


def test_js_template_select():
    code = """db.query(`SELECT * FROM users WHERE id = ${userId}`)"""
    out = extract_unsafe_queries(code, "javascript")
    assert len(out) == 1
    assert out[0]["kind"] == "template"
    assert "${userId}" in out[0]["snippet"]


def test_js_template_insert():
    code = """connection.query(`INSERT INTO posts (title) VALUES ('${title}')`)"""
    out = extract_unsafe_queries(code, "javascript")
    assert len(out) == 1


def test_typescript_template_update():
    code = """await pool.query(`UPDATE users SET name = '${name}' WHERE id = ${id}`)"""
    out = extract_unsafe_queries(code, "typescript")
    assert len(out) == 1
    assert out[0]["language"] == "typescript"


def test_js_template_without_dollar_interpolation_safe():
    """Bare template literal with no ${} interpolation -- safe."""
    code = """db.query(`SELECT * FROM users`)"""
    assert extract_unsafe_queries(code, "javascript") == []


# ---- String + concatenation -------------------------------------


def test_python_concat_select():
    code = '''cursor.execute("SELECT * FROM users WHERE id = " + str(uid))'''
    out = extract_unsafe_queries(code, "python")
    assert any(e["kind"] == "concat" for e in out)


def test_js_concat_select():
    code = '''db.query("SELECT * FROM users WHERE id = " + userId)'''
    out = extract_unsafe_queries(code, "javascript")
    assert any(e["kind"] == "concat" for e in out)


def test_concat_with_attribute_access():
    code = '''query = "SELECT * FROM " + table.name'''
    out = extract_unsafe_queries(code, "python")
    assert len(out) >= 1


# ---- .format() / % formatting -----------------------------------


def test_python_format_method():
    code = '''cursor.execute("SELECT * FROM users WHERE id = {}".format(uid))'''
    out = extract_unsafe_queries(code, "python")
    assert any(e["kind"] == "format" for e in out)


def test_python_format_with_position_arg():
    code = '''cursor.execute("INSERT INTO {0} VALUES ({1})".format(table, val))'''
    out = extract_unsafe_queries(code, "python")
    assert any(e["kind"] == "format" for e in out)


def test_python_percent_format_s():
    code = '''cursor.execute("SELECT * FROM users WHERE id = %s" % uid)'''
    out = extract_unsafe_queries(code, "python")
    assert any(e["kind"] == "format" for e in out)


def test_python_percent_format_d():
    code = '''cursor.execute("SELECT * FROM users WHERE id = %d" % uid)'''
    out = extract_unsafe_queries(code, "python")
    assert any(e["kind"] == "format" for e in out)


def test_python_percent_with_tuple():
    code = '''cursor.execute("SELECT * FROM users WHERE id = %s" % (uid,))'''
    out = extract_unsafe_queries(code, "python")
    assert any(e["kind"] == "format" for e in out)


# ---- PHP / Ruby variable interpolation --------------------------


def test_php_dollar_interpolation():
    code = '''$db->query("SELECT * FROM users WHERE id = $userId");'''
    out = extract_unsafe_queries(code, "php")
    assert any(e["kind"] == "interpolate" for e in out)


def test_php_dollar_brace_interpolation():
    code = '''$db->query("SELECT * FROM users WHERE id = ${userId}");'''
    out = extract_unsafe_queries(code, "php")
    assert any(e["kind"] == "interpolate" for e in out)


def test_ruby_hash_brace_interpolation():
    code = '''db.exec("SELECT * FROM users WHERE id = #{user_id}")'''
    out = extract_unsafe_queries(code, "ruby")
    assert any(e["kind"] == "interpolate" for e in out)


def test_single_quoted_php_safe():
    """Single-quoted PHP strings don't interpolate -- safe."""
    code = """$db->query('SELECT * FROM users WHERE id = $userId');"""
    assert extract_unsafe_queries(code, "php") == []


# ---- Multi-call detection ----------------------------------------


def test_multiple_unsafe_calls():
    code = '''
cursor.execute(f"SELECT * FROM users WHERE id = {uid}")
cursor.execute(f"UPDATE users SET name = '{name}' WHERE id = {uid}")
'''
    out = extract_unsafe_queries(code, "python")
    assert len(out) == 2


def test_mixed_safe_and_unsafe():
    code = '''
# Safe
cursor.execute("SELECT * FROM users WHERE id = %s", (uid,))
# Unsafe
cursor.execute(f"DELETE FROM users WHERE id = {uid}")
'''
    out = extract_unsafe_queries(code, "python")
    assert len(out) == 1
    assert out[0]["kind"] == "fstring"


# ---- Language gating ---------------------------------------------


def test_pure_data_json_returns_empty():
    """JSON / CSV / TSV / YAML / XML are pure data -- never code."""
    code = '''{"query": "SELECT * FROM users WHERE id = 1"}'''
    assert extract_unsafe_queries(code, "json") == []


def test_pure_data_yaml_returns_empty():
    code = '''query: SELECT * FROM users WHERE id = 1'''
    assert extract_unsafe_queries(code, "yaml") == []


def test_shell_returns_empty():
    """Shell scripts are not interpolating into SQL through this matcher."""
    code = """psql -c "SELECT * FROM users WHERE id = $UID";"""
    # Shell-language: returns []
    assert extract_unsafe_queries(code, "bash") == []
    assert extract_unsafe_queries(code, "sh") == []


# ---- Snippet truncation ------------------------------------------


def test_snippet_truncated_at_200():
    long_var = "x" * 300
    code = f'''cursor.execute(f"SELECT * FROM users WHERE id = {{{long_var}}}")'''  # noqa: S608
    out = extract_unsafe_queries(code, "python")
    assert len(out) == 1
    assert len(out[0]["snippet"]) <= 200


# ---- Safety / false-positive defences ---------------------------


def test_string_with_just_format_no_sql_safe():
    """A .format() call without a SQL keyword shouldn't fire."""
    code = '''"Hello, {}".format(name)'''
    assert extract_unsafe_queries(code, "python") == []


def test_print_with_fstring_no_sql_safe():
    code = '''print(f"User {uid} logged in")'''
    assert extract_unsafe_queries(code, "python") == []


def test_string_concat_without_sql_keyword_safe():
    code = '''greeting = "Hello, " + name'''
    assert extract_unsafe_queries(code, "python") == []


def test_template_without_sql_keyword_safe():
    code = """console.log(`User ${uid} logged in`)"""
    assert extract_unsafe_queries(code, "javascript") == []


# ---- Cap at 50 entries -------------------------------------------


def test_cap_at_50_entries():
    lines = []
    for i in range(60):
        lines.append(f'cursor.execute(f"SELECT * FROM users WHERE id = {{i_{i}}}")')  # noqa: S608
    code = "\n".join(lines)
    out = extract_unsafe_queries(code, "python")
    assert len(out) == 50


# ---- enrich_code integration -------------------------------------


def test_enrich_code_writes_unsafe_queries():
    text = '''def get_user(uid):
    return cursor.execute(f"SELECT * FROM users WHERE id = {uid}")
'''
    out = enrich_code(None, OCRResult(text=text))
    assert len(out.unsafe_queries) == 1
    assert out.unsafe_queries[0]["kind"] == "fstring"


def test_enrich_code_caller_preserved():
    """Caller-supplied unsafe_queries are NOT overridden."""
    text = '''cursor.execute(f"SELECT * FROM users WHERE id = {uid}")'''
    existing = CodeFields(
        language="python",
        code=text,
        unsafe_queries=[
            {"kind": "concat", "language": "python", "snippet": "from llm"}
        ],
    )
    out = enrich_code(existing, OCRResult(text=""))
    assert len(out.unsafe_queries) == 1
    assert out.unsafe_queries[0]["snippet"] == "from llm"


def test_enrich_code_empty_for_safe_code():
    text = '''def add(a, b):
    return a + b'''
    out = enrich_code(None, OCRResult(text=text))
    assert out.unsafe_queries == []


# ---- Real-world snippet captures ---------------------------------


def test_real_world_django_view():
    text = '''from django.db import connection

def get_user_by_id(request, user_id):
    with connection.cursor() as cursor:
        # Bug: SQL injection vulnerability
        cursor.execute(f"SELECT id, name FROM users WHERE id = {user_id}")
        row = cursor.fetchone()
    return JsonResponse({"id": row[0], "name": row[1]})
'''
    out = extract_unsafe_queries(text, "python")
    assert len(out) >= 1
    assert out[0]["kind"] == "fstring"


def test_real_world_express_handler():
    text = '''app.get('/users/:id', async (req, res) => {
  const id = req.params.id;
  const result = await db.query(`SELECT * FROM users WHERE id = ${id}`);
  res.json(result.rows[0]);
});
'''
    out = extract_unsafe_queries(text, "javascript")
    assert len(out) >= 1
    assert any(e["kind"] == "template" for e in out)


def test_real_world_php_handler():
    text = '''<?php
$userId = $_GET['id'];
$result = $db->query("SELECT * FROM users WHERE id = $userId");
'''
    out = extract_unsafe_queries(text, "php")
    assert len(out) >= 1
    assert any(e["kind"] == "interpolate" for e in out)


def test_real_world_legacy_python_format():
    text = '''def search_users(query):
    sql = "SELECT * FROM users WHERE name LIKE '%{}%' ORDER BY id LIMIT 100".format(query)
    cursor.execute(sql)
    return cursor.fetchall()
'''
    out = extract_unsafe_queries(text, "python")
    assert len(out) >= 1
    assert any(e["kind"] == "format" for e in out)


def test_unknown_language_defaults_to_unknown():
    """When language is None, snippet still scanned with language='unknown'."""
    code = '''cursor.execute(f"SELECT * FROM users WHERE id = {uid}")'''
    out = extract_unsafe_queries(code, None)
    assert len(out) == 1
    assert out[0]["language"] == "unknown"
