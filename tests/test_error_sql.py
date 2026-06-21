"""SQL database error extraction (framework='sql').

The error extractor now recognises canonical engine-specific SQL
error preludes and tags them with ``framework='sql'``:

* PostgreSQL: ``ERROR:  syntax error at or near "x"``,
  ``ERROR:  relation "users" does not exist`` (with optional
  ``LINE N:`` source-line marker on a following line).
* MySQL: ``ERROR 1064 (42000): You have an error in your SQL...``
  (the unique 4-digit code + 5-char SQLSTATE in parens shape).
* SQLite: ``Error: near "x": syntax error`` (vocabulary-anchored
  so it doesn't steal other ``Error:`` lines).
* MSSQL: ``Msg 207, Level 16, State 1, Line 5`` + the following
  description line.

The branch sits inside the ``else:`` fallback (next to HTTP and
the generic ``\\w+Exception`` catch) and runs BEFORE HTTP because
SQL errors carry no status code. The dialect identifier (postgres
/ mysql / sqlite / mssql) is folded into the exception slot
(``MySQL 1064 (42000)``, ``PostgreSQL ERROR``, ``SQLite Error``,
``MSSQL Msg 207``) so dashboards can group either by framework
(=='sql') or by exception (which carries the dialect tag).

likely_cause hints cover the high-frequency SQL failures across
dialects: syntax errors, missing tables / columns, unique-
constraint duplicates, foreign-key violations, deadlocks, lock
timeouts, permission denied, value-too-long, NOT NULL violations,
and the MSSQL-specific ``Invalid column name`` wording.
"""
from __future__ import annotations

from shotclassify_extract import parse_error_text, parse_sql_error

# ---- parse_sql_error: PostgreSQL ------------------------------------


def test_postgres_syntax_error():
    text = 'ERROR:  syntax error at or near "FROOM"\nLINE 1: SELECT * FROOM users\n'
    out = parse_sql_error(text)
    assert out is not None
    dialect, exc, msg, line_ = out
    assert dialect == "postgres"
    assert exc == "PostgreSQL ERROR"
    assert "syntax error" in msg
    assert line_ == 1


def test_postgres_relation_does_not_exist():
    text = 'ERROR:  relation "users" does not exist\nLINE 1: SELECT * FROM users\n'
    out = parse_sql_error(text)
    assert out is not None
    dialect, _, msg, line_ = out
    assert dialect == "postgres"
    assert "relation" in msg
    assert line_ == 1


def test_postgres_column_does_not_exist():
    text = (
        'ERROR:  column "missing" of relation "users" does not exist\n'
        "LINE 1: UPDATE users SET missing = 1\n"
    )
    out = parse_sql_error(text)
    assert out is not None
    dialect, _, _, line_ = out
    assert dialect == "postgres"
    assert line_ == 1


def test_postgres_no_line_marker():
    """PostgreSQL error without the LINE N: marker still tags."""
    text = "ERROR:  permission denied for table users\n"
    out = parse_sql_error(text)
    assert out is not None
    dialect, _, msg, line_ = out
    assert dialect == "postgres"
    assert "permission denied" in msg
    assert line_ is None


# ---- parse_sql_error: MySQL -----------------------------------------


def test_mysql_syntax_1064():
    text = (
        "ERROR 1064 (42000): You have an error in your SQL syntax; "
        "check the manual that corresponds to your MariaDB server version\n"
    )
    out = parse_sql_error(text)
    assert out is not None
    dialect, exc, msg, line_ = out
    assert dialect == "mysql"
    assert "1064" in exc
    assert "(42000)" in exc
    assert "SQL syntax" in msg
    assert line_ is None


def test_mysql_table_doesnt_exist_1146():
    text = "ERROR 1146 (42S02): Table 'db.users' doesn't exist\n"
    out = parse_sql_error(text)
    assert out is not None
    dialect, exc, msg, _ = out
    assert dialect == "mysql"
    assert "1146" in exc
    assert "users" in msg


def test_mysql_unknown_column_1054():
    text = "ERROR 1054 (42S22): Unknown column 'x' in 'field list'\n"
    out = parse_sql_error(text)
    assert out is not None
    dialect, _, msg, _ = out
    assert dialect == "mysql"
    assert "Unknown column" in msg


def test_mysql_duplicate_entry_1062():
    text = "ERROR 1062 (23000): Duplicate entry 'jane@example.com' for key 'users.email_unique'\n"
    out = parse_sql_error(text)
    assert out is not None
    dialect, _, msg, _ = out
    assert dialect == "mysql"
    assert "Duplicate" in msg


# ---- parse_sql_error: SQLite ----------------------------------------


