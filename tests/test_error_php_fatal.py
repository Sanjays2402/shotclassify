"""PHP fatal-error stacktrace parsing.

A new ``framework='php'`` branch in ``parse_error_text`` recognises
the canonical PHP fatal-error shapes:

* ``Fatal error: Uncaught TypeError: ...`` (without leading ``PHP``)
* ``PHP Fatal error: Uncaught RuntimeException: boom in /app/x.php:5``
* Trailing ``Stack trace:`` + ``#0 /path(NN): ...`` frames
* Innermost-frame location from ``thrown in PATH on line N``
* Inline ``in PATH:LINE`` location when the multi-line tail is missing

The branch is placed BEFORE the JVM (``_JAVA_EXC``) branch because
PHP exception names also satisfy the generic ``\\w+Exception`` /
``\\w+Error`` pattern. Namespace-qualified exceptions (Laravel /
Symfony: ``Symfony\\Component\\HttpKernel\\Exception\\NotFoundHttpException``)
keep their full namespace path so dashboards can group by short
or long form.

likely_cause hints cover the high-frequency PHP fatals: TypeError
(argument type mismatch), ArgumentCountError (too few arguments),
DivisionByZeroError, ParseError (syntax error), class-not-found
autoloader failure, generic RuntimeException / LogicException /
InvalidArgumentException, OutOfBoundsException / OutOfRangeException,
PDOException / mysqli failures, and permission-denied filesystem
errors.
"""
from __future__ import annotations

from shotclassify_extract import parse_error_text, parse_php_fatal

# ---- parse_php_fatal: exception line variants -----------------------


def test_basic_typeerror_with_thrown_in():
    text = (
        "Fatal error: Uncaught TypeError: Foo::bar(): Argument #1 must be of type int\n"
        "Stack trace:\n"
        "#0 /var/www/app/main.php(12): Foo->bar('hi')\n"
        "#1 {main}\n"
        "  thrown in /var/www/app/lib/Foo.php on line 42\n"
    )
    out = parse_php_fatal(text)
    assert out is not None
    exc, msg, file_, line_ = out
    assert exc == "TypeError"
    assert "Foo::bar" in msg
    assert file_ == "/var/www/app/lib/Foo.php"
    assert line_ == 42


def test_php_prefix_runtime_exception():
    text = (
        "PHP Fatal error:  Uncaught RuntimeException: boom in /app/index.php:5\n"
        "Stack trace:\n"
        "#0 {main}\n"
        "  thrown in /app/index.php on line 5\n"
    )
    out = parse_php_fatal(text)
    assert out is not None
    exc, msg, file_, line_ = out
    assert exc == "RuntimeException"
    assert "boom" in msg
    assert file_ == "/app/index.php"
    assert line_ == 5


def test_inline_location_fallback_when_no_thrown_in():
    """One-line traces use the inline ``in PATH:LINE`` form."""
    text = "PHP Fatal error: Uncaught LogicException: bad state in /app/foo.php:99"
    out = parse_php_fatal(text)
    assert out is not None
    exc, msg, file_, line_ = out
    assert exc == "LogicException"
    assert msg == "bad state"
    assert file_ == "/app/foo.php"
    assert line_ == 99


def test_namespace_qualified_exception_preserved():
    text = (
        "Fatal error: Uncaught Symfony\\Component\\HttpKernel\\Exception\\"
        "NotFoundHttpException: route not found\n"
        "  thrown in /var/www/vendor/symfony/http-kernel/Exception.php on line 12\n"
    )
    out = parse_php_fatal(text)
    assert out is not None
    exc, msg, file_, line_ = out
    assert "Symfony\\Component" in exc
    assert exc.endswith("NotFoundHttpException")
    assert msg == "route not found"
    assert line_ == 12


def test_argument_count_error():
    text = (
        "Fatal error: Uncaught ArgumentCountError: Too few arguments to "
        "function Foo::bar(), 0 passed and exactly 1 expected\n"
        "  thrown in /app/Foo.php on line 8\n"
    )
    out = parse_php_fatal(text)
    assert out is not None
    exc, msg, _, _ = out
    assert exc == "ArgumentCountError"
    assert "Too few arguments" in msg


