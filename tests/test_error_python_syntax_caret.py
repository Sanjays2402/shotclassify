"""Python SyntaxError caret-line extraction.

When CPython prints a SyntaxError / IndentationError / TabError, the
trace ends with the offending source line followed by a caret pointer
(``^^^^^^^``) at the bad token. The parse_error_text() helper now
enriches the ``message`` field with both the source line and the
caret column span so dashboards can render a highlighted snippet.

CPython 3.10+ also prints multi-char ``~~~~^^^^~~~~`` indicators that
span the whole expression with carets pinning the operator. Both
shapes are recognised; the full span (tildes + carets) is captured.

The exception name is whatever CPython printed (one of SyntaxError,
IndentationError, TabError, UnicodeDecodeError, UnicodeEncodeError).
likely_cause maps common wordings to operator-friendly hints.
"""
from __future__ import annotations

from shotclassify_extract import parse_syntax_caret
from shotclassify_extract.error import parse_error_text

# ---- parse_syntax_caret helper ---------------------------------------


def test_parse_syntax_caret_basic():
    text = (
        '  File "/x.py", line 3\n'
        "    print(x +)\n"
        "             ^\n"
        "SyntaxError: invalid syntax\n"
    )
    got = parse_syntax_caret(text)
    assert got is not None
    exc, source, start, end = got
    assert exc == "SyntaxError"
    assert source == "    print(x +)"
    # The caret sits 13 columns in (matching the source's 13-char prefix).
    assert start == 13
    assert end == 14


def test_parse_syntax_caret_multi_char():
    """CPython 3.10+ widened caret indicators like ``~~^^^~~``."""
    text = (
        '  File "/x.py", line 5\n'
        "    a = b + c +\n"
        "        ~~^^~~~\n"
        "SyntaxError: invalid syntax\n"
    )
    got = parse_syntax_caret(text)
    assert got is not None
    exc, source, start, end = got
    assert exc == "SyntaxError"
    assert start == 8
    assert end == 15  # 8 + 7 chars of carets / tildes


def test_parse_syntax_caret_indentation_error():
    text = (
        '  File "/x.py", line 7\n'
        "      print('hi')\n"
        "      ^\n"
        "IndentationError: unexpected indent\n"
    )
    got = parse_syntax_caret(text)
    assert got is not None
    exc, source, start, end = got
    assert exc == "IndentationError"
    assert start == 6
    assert end == 7


def test_parse_syntax_caret_tab_error():
    text = (
        '  File "/x.py", line 4\n'
        "    if foo:\n"
        "        ^\n"
        "TabError: inconsistent use of tabs and spaces\n"
    )
    got = parse_syntax_caret(text)
    assert got is not None
    exc, source, _start, _end = got
    assert exc == "TabError"


def test_parse_syntax_caret_returns_none_without_exc_line():
    """Caret present but no SyntaxError-class line -> None."""
    text = (
        "    print(x)\n"
        "         ^\n"
    )
    assert parse_syntax_caret(text) is None


def test_parse_syntax_caret_returns_none_without_caret():
    """SyntaxError without the caret indicator -> None."""
    text = "SyntaxError: invalid syntax\n"
    assert parse_syntax_caret(text) is None


def test_parse_syntax_caret_returns_none_for_empty():
    assert parse_syntax_caret("") is None
    assert parse_syntax_caret(None) is None  # type: ignore[arg-type]


def test_parse_syntax_caret_ignores_first_line_caret():
    """A caret on line 0 with no source above it is malformed; skip."""
    text = (
        "        ^\n"
        '  File "/x.py", line 1\n'
        "    x = 1\n"
        "    ^\n"
        "SyntaxError: invalid syntax\n"
    )
    got = parse_syntax_caret(text)
    assert got is not None
    # We picked the second caret (with a valid source line above it).
    assert got[1] == "    x = 1"


def test_parse_syntax_caret_unmatched_message_preserved():
    """The full source line is captured even when it's just an opener."""
    text = (
        '  File "/x.py", line 2\n'
        "    items = [1, 2,\n"
        "                  ^\n"
        "SyntaxError: unmatched '['\n"
    )
    got = parse_syntax_caret(text)
    assert got is not None
    exc, source, start, end = got
    assert exc == "SyntaxError"
    assert source == "    items = [1, 2,"
    assert start == 18
    assert end == 19


def test_parse_syntax_caret_ignores_separator_with_caret():
    """A divider line containing ``^`` plus other chars must NOT count."""
    text = (
        "---^---\n"
        "SyntaxError: invalid syntax\n"
    )
    assert parse_syntax_caret(text) is None


# ---- parse_error_text wiring ----------------------------------------


