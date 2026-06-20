"""SQL dialect detection tests.

The code extractor already tags raw language as ``sql`` via Pygments /
the fast hints. The dialect detector narrows that to one of
``mysql`` / ``postgres`` / ``sqlite`` / ``mssql`` so dashboards can
group MySQL captures separately from PostgreSQL captures without an
LLM round trip.

Detection priority (FIRST match wins):
  mssql     - SELECT TOP n, NVARCHAR, GETDATE(), [col] brackets,
              WITH (NOLOCK), @@IDENTITY/@@ROWCOUNT.
  postgres  - RETURNING, $1/$N placeholders, ::TYPE casts, SERIAL,
              ILIKE, ON CONFLICT.
  mysql     - AUTO_INCREMENT, ENGINE=, `col` backtick quoting,
              LIMIT n,m, UNSIGNED, DEFAULT CHARSET=.
  sqlite    - AUTOINCREMENT (one word), PRAGMA, sqlite_master,
              WITHOUT ROWID.

Ambiguous ANSI SQL falls through to None.
"""
from __future__ import annotations

import pytest
from shotclassify_common import OCRResult
from shotclassify_extract import detect_sql_dialect, enrich_code

# ---- detect_sql_dialect helper -----------------------------------------


@pytest.mark.parametrize(
    "code,expected",
    [
        # MySQL
        ("CREATE TABLE u (id INT AUTO_INCREMENT PRIMARY KEY)", "mysql"),
        ("CREATE TABLE u (id INT) ENGINE=InnoDB", "mysql"),
        ("SELECT `name`, `email` FROM `users`", "mysql"),
        ("SELECT * FROM users LIMIT 10, 20", "mysql"),
        ("CREATE TABLE u (id INT UNSIGNED)", "mysql"),
        # PostgreSQL
        ("INSERT INTO u (name) VALUES ('x') RETURNING id", "postgres"),
        ("SELECT * FROM u WHERE id = $1", "postgres"),
        ("SELECT name::text FROM users", "postgres"),
        ("CREATE TABLE u (id SERIAL PRIMARY KEY)", "postgres"),
        ("SELECT * FROM u WHERE name ILIKE '%foo%'", "postgres"),
        ("INSERT INTO u (id) VALUES (1) ON CONFLICT DO NOTHING", "postgres"),
        # MSSQL
        ("SELECT TOP 10 * FROM users", "mssql"),
        ("CREATE TABLE u (name NVARCHAR(50))", "mssql"),
        ("SELECT GETDATE()", "mssql"),
        ("SELECT * FROM users WITH (NOLOCK)", "mssql"),
        ("SELECT @@IDENTITY", "mssql"),
        ("SELECT [user name] FROM [Users]", "mssql"),
        # SQLite
        ("CREATE TABLE u (id INTEGER PRIMARY KEY AUTOINCREMENT)", "sqlite"),
        ("PRAGMA table_info(users)", "sqlite"),
        ("SELECT name FROM sqlite_master WHERE type='table'", "sqlite"),
        ("CREATE TABLE u (id INT) WITHOUT ROWID", "sqlite"),
    ],
)
def test_detect_sql_dialect_recognises_dialect_features(code, expected):
    assert detect_sql_dialect(code) == expected


def test_detect_sql_dialect_returns_none_for_ambiguous_ansi_sql():
    """Plain ANSI SQL without dialect-specific syntax falls through to
    None -- the caller already knows it's SQL from detect_language."""
    code = "SELECT name, email FROM users WHERE id = ?"
    assert detect_sql_dialect(code) is None


def test_detect_sql_dialect_returns_none_for_empty_or_whitespace():
    assert detect_sql_dialect("") is None
    assert detect_sql_dialect("   \n\n  ") is None


def test_detect_sql_dialect_priority_mssql_over_others():
    """A snippet that has both TOP (MSSQL) and a backtick (looks like
    MySQL but rarely is in MSSQL contexts) should tag as MSSQL because
    TOP is a much stronger signal than a single backtick."""
    code = "SELECT TOP 5 `name` FROM users"
    assert detect_sql_dialect(code) == "mssql"


def test_detect_sql_dialect_priority_postgres_over_mysql():
    """A snippet that has both RETURNING (postgres) and LIMIT n,m
    (MySQL) should tag postgres -- RETURNING is the more specific
    signal."""
    code = "UPDATE u SET x=1 LIMIT 5, 10 RETURNING id"
    assert detect_sql_dialect(code) == "postgres"


def test_detect_sql_dialect_skips_dollar_in_regex_literal():
    """A snippet that mentions ``$1`` only inside a regex string should
    not falsely tag as postgres. Our regex requires a word boundary on
    the left, so an embedded ``r'\\$1'`` (preceded by a backslash) is
    skipped."""
    code = "SELECT * FROM messages WHERE body REGEXP '\\$1foo'"
    assert detect_sql_dialect(code) is None


def test_detect_sql_dialect_square_bracket_needs_identifier():
    """Bare ``[0]`` array indexing in a string literal should not
    falsely tag as MSSQL."""
    code = "SELECT json_extract(body, '$.items[0]') FROM logs"
    # No MSSQL-style identifier in brackets, and no other MSSQL signal.
    assert detect_sql_dialect(code) is None


# ---- enrich_code integration ------------------------------------------


def test_enrich_code_sets_dialect_for_sql_snippet():
    """When OCR contains SQL with a dialect signal, enrich_code
    populates the new ``dialect`` field on CodeFields."""
    ocr = OCRResult(
        text="SELECT id FROM users WHERE name = $1 RETURNING id",
        word_count=10,
    )
    out = enrich_code(None, ocr)
    assert out.language == "sql"
    assert out.dialect == "postgres"


def test_enrich_code_preserves_llm_supplied_dialect():
    """An LLM that already populated the dialect must not be
    second-guessed by the heuristic."""
    from shotclassify_common import CodeFields

    existing = CodeFields(
        language="sql",
        code="SELECT TOP 5 * FROM users",
        dialect="mysql",  # deliberately wrong; LLM wins
        line_count=1,
    )
    ocr = OCRResult(text="SELECT TOP 5 * FROM users", word_count=5)
    out = enrich_code(existing, ocr)
    assert out.dialect == "mysql"


def test_enrich_code_no_dialect_for_python_snippet():
    """Non-SQL code never gets a dialect field set."""
    ocr = OCRResult(
        text="def add(a, b):\n    return a + b\n",
        word_count=4,
    )
    out = enrich_code(None, ocr)
    assert out.language == "python"
    assert out.dialect is None


def test_enrich_code_no_dialect_for_ansi_sql():
    """SQL without a dialect signal sets language=sql but leaves
    dialect=None so dashboards can show 'SQL (unknown dialect)'."""
    ocr = OCRResult(
        text="SELECT name FROM users WHERE id = ?",
        word_count=6,
    )
    out = enrich_code(None, ocr)
    assert out.language == "sql"
    assert out.dialect is None