def test_division_by_zero():
    text = (
        "PHP Fatal error: Uncaught DivisionByZeroError: Division by zero\n"
        "  thrown in /app/calc.php on line 4\n"
    )
    out = parse_php_fatal(text)
    assert out is not None
    exc, _, _, _ = out
    assert exc == "DivisionByZeroError"


def test_parse_error_syntax():
    text = (
        "PHP Parse error:  syntax error, unexpected token \";\" in /app/x.php on line 7\n"
    )
    # Parse error: shape doesn't match the "Uncaught" prelude, so
    # the helper returns None. This documents the boundary --
    # we recognise UNCAUGHT exceptions, not raw parse errors.
    assert parse_php_fatal(text) is None


def test_pdo_exception():
    text = (
        "Fatal error: Uncaught PDOException: SQLSTATE[42S02] table not found in /app/db.php:55\n"
        "  thrown in /app/db.php on line 55\n"
    )
    out = parse_php_fatal(text)
    assert out is not None
    exc, msg, _, _ = out
    assert exc == "PDOException"
    assert "SQLSTATE" in msg


# ---- parse_php_fatal: rejection / boundary ---------------------------


def test_warning_not_fatal_rejected():
    """A warning / notice is NOT a fatal -- we don't claim it."""
    text = "PHP Warning: Undefined variable $foo in /app/x.php on line 3"
    assert parse_php_fatal(text) is None


def test_no_uncaught_keyword_rejected():
    """The ``Uncaught`` keyword is the discriminator."""
    text = "Fatal error: Something went wrong"
    assert parse_php_fatal(text) is None


def test_empty_text():
    assert parse_php_fatal("") is None
    assert parse_php_fatal("   ") is None


def test_python_traceback_not_matched():
    """Python traceback must NOT register as a PHP fatal."""
    text = "Traceback (most recent call last):\n  File 'x.py', line 1\nValueError: bad"
    assert parse_php_fatal(text) is None


def test_node_stacktrace_not_matched():
    text = "Error: kaboom\n    at Object.<anonymous> (foo.js:5:10)"
    assert parse_php_fatal(text) is None


# ---- parse_error_text wiring (full pipeline) ------------------------


def test_parse_error_text_tags_php_framework():
    text = (
        "Fatal error: Uncaught TypeError: Foo::bar(): Argument #1 must be int\n"
        "Stack trace:\n"
        "#0 /app/main.php(12): Foo->bar('hi')\n"
        "  thrown in /app/lib/Foo.php on line 42\n"
    )
    out = parse_error_text(text)
    assert out.framework == "php"
    assert out.exception == "TypeError"
    assert out.file == "/app/lib/Foo.php"
    assert out.line == 42


def test_parse_error_text_php_likely_cause_typeerror():
    text = (
        "Fatal error: Uncaught TypeError: Argument #1 must be of type int\n"
        "  thrown in /app/x.php on line 5\n"
    )
    out = parse_error_text(text)
    assert out.framework == "php"
    assert out.likely_cause is not None
    assert "type" in out.likely_cause.lower()


def test_parse_error_text_php_likely_cause_runtime():
    text = (
        "Fatal error: Uncaught RuntimeException: boom\n"
        "  thrown in /app/x.php on line 5\n"
    )
    out = parse_error_text(text)
    assert out.framework == "php"
    assert out.likely_cause is not None
    assert "runtime" in out.likely_cause.lower()


def test_parse_error_text_php_likely_cause_argument_count():
    text = (
        "Fatal error: Uncaught ArgumentCountError: Too few arguments to function "
        "Foo::bar(), 0 passed and exactly 1 expected\n"
        "  thrown in /app/x.php on line 5\n"
    )
    out = parse_error_text(text)
    assert out.framework == "php"
    assert out.likely_cause is not None
    assert "argument" in out.likely_cause.lower()


