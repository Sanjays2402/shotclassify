"""Rust panic + pytest assertion frame parser tests.

Adds two more frameworks to the error extractor catalog:
* ``rust`` -- thread panics (both pre-1.72 and 1.72+ output shapes),
  with ``exception='panic'`` (Rust panics don't have a typed exception
  class), the file/line from the panic location, and operator-friendly
  ``likely_cause`` hints for the common kinds (index out of bounds,
  unwrap on None/Err, divide by zero, integer overflow, stack overflow).
* ``pytest`` -- single-failure summaries with ``test_name + assertion
  expression`` extraction. The exception is whatever class pytest
  prints in the tail ``FILE:LINE: ExcName`` line (typically
  ``AssertionError``), and the message is the bare ``assert foo == bar``
  expression instead of the noisier multi-line AssertionError detail.

Ordering rules covered by the regression tests at the bottom:
* pytest WINS over the Python traceback branch when both signals are
  present (the ``>`` assert indicator is the discriminator).
* A plain Python traceback without pytest framing still tags python.
* A Rust ``thread 'main' panicked`` line beats the generic HTTP
  fallback and the Error/Exception regex.
"""
from __future__ import annotations

from shotclassify_extract import parse_pytest_failure, parse_rust_panic
from shotclassify_extract.error import parse_error_text

# ---- parse_rust_panic helper --------------------------------------------


def test_rust_panic_old_form_index_out_of_bounds():
    text = (
        "thread 'main' panicked at 'index out of bounds: the len is 3 but the index is 5', "
        "src/main.rs:7:13\n"
        "note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace\n"
    )
    got = parse_rust_panic(text)
    assert got is not None
    file_, line_, msg = got
    assert file_ == "src/main.rs"
    assert line_ == 7
    assert "index out of bounds" in msg


def test_rust_panic_new_form_1_72_plus():
    text = (
        "thread 'main' panicked at src/main.rs:5:8:\n"
        "attempt to divide by zero\n"
    )
    got = parse_rust_panic(text)
    assert got is not None
    file_, line_, msg = got
    assert file_ == "src/main.rs"
    assert line_ == 5
    assert "divide by zero" in msg


def test_rust_panic_returns_none_for_non_panic_text():
    assert parse_rust_panic("just words") is None
    assert parse_rust_panic("") is None


# ---- parse_pytest_failure helper -----------------------------------------


def test_pytest_failure_extracts_test_assert_expression():
    text = (
        "________________________ test_addition ________________________\n"
        "\n"
        "    def test_addition():\n"
        ">       assert 1 + 1 == 3\n"
        "E       assert 2 == 3\n"
        "\n"
        "tests/test_math.py:5: AssertionError\n"
    )
    got = parse_pytest_failure(text)
    assert got is not None
    file_, line_, exc, expr = got
    assert file_ == "tests/test_math.py"
    assert line_ == 5
    assert exc == "AssertionError"
    assert expr == "1 + 1 == 3"


def test_pytest_failure_extracts_other_exception_tail():
    """When pytest's tail line is e.g. ``FILE:LINE: ValueError`` the
    exception field reflects that, not a hardcoded AssertionError.
    The assert expression is still extracted because the ``>``
    indicator was the surfaced line."""
    text = (
        "    def test_load():\n"
        ">       parse(\"\")\n"
        "E       ValueError: empty input\n"
        "\n"
        "tests/test_parser.py:12: ValueError\n"
    )
    got = parse_pytest_failure(text)
    assert got is not None
    file_, line_, exc, expr = got
    assert exc == "ValueError"
    assert line_ == 12
    assert expr.startswith("parse")  # ">" line content


def test_pytest_failure_returns_none_when_no_tail():
    """A bare assertion line without the closing ``FILE:LINE: Error``
    is not pytest output; we let the Python branch take it."""
    text = ">       assert foo == bar\n"
    assert parse_pytest_failure(text) is None


# ---- error extractor integration: rust ----------------------------------


def test_error_extractor_tags_rust_panic_index_out_of_bounds():
    text = (
        "thread 'main' panicked at 'index out of bounds: the len is 0 but the index is 0', "
        "src/lib.rs:42:5\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "rust"
    assert fields.exception == "panic"
    assert fields.file == "src/lib.rs"
    assert fields.line == 42
    assert fields.likely_cause is not None
    assert "len()" in fields.likely_cause


def test_error_extractor_tags_rust_panic_new_form():
    text = (
        "thread 'main' panicked at src/main.rs:9:13:\n"
        "called `Option::unwrap()` on a `None` value\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "rust"
    assert fields.file == "src/main.rs"
    assert fields.line == 9
    assert fields.likely_cause is not None
    assert "unwrap" in fields.likely_cause.lower()


def test_error_extractor_tags_rust_panic_overflow():
    text = (
        "thread 'main' panicked at src/math.rs:3:5:\n"
        "attempt to subtract with overflow\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "rust"
    assert "overflowed" in (fields.likely_cause or "").lower()


# ---- error extractor integration: pytest --------------------------------


def test_error_extractor_tags_pytest_assertion():
    text = (
        "________________________ test_x ________________________\n"
        "\n"
        "    def test_x():\n"
        ">       assert add(1, 2) == 4\n"
        "E       assert 3 == 4\n"
        "E        +  where 3 = add(1, 2)\n"
        "\n"
        "tests/test_math.py:8: AssertionError\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "pytest"
    assert fields.exception == "AssertionError"
    assert fields.file == "tests/test_math.py"
    assert fields.line == 8
    assert "add(1, 2) == 4" in (fields.message or "")
    assert "Assertion failed" in (fields.likely_cause or "")


def test_pytest_wins_over_python_traceback_when_assert_indicator_present():
    """A pytest run wraps the failing test in a Python traceback. When
    we see the ``>`` assert indicator we tag pytest instead of python
    so dashboards can surface the assertion expression."""
    text = (
        "________________________ test_q ________________________\n"
        "\n"
        "    def test_q():\n"
        ">       assert q() == 1\n"
        "E       AssertionError\n"
        "\n"
        "Traceback (most recent call last):\n"
        '  File "/x.py", line 1, in <module>\n'
        "    test_q()\n"
        "AssertionError\n"
        "tests/test_q.py:3: AssertionError\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "pytest"
    assert fields.message == "q() == 1"


def test_python_traceback_still_wins_when_no_pytest_indicator():
    """A bare Python traceback (no pytest divider, no ``>`` assert)
    still tags python."""
    text = (
        'Traceback (most recent call last):\n'
        '  File "/x.py", line 1, in <module>\n'
        '    raise ValueError("nope")\n'
        'ValueError: nope\n'
    )
    fields = parse_error_text(text)
    assert fields.framework == "python"
    assert fields.exception == "ValueError"


def test_rust_does_not_steal_python_or_go_traces():
    """Regression: ``panicked`` only appears in Rust panic lines; the
    Go branch keys off ``panic:`` (different verb) and the Python
    branch keys off ``Traceback``. A Python traceback that quotes the
    word ``panicked`` in a string literal still classifies as python."""
    text = (
        'Traceback (most recent call last):\n'
        '  File "/x.py", line 1, in <module>\n'
        '    raise RuntimeError("the goroutine panicked at /x.rs")\n'
        'RuntimeError: the goroutine panicked at /x.rs\n'
    )
    fields = parse_error_text(text)
    assert fields.framework == "python"