def test_sqlite_near_syntax():
    text = 'Error: near "FROOM": syntax error\n'
    out = parse_sql_error(text)
    assert out is not None
    dialect, exc, msg, line_ = out
    assert dialect == "sqlite"
    assert exc == "SQLite Error"
    assert "syntax error" in msg
    assert line_ is None


def test_sqlite_no_such_table():
    text = "Error: no such table: users\n"
    out = parse_sql_error(text)
    assert out is not None
    dialect, _, msg, _ = out
    assert dialect == "sqlite"
    assert "no such table" in msg


def test_sqlite_no_such_column():
    text = 'Error: no such column: x\n'
    out = parse_sql_error(text)
    assert out is not None
    dialect, _, _, _ = out
    assert dialect == "sqlite"


def test_sqlite_too_many_columns():
    text = "Error: too many columns on table users\n"
    out = parse_sql_error(text)
    assert out is not None
    assert out[0] == "sqlite"


def test_sqlite_foreign_key():
    text = "Error: foreign key constraint failed\n"
    out = parse_sql_error(text)
    assert out is not None
    assert out[0] == "sqlite"


# ---- parse_sql_error: MSSQL -----------------------------------------


def test_mssql_invalid_column_msg_207():
    text = (
        "Msg 207, Level 16, State 1, Line 5\n"
        "Invalid column name 'x'.\n"
    )
    out = parse_sql_error(text)
    assert out is not None
    dialect, exc, msg, line_ = out
    assert dialect == "mssql"
    assert "207" in exc
    assert "Invalid column name" in msg
    assert line_ == 5


def test_mssql_msg_no_line():
    """MSSQL header without an explicit Line N -> line is None."""
    text = (
        "Msg 547, Level 16, State 0\n"
        "FOREIGN KEY constraint conflict.\n"
    )
    out = parse_sql_error(text)
    assert out is not None
    dialect, _, msg, line_ = out
    assert dialect == "mssql"
    assert line_ is None
    assert "FOREIGN KEY" in msg


def test_mssql_object_doesnt_exist():
    text = (
        "Msg 208, Level 16, State 1, Line 1\n"
        "Invalid object name 'dbo.MissingTable'.\n"
    )
    out = parse_sql_error(text)
    assert out is not None
    dialect, _, msg, line_ = out
    assert dialect == "mssql"
    assert line_ == 1
    assert "Invalid object name" in msg


# ---- rejection / boundary -------------------------------------------


def test_empty_text():
    assert parse_sql_error("") is None
    assert parse_sql_error("   ") is None


def test_python_traceback_not_matched():
    text = "Traceback (most recent call last):\n  File 'x.py', line 1\nValueError: bad"
    assert parse_sql_error(text) is None


def test_php_fatal_not_matched():
    text = "Fatal error: Uncaught RuntimeException: boom\n  thrown in /app/x.php on line 5\n"
    assert parse_sql_error(text) is None


def test_node_stacktrace_not_matched():
    text = "TypeError: bad\n    at foo (bar.js:5:10)\n"
    assert parse_sql_error(text) is None


def test_random_error_keyword_rejected():
    """A bare ``Error: something`` without SQLite vocab is NOT matched."""
    text = "Error: thingy went wrong\n"
    assert parse_sql_error(text) is None


# ---- dialect priority -----------------------------------------------


def test_mysql_wins_over_postgres_when_both_present():
    """MySQL signature is more specific; it runs first."""
    text = (
        "ERROR 1064 (42000): MySQL syntax error\n"
        "ERROR:  duplicate would-be-postgres marker\n"
    )
    out = parse_sql_error(text)
    assert out is not None
    assert out[0] == "mysql"


def test_mssql_wins_over_postgres_when_both_present():
    text = (
        "Msg 207, Level 16, State 1, Line 5\n"
        "Invalid column name 'x'.\n"
        "ERROR:  postgres also\n"
    )
    out = parse_sql_error(text)
    assert out is not None
    assert out[0] == "mssql"


def test_sqlite_wins_over_postgres():
    """SQLite vocabulary-anchored ``Error: near`` wins."""
    text = (
        'Error: near "x": syntax error\n'
        "ERROR:  postgres style after\n"
    )
    out = parse_sql_error(text)
    assert out is not None
    assert out[0] == "sqlite"


# ---- parse_error_text wiring (full pipeline) ------------------------


def test_parse_error_text_tags_sql_for_postgres():
    text = 'ERROR:  syntax error at or near "FROOM"\nLINE 1: SELECT * FROOM users\n'
    out = parse_error_text(text)
    assert out.framework == "sql"
    assert out.exception is not None
    assert "PostgreSQL" in out.exception
    assert out.line == 1


def test_parse_error_text_tags_sql_for_mysql():
    text = "ERROR 1064 (42000): You have an error in your SQL syntax\n"
    out = parse_error_text(text)
    assert out.framework == "sql"
    assert out.exception is not None
    assert "MySQL" in out.exception