def test_parse_error_text_python_syntax_enriches_message():
    text = (
        "Traceback (most recent call last):\n"
        '  File "/x.py", line 3\n'
        "    print(x +)\n"
        "             ^\n"
        "SyntaxError: invalid syntax\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "python"
    assert fields.exception == "SyntaxError"
    assert fields.file == "/x.py"
    assert fields.line == 3
    assert fields.message is not None
    assert "invalid syntax" in fields.message
    assert "print(x +)" in fields.message
    assert "col" in fields.message
    assert fields.likely_cause is not None
    assert "highlighted token" in fields.likely_cause


def test_parse_error_text_indentation_error_enriches():
    text = (
        "Traceback (most recent call last):\n"
        '  File "/x.py", line 5\n'
        "    if foo:\n"
        "        ^\n"
        "IndentationError: expected an indented block\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "python"
    assert fields.exception == "IndentationError"
    assert fields.likely_cause is not None
    assert "tabs and spaces" in fields.likely_cause


def test_parse_error_text_tab_error_enriches():
    text = (
        "Traceback (most recent call last):\n"
        '  File "/x.py", line 4\n'
        "    if foo:\n"
        "        ^\n"
        "TabError: inconsistent use of tabs and spaces\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "python"
    assert fields.exception == "TabError"
    assert fields.likely_cause is not None
    assert "tabs" in fields.likely_cause.lower()


def test_parse_error_text_syntax_without_caret_unchanged():
    """SyntaxError text without the caret indicator: framework stays
    python and exception/message still come from the generic Python
    branch -- no caret tail appended.
    """
    text = (
        "Traceback (most recent call last):\n"
        '  File "/x.py", line 3\n'
        "SyntaxError: invalid syntax\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "python"
    assert fields.exception == "SyntaxError"
    # No "[at " caret-tail because parse_syntax_caret returned None.
    assert fields.message is not None
    assert "[at " not in fields.message
    assert fields.likely_cause is not None
    assert "highlighted token" in fields.likely_cause


def test_parse_error_text_unmatched_bracket_likely_cause():
    text = (
        "Traceback (most recent call last):\n"
        '  File "/x.py", line 1\n'
        "    a = [1, 2,\n"
        "             ^\n"
        "SyntaxError: unmatched '['\n"
    )
    fields = parse_error_text(text)
    assert fields.likely_cause is not None
    assert "Unmatched bracket" in fields.likely_cause


def test_parse_error_text_unexpected_eof_likely_cause():
    text = (
        "Traceback (most recent call last):\n"
        '  File "/x.py", line 1\n'
        "    def f(\n"
        "         ^\n"
        "SyntaxError: unexpected EOF while parsing\n"
    )
    fields = parse_error_text(text)
    assert fields.likely_cause is not None
    assert "ended mid-statement" in fields.likely_cause


def test_parse_error_text_missing_colon_likely_cause():
    text = (
        "Traceback (most recent call last):\n"
        '  File "/x.py", line 1\n'
        "    def f()\n"
        "          ^\n"
        "SyntaxError: expected ':'\n"
    )
    fields = parse_error_text(text)
    assert fields.likely_cause is not None
    assert "missing trailing" in fields.likely_cause


def test_parse_error_text_f_string_likely_cause():
    text = (
        "Traceback (most recent call last):\n"
        '  File "/x.py", line 1\n'
        "    s = f'{a}\n"
        "             ^\n"
        "SyntaxError: f-string: expecting '}'\n"
    )
    fields = parse_error_text(text)
    assert fields.likely_cause is not None
    assert "F-string" in fields.likely_cause


def test_parse_error_text_widened_caret_span():
    """CPython 3.10+ widened caret indicators get the full span captured."""
    text = (
        "Traceback (most recent call last):\n"
        '  File "/x.py", line 2\n'
        "    a = b + c +\n"
        "        ~~^^~~~\n"
        "SyntaxError: invalid syntax\n"
    )
    fields = parse_error_text(text)
    assert fields.message is not None
    # Span is 7 chars wide (indices 8..15).
    assert "col 4..11" in fields.message  # 8-4=4, 15-4=11 (after trim of 4 spaces)


def test_parse_error_text_message_includes_source_line_repr():
    """The source line appears repr'd in the message so newlines or
    tabs survive verbatim for the dashboard renderer.
    """
    text = (
        "Traceback (most recent call last):\n"
        '  File "/x.py", line 3\n'
        "    if x:\n"
        "        ^\n"
        "SyntaxError: invalid syntax\n"
    )
    fields = parse_error_text(text)
    assert fields.message is not None
    assert "'if x:'" in fields.message  # repr of the trimmed source line


def test_parse_error_text_non_python_text_unaffected():
    """A Java exception with words like 'SyntaxError' should not get
    Python caret enrichment (the python branch never fires on it).
    """
    text = "java.lang.SyntaxError: parse fail at /Foo.java:12\n"
    fields = parse_error_text(text)
    # Java branch tags jvm; caret enrichment must not run.
    assert fields.framework == "jvm"
    if fields.message:
        assert "[at " not in fields.message
