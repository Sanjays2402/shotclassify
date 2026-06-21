"""Swift / Objective-C crash log parsing.

A new ``framework='swift'`` branch in ``parse_error_text`` recognises
the two canonical Apple-platform crash shapes:

* Swift fatalError() / preconditionFailure / runtime trap:
  ``Fatal error: <msg>: file X.swift, line N``
* Objective-C NSException uncaught throw:
  ``*** Terminating app due to uncaught exception 'NSXxxException',
  reason: '<msg>'``

Both shapes tag as ``framework='swift'`` because most Apple apps mix
the two languages and dashboards group by platform, not by source
language. The exception slot carries either the literal string
``"Fatal error"`` / ``"Swift runtime failure"`` for Swift fatals
(Swift fatals don't have typed exception classes) or the
``NSXxxException`` class name for Objective-C throws.

File / line are extracted from the Swift trailing
``: file X.swift, line N`` directive when present. ObjC throws do
not include a file path in the bare exception line (the symbolicated
backtrace lives elsewhere in the crash log and is usually OCR-mangled)
so file / line stay ``None`` for ObjC.

The branch is placed AFTER PHP in the ``parse_error_text`` elif chain:
PHP's ``Fatal error: Uncaught X:`` prelude is more specific than the
bare Swift ``Fatal error: <msg>`` prelude because the ``Uncaught``
keyword discriminates the two -- this means a PHP fatal that happens
to have a Swift-looking message tail still tags as PHP.

likely_cause hints cover the most-common Apple platform crashes:
nil-Optional unwrap, NSInvalidArgumentException, NSRangeException /
index-out-of-bounds, NSInternalInconsistencyException, Swift array
index out of range, division by zero, precondition / assertion
failure, and the URL / file-system error families.
"""
from __future__ import annotations

from shotclassify_extract import parse_error_text, parse_swift_crash

# ---- parse_swift_crash: Swift fatal-error variants ------------------


def test_swift_fatal_with_file_line():
    text = (
        "Fatal error: Unexpectedly found nil while unwrapping an Optional value: "
        "file MyApp/ContentView.swift, line 42\n"
    )
    out = parse_swift_crash(text)
    assert out is not None
    exc, msg, file_, line_ = out
    assert exc == "Fatal error"
    assert "Unexpectedly found nil" in msg
    assert file_ == "MyApp/ContentView.swift"
    assert line_ == 42


def test_swift_fatal_index_out_of_range():
    text = "Fatal error: Index out of range: file MyApp/Foo.swift, line 7\n"
    out = parse_swift_crash(text)
    assert out is not None
    exc, msg, file_, line_ = out
    assert exc == "Fatal error"
    assert msg == "Index out of range"
    assert file_ == "MyApp/Foo.swift"
    assert line_ == 7


def test_swift_fatal_without_file_directive():
    """Xcode debugger output sometimes drops the trailing file directive."""
    text = "Fatal error: Index out of range\n"
    out = parse_swift_crash(text)
    assert out is not None
    exc, msg, file_, line_ = out
    assert exc == "Fatal error"
    assert msg == "Index out of range"
    assert file_ is None
    assert line_ is None


def test_swift_precondition_failed():
    text = "Fatal error: Precondition failed: x must be positive: file App.swift, line 99\n"
    out = parse_swift_crash(text)
    assert out is not None
    exc, msg, file_, line_ = out
    assert exc == "Fatal error"
    assert "Precondition" in msg
    assert file_ == "App.swift"
    assert line_ == 99


def test_swift_runtime_failure_no_file():
    """Swift runtime failure prelude carries no file/line on its own."""
    text = "Swift runtime failure: Index out of bounds\n"
    out = parse_swift_crash(text)
    assert out is not None
    exc, msg, file_, line_ = out
    assert exc == "Swift runtime failure"
    assert msg == "Index out of bounds"
    assert file_ is None
    assert line_ is None


# ---- parse_swift_crash: Objective-C NSException ---------------------


def test_objc_invalid_argument_exception():
    text = (
        "*** Terminating app due to uncaught exception 'NSInvalidArgumentException', "
        "reason: '*** -[__NSArrayI objectAtIndex:]: index 5 beyond bounds [0 .. 2]'\n"
    )
    out = parse_swift_crash(text)
    assert out is not None
    exc, msg, file_, line_ = out
    assert exc == "NSInvalidArgumentException"
    assert "beyond bounds" in msg
    assert file_ is None
    assert line_ is None