def test_parse_error_text_php_likely_cause_division_by_zero():
    text = (
        "Fatal error: Uncaught DivisionByZeroError: Division by zero\n"
        "  thrown in /app/x.php on line 5\n"
    )
    out = parse_error_text(text)
    assert out.likely_cause is not None
    assert "zero" in out.likely_cause.lower()


def test_parse_error_text_php_likely_cause_class_not_found():
    text = (
        "Fatal error: Uncaught Error: Class \"App\\Missing\" not found in /app/main.php:5\n"
        "  thrown in /app/main.php on line 5\n"
    )
    out = parse_error_text(text)
    assert out.likely_cause is not None
    assert "autoloader" in out.likely_cause.lower() or "class" in out.likely_cause.lower()


def test_parse_error_text_php_likely_cause_invalid_argument():
    text = (
        "Fatal error: Uncaught InvalidArgumentException: bad input\n"
        "  thrown in /app/x.php on line 5\n"
    )
    out = parse_error_text(text)
    assert out.likely_cause is not None
    assert "argument" in out.likely_cause.lower()


def test_parse_error_text_php_likely_cause_pdo():
    text = (
        "Fatal error: Uncaught PDOException: SQLSTATE bad\n"
        "  thrown in /app/x.php on line 5\n"
    )
    out = parse_error_text(text)
    assert out.likely_cause is not None
    assert "database" in out.likely_cause.lower()


def test_parse_error_text_php_likely_cause_out_of_bounds():
    text = (
        "Fatal error: Uncaught OutOfBoundsException: index 5 of 3\n"
        "  thrown in /app/x.php on line 5\n"
    )
    out = parse_error_text(text)
    assert out.likely_cause is not None
    assert "bounds" in out.likely_cause.lower() or "index" in out.likely_cause.lower()


def test_parse_error_text_php_likely_cause_logic_exception():
    text = (
        "Fatal error: Uncaught LogicException: should never happen\n"
        "  thrown in /app/x.php on line 5\n"
    )
    out = parse_error_text(text)
    assert out.likely_cause is not None
    assert "logic" in out.likely_cause.lower()


# ---- ordering vs other frameworks -----------------------------------


def test_php_beats_jvm_branch():
    """A PHP fatal must not be tagged as JVM by the generic
    \\w+Exception regex."""
    text = (
        "Fatal error: Uncaught RuntimeException: boom\n"
        "  thrown in /app/x.php on line 5\n"
    )
    out = parse_error_text(text)
    assert out.framework == "php"
    assert out.framework != "jvm"


def test_jvm_still_works_for_pure_java():
    """Sanity check: a Java trace still tags JVM after the PHP
    branch was inserted."""
    text = (
        "Exception in thread \"main\" java.lang.NullPointerException: oops\n"
        "    at com.example.App.main(App.java:10)\n"
    )
    out = parse_error_text(text)
    assert out.framework == "jvm"


def test_python_still_works_after_php_branch():
    """Sanity check: a Python traceback still tags python."""
    text = (
        "Traceback (most recent call last):\n"
        "  File \"x.py\", line 1, in <module>\n"
        "    raise ValueError('bad')\n"
        "ValueError: bad\n"
    )
    out = parse_error_text(text)
    assert out.framework == "python"


def test_php_works_with_multiline_stack():
    text = (
        "PHP Fatal error: Uncaught LogicException: bad state\n"
        "Stack trace:\n"
        "#0 /app/main.php(12): App\\Foo->bar()\n"
        "#1 /app/main.php(20): App\\Foo->run()\n"
        "#2 {main}\n"
        "  thrown in /app/lib/Foo.php on line 88\n"
    )
    out = parse_error_text(text)
    assert out.framework == "php"
    assert out.exception == "LogicException"
    assert out.file == "/app/lib/Foo.php"
    assert out.line == 88


def test_php_handles_nested_namespace_with_uncaught_keyword():
    text = (
        "Fatal error: Uncaught App\\Services\\PaymentFailureException: "
        "card declined\n"
        "  thrown in /app/Services/Payment.php on line 33\n"
    )
    out = parse_error_text(text)
    assert out.framework == "php"
    assert out.exception is not None
    assert "PaymentFailureException" in out.exception
    assert out.line == 33