def test_parse_error_text_tags_sql_for_sqlite():
    text = 'Error: near "FROOM": syntax error\n'
    out = parse_error_text(text)
    assert out.framework == "sql"
    assert out.exception == "SQLite Error"


def test_parse_error_text_tags_sql_for_mssql():
    text = "Msg 207, Level 16, State 1, Line 5\nInvalid column name 'x'.\n"
    out = parse_error_text(text)
    assert out.framework == "sql"
    assert out.exception is not None
    assert "MSSQL" in out.exception
    assert out.line == 5


# ---- likely_cause hints ---------------------------------------------


def test_likely_cause_syntax_error():
    text = "ERROR 1064 (42000): syntax error here\n"
    out = parse_error_text(text)
    assert out.likely_cause is not None
    assert "syntax" in out.likely_cause.lower()


def test_likely_cause_no_such_table():
    text = "Error: no such table: users\n"
    out = parse_error_text(text)
    assert out.likely_cause is not None
    assert "table" in out.likely_cause.lower() or "schema" in out.likely_cause.lower()


def test_likely_cause_unknown_column():
    text = "ERROR 1054 (42S22): Unknown column 'x' in 'field list'\n"
    out = parse_error_text(text)
    assert out.likely_cause is not None
    assert "column" in out.likely_cause.lower()


def test_likely_cause_duplicate_entry():
    text = "ERROR 1062 (23000): Duplicate entry 'jane' for key 'users.email'\n"
    out = parse_error_text(text)
    assert out.likely_cause is not None
    assert "unique" in out.likely_cause.lower() or "duplicate" in out.likely_cause.lower()


def test_likely_cause_foreign_key():
    text = "Error: foreign key constraint failed\n"
    out = parse_error_text(text)
    assert out.likely_cause is not None
    assert "foreign" in out.likely_cause.lower() or "key" in out.likely_cause.lower()


def test_likely_cause_deadlock():
    text = "ERROR 1213 (40001): Deadlock found when trying to get lock\n"
    out = parse_error_text(text)
    assert out.likely_cause is not None
    assert "deadlock" in out.likely_cause.lower()


def test_likely_cause_invalid_column_name_mssql():
    """MSSQL-specific wording also surfaces a column hint."""
    text = "Msg 207, Level 16, State 1, Line 5\nInvalid column name 'x'.\n"
    out = parse_error_text(text)
    assert out.likely_cause is not None
    assert "column" in out.likely_cause.lower()


def test_likely_cause_lock_timeout():
    text = "ERROR 1205 (HY000): Lock wait timeout exceeded\n"
    out = parse_error_text(text)
    assert out.likely_cause is not None
    assert "lock" in out.likely_cause.lower()


def test_likely_cause_permission_denied():
    text = "ERROR:  permission denied for table users\n"
    out = parse_error_text(text)
    assert out.likely_cause is not None
    assert "privilege" in out.likely_cause.lower() or "role" in out.likely_cause.lower()


def test_likely_cause_data_too_long():
    text = "ERROR 1406 (22001): Data too long for column 'name'\n"
    out = parse_error_text(text)
    assert out.likely_cause is not None
    assert "length" in out.likely_cause.lower() or "exceeds" in out.likely_cause.lower()


def test_likely_cause_not_null_violation():
    text = "ERROR:  null value in column \"id\" violates not-null constraint\n"
    out = parse_error_text(text)
    assert out.likely_cause is not None
    assert "null" in out.likely_cause.lower()


# ---- ordering -------------------------------------------------------


def test_sql_branch_runs_before_http():
    """A SQL error without an HTTP status must NOT tag as ``http``."""
    text = 'ERROR:  syntax error at or near "FROOM"\n'
    out = parse_error_text(text)
    assert out.framework == "sql"
    assert out.framework != "http"


def test_http_branch_still_works():
    """Sanity check: an HTTP-only line still tags as ``http``."""
    text = "HTTP/1.1 500 Internal Server Error\n"
    out = parse_error_text(text)
    assert out.framework == "http"


def test_python_traceback_still_works():
    """Sanity check: Python tracebacks still tag as ``python``."""
    text = (
        "Traceback (most recent call last):\n"
        "  File \"x.py\", line 1, in <module>\n"
        "    raise ValueError('bad')\n"
        "ValueError: bad\n"
    )
    out = parse_error_text(text)
    assert out.framework == "python"


def test_php_fatal_still_works():
    """Sanity check: PHP fatals still tag as ``php``."""
    text = (
        "Fatal error: Uncaught RuntimeException: boom\n"
        "  thrown in /app/x.php on line 5\n"
    )
    out = parse_error_text(text)
    assert out.framework == "php"