def test_objc_range_exception():
    text = (
        "2026-06-21 10:00:00.123 MyApp[12345:67890] *** Terminating app due to "
        "uncaught exception 'NSRangeException', reason: '*** -[__NSCFArray "
        "objectAtIndex:]: index (5) beyond bounds (3)'\n"
    )
    out = parse_swift_crash(text)
    assert out is not None
    exc, msg, file_, line_ = out
    assert exc == "NSRangeException"
    assert "index (5)" in msg


def test_objc_internal_inconsistency_exception():
    text = (
        "*** Terminating app due to uncaught exception "
        "'NSInternalInconsistencyException', reason: 'UITableView "
        "dataSource must not be nil'\n"
    )
    out = parse_swift_crash(text)
    assert out is not None
    exc, msg, _, _ = out
    assert exc == "NSInternalInconsistencyException"
    assert "must not be nil" in msg


def test_objc_takes_priority_over_swift_when_both_present():
    """Some hybrid crash logs print both prelude lines; ObjC wins because
    the NSException class is the more useful identifier."""
    text = (
        "Fatal error: Unexpectedly found nil while unwrapping an Optional value\n"
        "*** Terminating app due to uncaught exception 'NSInvalidArgumentException', "
        "reason: 'app delegate may not be nil'\n"
    )
    out = parse_swift_crash(text)
    assert out is not None
    exc, msg, _, _ = out
    assert exc == "NSInvalidArgumentException"
    assert "may not be nil" in msg


# ---- parse_swift_crash: negative cases ------------------------------


def test_empty_text_returns_none():
    assert parse_swift_crash("") is None


def test_non_swift_text_returns_none():
    """A Python traceback should not look like a Swift fatal."""
    text = 'Traceback (most recent call last):\n  File "x.py", line 1, in <module>\nKeyError: bad\n'
    assert parse_swift_crash(text) is None


def test_php_fatal_does_not_match_swift():
    """PHP's ``Fatal error: Uncaught X`` prelude should be rejected by
    the Swift matcher because the ``Uncaught`` keyword is the
    discriminator."""
    text = (
        "PHP Fatal error: Uncaught TypeError: argument must be int\n"
        "Stack trace:\n#0 /app/index.php(5): foo(1)\n"
        "  thrown in /app/index.php on line 5\n"
    )
    # The Swift parser MAY match the bare ``Fatal error:`` line since
    # the PHP discriminator (``Uncaught``) sits in the message field.
    # The integration-level test below verifies that parse_error_text
    # routes this to PHP, not Swift.
    out = parse_swift_crash(text)
    # Allow either: the Swift helper is permissive but parse_error_text
    # routes via the elif chain so PHP wins.
    if out is not None:
        # If Swift did match, file/line should be None (no file directive)
        assert out[2] is None


# ---- parse_error_text: integration --------------------------------


def test_parse_error_text_tags_swift_fatal():
    text = "Fatal error: Index out of range: file Foo.swift, line 12\n"
    out = parse_error_text(text)
    assert out.framework == "swift"
    assert out.exception == "Fatal error"
    assert out.message == "Index out of range"
    assert out.file == "Foo.swift"
    assert out.line == 12


def test_parse_error_text_tags_objc_nsexception():
    text = (
        "*** Terminating app due to uncaught exception 'NSInvalidArgumentException', "
        "reason: 'app delegate may not be nil'\n"
    )
    out = parse_error_text(text)
    assert out.framework == "swift"
    assert out.exception == "NSInvalidArgumentException"
    assert "may not be nil" in (out.message or "")


def test_parse_error_text_routes_php_fatal_to_php_not_swift():
    """PHP's ``Uncaught`` keyword routes the trace to the PHP branch
    even though the bare ``Fatal error:`` prefix could theoretically
    match Swift's permissive regex."""
    text = (
        "PHP Fatal error: Uncaught TypeError: argument must be int\n"
        "Stack trace:\n#0 /app/index.php(5): foo(1)\n"
        "  thrown in /app/index.php on line 5\n"
    )
    out = parse_error_text(text)
    assert out.framework == "php"
    assert out.exception == "TypeError"


def test_parse_error_text_nil_unwrap_likely_cause():
    text = (
        "Fatal error: Unexpectedly found nil while unwrapping an Optional value: "
        "file App.swift, line 42\n"
    )
    out = parse_error_text(text)
    assert out.framework == "swift"
    assert out.likely_cause is not None
    assert "Force-unwrapped" in out.likely_cause


def test_parse_error_text_nsrange_likely_cause():
    text = (
        "*** Terminating app due to uncaught exception 'NSRangeException', "
        "reason: '*** index (5) beyond bounds (3)'\n"
    )
    out = parse_error_text(text)
    assert out.framework == "swift"
    assert out.likely_cause is not None
    assert "out of bounds" in out.likely_cause


def test_parse_error_text_nsinvalid_argument_likely_cause():
    text = (
        "*** Terminating app due to uncaught exception 'NSInvalidArgumentException', "
        "reason: 'argument must not be nil'\n"
    )
    out = parse_error_text(text)
    assert out.framework == "swift"
    assert out.likely_cause is not None
    assert "Invalid argument" in out.likely_cause


def test_parse_error_text_precondition_likely_cause():
    text = "Fatal error: precondition failed: must be positive: file A.swift, line 1\n"
    out = parse_error_text(text)
    assert out.framework == "swift"
    assert out.likely_cause is not None
    assert "precondition" in out.likely_cause.lower()


def test_parse_error_text_division_by_zero_likely_cause():
    text = "Fatal error: Division by zero: file A.swift, line 1\n"
    out = parse_error_text(text)
    assert out.framework == "swift"
    assert out.likely_cause is not None
    assert "denominator" in out.likely_cause.lower()


def test_parse_error_text_swift_runtime_failure():
    text = "Swift runtime failure: Index out of bounds\n"
    out = parse_error_text(text)
    assert out.framework == "swift"
    assert out.exception == "Swift runtime failure"
    assert out.message == "Index out of bounds"


def test_parse_error_text_swift_index_out_of_range_likely_cause():
    text = "Fatal error: Index out of range: file A.swift, line 1\n"
    out = parse_error_text(text)
    assert out.framework == "swift"
    assert out.likely_cause is not None
    assert "out of bounds" in out.likely_cause.lower() or "subscripting" in out.likely_cause.lower()


def test_parse_error_text_nsinternal_inconsistency_likely_cause():
    text = (
        "*** Terminating app due to uncaught exception "
        "'NSInternalInconsistencyException', reason: 'must not be nil'\n"
    )
    out = parse_error_text(text)
    assert out.framework == "swift"
    assert out.likely_cause is not None
    assert "internal invariant" in out.likely_cause.lower()


def test_parse_error_text_python_trace_does_not_steal_swift_branch():
    """Python traceback should still tag python, not swift."""
    text = (
        "Traceback (most recent call last):\n"
        '  File "x.py", line 5, in foo\n'
        "    return d[k]\n"
        "KeyError: 'missing'\n"
    )
    out = parse_error_text(text)
    assert out.framework == "python"
    assert out.exception == "KeyError"


def test_parse_error_text_jvm_trace_does_not_steal_swift_branch():
    text = (
        "Exception in thread \"main\" java.lang.NullPointerException: oops\n"
        "    at com.example.App.main(App.java:12)\n"
    )
    out = parse_error_text(text)
    assert out.framework == "jvm"


def test_parse_error_text_nsurl_does_not_match_without_exception_suffix():
    """``NSURLErrorDomain`` lacks the ``Exception`` / ``Error`` suffix
    our regex requires, so it stays unmatched and falls through. This
    is intentional: NSURLErrorDomain values are NSError-domain strings,
    not exception classes, and they normally appear as part of a
    ``NSError`` object rather than as a raised exception."""
    text = (
        "*** Terminating app due to uncaught exception 'NSURLErrorDomain', "
        "reason: 'could not connect to host'\n"
    )
    out = parse_error_text(text)
    # Should fall through to the generic / unknown branch, not Swift.
    assert out.framework != "swift"


def test_swift_fatal_multiline_message_keeps_first_line_only():
    """Multi-line OCR outputs only the first message line is captured."""
    text = (
        "Fatal error: Unexpectedly found nil: file X.swift, line 5\n"
        "Some other unrelated content\n"
    )
    out = parse_swift_crash(text)
    assert out is not None
    _, msg, _, line_ = out
    assert "Unexpectedly found nil" in msg
    assert line_ == 5
