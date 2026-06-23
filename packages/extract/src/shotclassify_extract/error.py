"""Error / stacktrace extractor."""
from __future__ import annotations

import re

from shotclassify_common import ErrorFields, OCRResult

_PY_TRACE = re.compile(r"Traceback \(most recent call last\):")
_PY_FRAME = re.compile(r'File "([^"]+)", line (\d+)')
_PY_EXC = re.compile(r"^([A-Z][A-Za-z0-9_]*Error|Exception)\s*:?\s*(.*)$", re.MULTILINE)
# Python SyntaxError caret indicator. Python prints the offending
# source line, an optional whitespace prefix matching the source
# indent, then a run of ``^`` characters pointing at the bad token /
# span. CPython 3.10+ also prints ``~~~~^^^^~~~~`` shapes where the
# tildes cover the whole expression and the carets pin the operator;
# we accept both purely-caret and tilde+caret shapes. The caret line
# must be on its own line and contain only whitespace + ``~`` + ``^``.
_PY_SYNTAX_EXC = re.compile(
    r"^(?P<exc>SyntaxError|IndentationError|TabError|UnicodeDecodeError|"
    r"UnicodeEncodeError)\s*:\s*(?P<msg>.*)$",
    re.MULTILINE,
)
_PY_CARET_LINE = re.compile(r"^(?P<prefix>[ \t]*)(?P<arrows>[~^]*\^[~^]*)\s*$", re.MULTILINE)
_JS_AT = re.compile(r"\s+at\s+\S+\s+\(([^):]+):(\d+):(\d+)\)")
_JS_EXC = re.compile(r"^(\w*Error)\s*:\s*(.*)$", re.MULTILINE)
_JAVA_EXC = re.compile(r"^(?:Exception in thread .* )?([\w.$]+(?:Exception|Error))\s*:\s*(.*)$", re.MULTILINE)

# .NET / C# stacktraces. The CLR prints exceptions as
# ``System.NullReferenceException: Object reference ...`` followed by
# frames like ``   at Foo.Bar.Baz(int x) in C:\src\x.cs:line 42``.
# Some traces (web logs, container output) omit the file/line portion
# and only show ``   at Namespace.Type.Method(...)``. We accept both.
#
# We require the exception namespace to start with ``System.`` or any
# CamelCase ``Word.Word`` with an ``Exception`` suffix so the regex does
# not accidentally fire on a generic Python or Java line.
_DOTNET_EXC = re.compile(
    r"^([A-Z][\w]*(?:\.[A-Z][\w]*)+Exception)\s*:\s*(.*)$",
    re.MULTILINE,
)
# Frame WITH source file/line: ``   at NS.T.M(args) in C:\path\f.cs:line 12``
# The file segment is a non-whitespace blob ending in ``.cs`` / ``.vb`` /
# ``.fs`` -- using ``\S+?`` (non-greedy) lets Windows drive paths like
# ``C:\src\App.cs`` survive the drive-letter colon (a ``[^:]`` class
# would stop at the first ``:`` and miss ``:line`` entirely).
_DOTNET_FRAME_FILE = re.compile(
    r"^\s*at\s+[\w.<>`\$]+(?:\([^)]*\))?\s+in\s+(?P<file>\S+?(?:\.cs|\.vb|\.fs)):line\s+(?P<line>\d+)\s*$",
    re.MULTILINE,
)
# Frame WITHOUT source: ``   at NS.T.M(args)``. Used only to detect that
# this trace looks like .NET when no file/line is present.
_DOTNET_FRAME_BARE = re.compile(
    r"^\s*at\s+[A-Z][\w<>`\$]*(?:\.[A-Z][\w<>`\$]*)+\s*\([^)]*\)\s*$",
    re.MULTILINE,
)

# Erlang / Elixir crash report shapes. Elixir prints exceptions as:
#   ** (RuntimeError) some message
#       (app 0.1.0) lib/foo.ex:42: Foo.bar/2
#       (elixir 1.14.0) lib/elixir/foo.ex:99: anonymous fn/0 in Foo.baz/0
# Erlang prints them as:
#   ** exception error: no function clause matching foo:bar(undefined)
#        in function  foo:bar/1
#           called as foo:bar(undefined)
#        in call from foo:baz/0
# Both shapes start with the literal ``** `` prefix which is unique
# enough to be the discriminator. We require either the parenthesised
# exception (Elixir) or the ``exception <kind>:`` shape (Erlang) on
# the line.
_BEAM_EXC_ELIXIR = re.compile(
    r"^\*\*\s+\((?P<exc>[A-Z][\w.]*(?:Error|Exception)?)\)\s*(?P<msg>.*)$",
    re.MULTILINE,
)
# Erlang prelude: ``** exception error: ...`` / ``** exception throw: ...``
# / ``** exception exit: ...``. The kind word goes into the exception
# slot so dashboards can distinguish error vs throw vs exit.
_BEAM_EXC_ERLANG = re.compile(
    r"^\*\*\s+exception\s+(?P<exc>error|throw|exit)\s*:\s*(?P<msg>.*)$",
    re.MULTILINE | re.IGNORECASE,
)
# Frame for either runtime. Elixir prints:
#   ``    (app 0.1.0) lib/foo.ex:42: Foo.bar/2``
# Erlang prints:
#   ``     in function  foo:bar/1`` (no file/line)
#   or, in newer OTP, ``     in function  foo:bar/1 (foo.erl, line 42)``
# We capture file + line from the Elixir shape and the newer Erlang
# shape; the older bare-function Erlang line is recognised only as
# "this looks like BEAM" so the framework tag is still set.
_BEAM_FRAME_ELIXIR = re.compile(
    r"^\s*\([\w\s.\-]+\)\s+(?P<file>[\w./\-]+\.(?:ex|exs|erl)):(?P<line>\d+):\s*",
    re.MULTILINE,
)
_BEAM_FRAME_ERLANG = re.compile(
    r"^\s*in\s+(?:call\s+from\s+|function\s+)([\w.:]+/\d+)"
    r"(?:\s*\((?P<file>[\w./\-]+\.erl),\s*line\s+(?P<line>\d+)\))?",
    re.MULTILINE,
)


def _beam_likely_cause(exception: str | None, message: str | None) -> str | None:
    """Return operator-friendly hints for common BEAM crashes.

    The BEAM runtime has a small set of high-frequency crashes that
    dominate production logs -- match clauses, undefined functions,
    badarg, badmap, badkey. The hints are intentionally short.
    """
    exc = (exception or "").lower()
    msg = (message or "").lower()
    if "no function clause matching" in msg:
        return "No function clause matched the arguments; add a fallback head."
    if "no case clause matching" in msg:
        return "No case clause matched the value; add a catch-all branch."
    if "undefined function" in msg or "no such function" in msg:
        return "Function does not exist; check module load and arity."
    if "badmap" in msg or "bad map" in msg:
        return "Value passed to map operation was not a map."
    if "badarg" in msg or "bad argument" in msg:
        return "Built-in received a bad argument; check the value type."
    if "badkey" in msg or "key not found" in msg:
        return "Map lookup with a missing key; use Map.get/3 with default."
    if "key error" in msg or "keyerror" in exc:
        return "Map lookup with a missing key; use Map.get/3 with default."
    if "argumenterror" in exc:
        return "Argument out of range or wrong type; validate before call."
    if "runtimeerror" in exc:
        return "Generic runtime crash; inspect the message."
    if "matcherror" in exc or "match" in exc and "error" in exc:
        return "Pattern match failed; the value did not fit the LHS pattern."
    if "throw" in exc:
        return "Uncaught throw; wrap the caller in try/catch or fix the throw site."
    return None


# Go panic format:
#   panic: runtime error: invalid memory address or nil pointer dereference
#   [signal SIGSEGV...]
#
#   goroutine 1 [running]:
#   main.run(...)
#           /path/to/file.go:42 +0x12
_GO_PANIC = re.compile(r"^\s*panic:\s*(.*)$", re.MULTILINE)
_GO_FRAME = re.compile(r"^\s+(\S+\.go):(\d+)\b", re.MULTILINE)
_GO_GOROUTINE = re.compile(r"^\s*goroutine\s+\d+\s+\[", re.MULTILINE)

# Ruby / Rails stacktrace lines look like:
#   /app/foo.rb:42:in `method': undefined method `bar' for nil:NilClass (NoMethodError)
#   or
#   from /app/foo.rb:42:in `method'
# The exception name in Ruby/Rails commonly includes a namespace
# separator (``ActiveRecord::RecordNotFound``), and not every Rails
# exception ends in Error/Exception (``ActiveRecord::RecordNotFound``
# is the canonical example). The regex captures any
# capitalized-CamelCase token at end of line in parens.
_RUBY_FRAME = re.compile(r"^\s*(?:from\s+)?([\w./_-]+\.rb):(\d+):in\s+`", re.MULTILINE)
_RUBY_EXC = re.compile(r"\(([A-Z][\w:]*)\)\s*$", re.MULTILINE)
_RUBY_MSG = re.compile(r":in\s+`[^']+':\s*(.+?)\s*\(", re.MULTILINE)

# Rust panic format. Older Rust prints:
#   thread 'main' panicked at 'index out of bounds: ...', src/main.rs:5:8
# Modern Rust (1.72+) prints:
#   thread 'main' panicked at src/main.rs:5:8:
#   index out of bounds: ...
# We accept either. ``_RUST_PANIC_OLD`` captures (message, file, line)
# in one pass; ``_RUST_PANIC_NEW`` captures (file, line) and the message
# is the next line.
_RUST_PANIC_OLD = re.compile(
    r"thread\s+'[^']*'\s+panicked\s+at\s+'(?P<msg>[^']*)',\s*"
    r"(?P<file>[\w./\-]+\.rs):(?P<line>\d+)(?::\d+)?",
)
_RUST_PANIC_NEW = re.compile(
    r"thread\s+'[^']*'\s+panicked\s+at\s+"
    r"(?P<file>[\w./\-]+\.rs):(?P<line>\d+)(?::\d+)?:\s*\n\s*(?P<msg>[^\n]+)",
)

# PHP fatal-error stacktraces. PHP prints a top-level fatal in one
# of two shapes:
#
#   Fatal error: Uncaught TypeError: Foo::bar(): Argument #1 ($x) must
#       be of type int, string given, called in /var/www/app/main.php
#       on line 12 and defined in /var/www/app/lib/Foo.php:42
#   Stack trace:
#   #0 /var/www/app/main.php(12): Foo->bar('hi')
#   #1 {main}
#     thrown in /var/www/app/lib/Foo.php on line 42
#
# Or, in modern Laravel / Symfony console output (no leading prelude):
#
#   PHP Fatal error:  Uncaught RuntimeException: boom in /app/index.php:5
#   Stack trace:
#   #0 {main}
#     thrown in /app/index.php on line 5
#
# We recognise the exception line (with or without the leading
# ``PHP `` prefix) and pull file + line from the trailing
# ``thrown in PATH on line N`` directive because that's the
# innermost frame. When that directive is absent we fall back to
# ``in PATH:LINE`` printed inside the exception line itself.
_PHP_EXC = re.compile(
    r"^\s*(?:PHP\s+)?Fatal\s+error\s*:\s*Uncaught\s+"
    r"(?P<exc>[A-Z][\w\\]*(?:Exception|Error|Throwable)?)"
    r"\s*:?\s*(?P<msg>[^\n]*)$",
    re.MULTILINE | re.IGNORECASE,
)
_PHP_THROWN_IN = re.compile(
    r"thrown\s+in\s+(?P<file>\S+\.php)\s+on\s+line\s+(?P<line>\d+)",
    re.IGNORECASE,
)
# Inline "in /path.php:LINE" form used when the trace is one-line.
_PHP_INLINE_LOC = re.compile(
    r"\bin\s+(?P<file>\S+\.php):(?P<line>\d+)\b",
)
# Stack-trace marker ``Stack trace:`` followed by ``#0 ... .php(NN):``
# frames. Used as a soft confirmation when the ``Fatal error`` prelude
# is malformed (OCR truncation can drop the prelude); when both the
# prelude AND a stack-trace frame are missing the branch is skipped.
_PHP_STACK_FRAME = re.compile(
    r"^\s*#\d+\s+(?P<file>\S+\.php)\((?P<line>\d+)\)\s*:",
    re.MULTILINE,
)
# Soft Laravel / Symfony banner used as a fall-through hint when the
# Fatal-error prelude is OCR-truncated. We only TAG framework='php'
# when one of these (or the stack-trace marker above) is present.
_PHP_TRACE_MARKER = re.compile(r"^\s*Stack\s+trace\s*:\s*$", re.MULTILINE | re.IGNORECASE)

# Swift / Objective-C crash log parsing. Apple platforms (iOS / macOS /
# watchOS / tvOS) print two distinct crash shapes:
#
# Swift fatalError() / preconditionFailure / runtime trap:
#   Fatal error: Unexpectedly found nil while unwrapping an Optional value:
#       file MyApp/ContentView.swift, line 42
#   Fatal error: Index out of range: file MyApp/Foo.swift, line 7
#   Swift runtime failure: Index out of bounds
#
# Objective-C NSException:
#   *** Terminating app due to uncaught exception 'NSInvalidArgumentException',
#       reason: '*** -[__NSArrayI objectAtIndex:]: index 5 beyond bounds [0 .. 2]'
#   *** Terminating app due to uncaught exception 'NSRangeException',
#       reason: '*** -[NSMutableArray insertObject:atIndex:]: object cannot be nil'
#
# Both shapes are framework='swift' (we don't split Swift vs Objective-C
# because most Apple apps mix them). The exception slot carries the
# concrete Swift error wording for Swift fatals and the NSException
# class name for Objective-C throws. File / line come from the trailing
# ``file X.swift, line N`` directive on Swift fatals; ObjC throws do
# not include a file by default (only a symbolicated backtrace which
# OCR rarely captures cleanly) so file/line stay None.
_SWIFT_FATAL = re.compile(
    r"^\s*(?:Swift/[\w]+\.swift:\d+:\s*)?"
    r"Fatal\s+error\s*:\s*"
    r"(?P<msg>[^:\n][^\n]*?)"
    r"(?:\s*:\s*file\s+(?P<file>[\w./\\-]+\.(?:swift|m|mm|h)),\s*"
    r"line\s+(?P<line>\d+))?\s*$",
    re.MULTILINE,
)
# Swift runtime failure prelude. Rarely printed alongside file/line so
# we capture it as a softer signal that confirms framework='swift' when
# the canonical Fatal-error prelude is absent.
_SWIFT_RUNTIME = re.compile(
    r"^\s*Swift\s+runtime\s+failure\s*:\s*(?P<msg>[^\n]+)$",
    re.MULTILINE | re.IGNORECASE,
)
# Objective-C NSException uncaught-throw. The ``***`` prelude and the
# ``uncaught exception '<NSExceptionClass>'`` discriminator make this
# unambiguous. ``reason: '...'`` carries the message.
_OBJC_EXC = re.compile(
    r"\*{3}\s*Terminating\s+app\s+due\s+to\s+uncaught\s+exception\s+"
    r"'(?P<exc>NS\w+(?:Exception|Error))'\s*,\s*"
    r"reason\s*:\s*'(?P<msg>[^']*)'",
)


# Kotlin coroutine exception parsing. Kotlin coroutines extend the JVM
# stacktrace shape with two distinctive markers that let us tag the
# crash as a coroutine-specific failure (helpful when triaging
# suspended-function bugs):
#
# JobCancellationException (cooperative cancellation):
#   kotlinx.coroutines.JobCancellationException: Job was cancelled;
#       job=StandaloneCoroutine{Cancelling}@1a2b3c4d
#       at kotlinx.coroutines.JobSupport.cancelMakeCompleting(JobSupport.kt:1543)
#       at kotlinx.coroutines.AbstractCoroutine.cancel(AbstractCoroutine.kt:107)
#
# Coroutine frames inside a regular Throwable trace:
#   java.lang.IllegalStateException: oops
#       at com.app.MainKt$main$1.invokeSuspend(Main.kt:12)
#       at kotlin.coroutines.jvm.internal.BaseContinuationImpl.resumeWith(...)
#       at kotlinx.coroutines.DispatchedTask.run(DispatchedTask.kt:106)
#       at kotlinx.coroutines.scheduling.CoroutineScheduler.runWorker(...)
#
# Discriminator: a top-level ``kotlinx.coroutines.X`` exception class,
# OR a frame line that contains ``kotlinx.coroutines.`` or a synthesised
# ``invokeSuspend`` frame (the suspending-function wrapper Kotlin
# generates). We tag the framework as ``kotlin`` regardless of which
# exception class is on top so dashboards can group all coroutine
# failures together. The branch sits BEFORE the JVM branch in
# parse_error_text because the same trace would otherwise tag as ``jvm``
# (Kotlin compiles to JVM bytecode and the frame shape is the same).
_KOTLIN_COROUTINE_EXC = re.compile(
    r"^(?:Caused\s+by\s*:\s*)?(?P<exc>kotlinx\.coroutines\.\w+(?:Exception|Error))"
    r"[ \t]*:?[ \t]*(?P<msg>[^\n]*)$",
    re.MULTILINE,
)
_KOTLIN_COROUTINE_FRAME = re.compile(
    r"\bat\s+(?:kotlinx\.coroutines\.[\w$.]+|[\w$.]+\$\w+\$\d+\.invokeSuspend)",
)
# Kotlin frame file/line extractor. Kotlin compiles to JVM and prints
# frames as ``at com.app.Pkg.Fn(File.kt:NN)`` -- distinct from Java
# frames only by the ``.kt`` extension. We use this to pull the
# innermost Kotlin source location once we've decided to tag the crash
# as kotlin.
_KOTLIN_FRAME_KT = re.compile(
    r"^\s*at\s+[\w$.]+\(([\w./\-]+\.kts?):(\d+)\)",
    re.MULTILINE,
)


# SQL database error parsing. Each major SQL engine prints distinct
# error preludes that let us pick the dialect:
#
#   PostgreSQL: ``ERROR:  syntax error at or near "x"``
#               ``ERROR:  relation "users" does not exist``
#               ``ERROR:  column "x" of relation "y" does not exist``
#               ``LINE 1: SELECT bad SQL ...``
#               (PostgreSQL psql output often includes a HINT: line
#               and a STATEMENT: line; we capture the LINE: marker
#               as the source location.)
#
#   MySQL:      ``ERROR 1064 (42000): You have an error in your SQL...``
#               ``ERROR 1146 (42S02): Table 'db.users' doesn't exist``
#               ``ERROR 1054 (42S22): Unknown column 'x' in 'field list'``
#               (MySQL prints a SQLSTATE in parens after the code.)
#
#   SQLite:     ``Error: near "x": syntax error``
#               ``Error: no such table: users``
#               ``Error: no such column: x``
#
#   MSSQL:      ``Msg 207, Level 16, State 1, Line 5``
#               ``Invalid column name 'x'.``
#               (MSSQL prints the message on the line AFTER the Msg
#               header; we capture both.)
#
# We try each dialect's discriminator in priority order and tag the
# framework as ``sql`` regardless (with ``exception`` carrying the
# dialect-and-code identifier).
_SQL_MYSQL = re.compile(
    r"\bERROR\s+(?P<code>\d{4})\s*\((?P<sqlstate>[A-Z0-9]{5})\)\s*:\s*"
    r"(?P<msg>[^\n]+)",
    re.IGNORECASE,
)
_SQL_POSTGRES = re.compile(
    r"^\s*ERROR\s*:\s+(?P<msg>[^\n]+)",
    re.MULTILINE,
)
_SQL_POSTGRES_LINE = re.compile(
    r"^\s*LINE\s+(?P<line>\d+)\s*:", re.MULTILINE,
)
_SQL_SQLITE = re.compile(
    r"^\s*(?:SQL\s+)?Error\s*:\s+(?P<msg>(?:near|no\s+such|too\s+many|"
    r"foreign\s+key|incomplete|unrecognized|unknown)[^\n]+)",
    re.MULTILINE,
)
_SQL_MSSQL = re.compile(
    r"^\s*Msg\s+(?P<code>\d+)\s*,\s*Level\s+(?P<level>\d+)\s*,\s*"
    r"State\s+(?P<state>\d+)\s*(?:,\s*Line\s+(?P<line>\d+))?",
    re.MULTILINE | re.IGNORECASE,
)

# Pytest assertion failure. The "long" output shape pytest emits is:
#   ____________________ test_name ____________________
#       def test_name():
#   >       assert foo == bar
#   E       AssertionError: ...
#   tests/test_x.py:12: AssertionError
#
# We anchor on the final ``FILE:LINE: AssertionError`` (or
# ``FILE:LINE: ExceptionName``) line because the visual divider rows
# vary. We also accept the older short shape:
#   FILE:LINE: in test_name
#       assert foo == bar
# This isn't a full pytest parser; it's a single-failure summary
# extractor, which is the vast majority of pytest screenshots.
_PYTEST_ASSERT_LINE = re.compile(
    r"^E\s+(?P<exc>[A-Z][\w]*(?:Error|Exception|AssertionError))\s*:?\s*(?P<msg>.*)$",
    re.MULTILINE,
)
_PYTEST_FAILURE_TAIL = re.compile(
    r"^(?P<file>[\w./\-]+\.py):(?P<line>\d+):\s*(?P<exc>[A-Z][\w]*(?:Error|AssertionError|Exception))\s*$",
    re.MULTILINE,
)
# pytest marks the failing source line with ``>`` followed by the
# expression. That's an ``assert ...`` in 95% of cases but it can be
# any expression (a function call that raised, a comparison, etc.) so
# we capture the whole line content rather than locking to ``assert``.
_PYTEST_ASSERT_EXPR = re.compile(r"^>\s+(?P<expr>\S.*?)\s*$", re.MULTILINE)


def parse_syntax_caret(text: str) -> tuple[str, str, int, int] | None:
    """Return ``(exception, source_line, caret_start, caret_end)`` when
    ``text`` carries a Python ``SyntaxError`` / ``IndentationError`` /
    ``TabError`` with the caret indicator. Returns ``None`` otherwise.

    The exception is taken from the trailing ``SyntaxError: msg`` line.
    The source line is the line printed IMMEDIATELY ABOVE the caret
    line (CPython always prints them in that order: source, then
    pointer). The caret span is ``(start_column, end_column)`` 0-indexed
    columns into the source line so dashboards can highlight the bad
    token. CPython 3.10+ prints multi-char ``~~~~^^^^~~~~`` shapes that
    cover the whole expression; we capture the FULL caret span (tildes
    included) because the carets within mark the operator and the
    tildes mark the operands.
    """
    if not text:
        return None
    exc_m = _PY_SYNTAX_EXC.search(text)
    if not exc_m:
        return None
    exc_name = exc_m.group("exc")
    # Find the caret line and the source line printed directly above it.
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = _PY_CARET_LINE.match(line)
        if not m:
            continue
        if i == 0:
            # Caret with no source line above is malformed; skip.
            continue
        source = lines[i - 1]
        prefix = m.group("prefix") or ""
        arrows = m.group("arrows") or ""
        start = len(prefix)
        end = start + len(arrows)
        # Reject the all-frame-bar pattern CPython prints between
        # frames (a dashed/under-line that contains a ``^``). A real
        # caret line never has anything but tildes and carets.
        if not arrows or arrows.strip("~^") != "":
            continue
        # Source line must not be empty -- prevents capturing the
        # caret of a frame whose source the OCR truncated.
        if not source.strip():
            continue
        return exc_name, source, start, end
    return None


def parse_rust_panic(text: str) -> tuple[str, int, str] | None:
    """Return ``(file, line, message)`` for a Rust panic, or None.

    Recognises both the pre-1.72 form
    ``thread 'main' panicked at 'msg', src/foo.rs:5:8`` and the modern
    1.72+ form ``thread 'main' panicked at src/foo.rs:5:8:\\nmsg``.
    """
    return _parse_rust_panic(text)


def parse_pytest_failure(
    text: str,
) -> tuple[str, int, str | None, str | None] | None:
    """Return ``(file, line, exception, assert_expr or message)`` for a
    pytest failure summary, or ``None`` when the text does not look
    like pytest output.
    """
    return _parse_pytest_failure(text)


def parse_beam_crash(text: str) -> tuple[str, str, str | None, int | None] | None:
    """Return ``(framework, exception, file or None, line or None)``
    for an Erlang or Elixir crash report, or ``None`` if no BEAM
    crash signature is present.

    The framework tag is ``elixir`` when the ``** (ExcModule.Error)``
    Elixir shape is present and ``erlang`` when the ``** exception
    error|throw|exit:`` Erlang shape is present. File and line are
    pulled from the first frame that carries them (Elixir always
    does; older Erlang frames carry only the function/arity).
    """
    return _parse_beam_crash(text)


def parse_php_fatal(text: str) -> tuple[str, str, str | None, int | None] | None:
    """Return ``(exception, message, file or None, line or None)`` for
    a PHP fatal-error stacktrace, or ``None`` when no PHP fatal
    signature is present.

    The exception name keeps any namespace prefix (``Symfony\\\\Component
    \\\\Foo\\\\BarException``) because Laravel / Symfony codebases
    routinely throw namespace-qualified exceptions. The trailing
    ``thrown in PATH on line N`` directive is the innermost frame;
    when that's missing we fall back to the inline ``in PATH:LINE``
    form (which sits inside the exception line itself).
    """
    return _parse_php_fatal(text)


def parse_swift_crash(text: str) -> tuple[str, str, str | None, int | None] | None:
    """Return ``(exception, message, file or None, line or None)`` for
    a Swift fatalError() / Objective-C NSException uncaught throw, or
    ``None`` when no Apple-platform crash signature is present.

    For Swift the exception slot carries the literal string
    ``"Fatal error"`` (or ``"Swift runtime failure"`` for runtime
    traps) because Swift fatals don't have a typed exception class.
    For Objective-C the exception slot carries the NSException class
    name (``NSInvalidArgumentException`` / ``NSRangeException`` /
    etc.). File / line are pulled from the Swift
    ``: file X.swift, line N`` directive when present; ObjC throws
    don't include one inline so the slots stay ``None``.
    """
    return _parse_swift_crash(text)


def parse_vue_error(text: str) -> tuple[str, str, str | None, int | None] | None:
    """Return ``(exception, message, file or None, line or None)`` for
    a Vue.js component error, or ``None`` when no Vue signature is
    present.

    Detection requires the ``[Vue warn]:`` prefix combined with a
    recognised Vue slot (``Error in v-on handler``, ``Error in
    mounted hook``, ``Error in render``, ``Error in callback for
    watcher``, ``Unhandled error during execution``, or
    ``Hydration <kind> mismatch``). Without the prefix the wording
    alone is too generic to discriminate from prose so we never
    tag as Vue.

    The exception slot prefers the quoted inner exception (``"TypeError:
    foo"``) when present; otherwise the slot name itself becomes the
    exception class (``HydrationNodeMismatch`` / ``VueUnhandledError(...)``).
    The file slot is the innermost ``.vue`` component file from the
    ``found in`` tree, falling back to ``<ComponentTag>`` when no
    file path is printed. Line is always ``None`` because Vue's
    warn handler doesn't print per-frame line numbers.
    """
    return _parse_vue_error(text)


def parse_react_error_boundary(
    text: str,
) -> tuple[str, str, str | None, int | None] | None:
    """Return ``(exception, message, file or None, line or None)`` for
    a React error-boundary console dump, or ``None`` when no React
    signature is present.

    React 16+ prints a distinctive error-boundary console output with
    one of these signatures:

      * ``The above error occurred in the <Component> component`` --
        the canonical React 16+ wrapper that React Dev prepends to
        every unhandled error inside a rendered subtree.
      * ``React will try to recreate this component tree`` -- the
        legacy React 15 boundary message.
      * ``Consider adding an error boundary to your tree`` -- the
        suggestion footer React appends when no boundary catches
        the error.
      * ``componentDidCatch`` / ``getDerivedStateFromError`` mentions
        with surrounding React context (component tree, key prop
        warning, render method) -- typed lifecycle method names.

    The exception slot prefers the quoted inner exception (``Error:
    Cannot read property...``) when present in the trace; otherwise
    falls back to the component-name tag (``ReactRenderError(App)``).
    The file slot is the innermost component name from the React
    component-tree dump (``in App (at src/App.tsx:42)``), falling
    back to ``<Component>`` form when no file is printed. The line
    slot is captured from the same component-tree entry when
    present.

    Detection is placed BEFORE the generic Node branch because the
    React error often includes a JS stack tail that the bare
    _JS_AT pattern would otherwise steal as framework='node',
    losing the React-specific signal (boundary-status, component
    name, lifecycle method).
    """
    return _parse_react_error_boundary(text)


def parse_kotlin_coroutine(
    text: str,
) -> tuple[str | None, str | None, str | None, int | None] | None:
    """Return ``(exception, message, file or None, line or None)`` for a
    Kotlin coroutine crash, or ``None`` when no coroutine signature is
    present.

    A coroutine signature is either a top-level
    ``kotlinx.coroutines.XException`` exception class, OR any frame
    that references ``kotlinx.coroutines.`` / the synthesised
    ``invokeSuspend`` wrapper Kotlin emits for suspending functions.

    When the top exception IS a ``kotlinx.coroutines.`` class we
    surface that as the exception; otherwise we fall through to the
    standard JVM ``ClassName: message`` line. File / line are pulled
    from the innermost Kotlin ``.kt`` / ``.kts`` frame, skipping the
    Java framework plumbing on the bottom of the trace.
    """
    return _parse_kotlin_coroutine(text)


def parse_sql_error(text: str) -> tuple[str, str, str, int | None] | None:
    """Return ``(dialect, exception, message, line or None)`` for a SQL
    error, or ``None`` when no SQL-error signature is present.

    ``dialect`` is one of ``postgres`` / ``mysql`` / ``sqlite`` /
    ``mssql``. ``exception`` is the dialect-specific identifier
    string suitable for grouping (``MySQL 1064``,
    ``PostgreSQL ERROR``, ``SQLite Error``, ``MSSQL Msg 207``).
    ``message`` is the human-readable description after the prelude.
    ``line`` is the source line number when the engine prints one
    (PostgreSQL ``LINE 1:`` marker, MSSQL ``Line N``); MySQL and
    SQLite typically don't include a line number so ``line`` is
    ``None`` for those.

    Dialect priority (first to match wins):

      1. MySQL    - the ``ERROR NNNN (SQLSTATE):`` shape is unique.
      2. MSSQL    - the ``Msg NNNN, Level N, State N`` header is unique.
      3. SQLite   - ``Error: near|no such|...`` with vocab match.
      4. Postgres - ``ERROR: msg`` (the most generic, runs last).
    """
    return _parse_sql_error(text)


def parse_spring_whitelabel(
    text: str,
) -> tuple[str, str, str | None, int | None] | None:
    """Return ``(exception, message, path or None, status or None)``
    for a Spring Boot WhiteLabel error page, or ``None`` when no
    WhiteLabel signature is present.

    The exception slot prefers a Java-style FQCN
    (``com.example.app.NotFoundException``) when included in the
    stack-trace dump (server.error.include-stacktrace=always);
    otherwise it falls back to Spring's HTTP reason phrase tagged
    as ``Type: <reason>``. The message slot is the captured
    exception message when present, else a composed
    ``HTTP <status> on <path>`` summary so dashboards still have a
    triage tag. The path is the failing request path when Spring
    printed ``no explicit mapping for /xxx``, else ``None``. The
    status is the integer HTTP status code from the
    ``(type=..., status=NNN)`` summary line.
    """
    return _parse_spring_whitelabel(text)


def parse_graphql_error(
    text: str,
) -> tuple[str, str, str | None, int | None] | None:
    """Return ``(exception, message, path or None, line or None)`` for
    a GraphQL error response, or ``None`` when no GraphQL error
    signature is present.

    The exception slot prefers ``extensions.code`` from the first
    error entry when present (standard GraphQL classification:
    GRAPHQL_VALIDATION_FAILED / BAD_USER_INPUT / UNAUTHENTICATED /
    FORBIDDEN / etc); falls back to a generic ``GraphQLError`` tag
    when no code is included.

    The message slot is the first error's ``message`` field with
    JSON string escapes unescaped (``\\\"`` -> ``\"``, ``\\n`` ->
    newline, ``\\u00XX`` -> Unicode). The path slot is the
    dotted/indexed GraphQL path (``users.0.name``) when present --
    GraphQL's equivalent of "where in the response did the error
    happen". The line slot is the source-document line number from
    ``locations[0].line`` when present.

    Detection requires an ``"errors": [`` array literal AND at least
    one ``"message": "..."`` field AND one discriminator
    (``"locations"`` / ``"path"`` / ``"extensions"`` / GraphQL
    vocabulary) so a generic JSON error response doesn't
    false-positive.
    """
    return _parse_graphql_error(text)


def _parse_sql_error(text: str) -> tuple[str, str, str, int | None] | None:
    if not text:
        return None
    # 1) MySQL: ``ERROR 1064 (42000): You have an error in your SQL...``
    m = _SQL_MYSQL.search(text)
    if m:
        code = m.group("code")
        sqlstate = m.group("sqlstate")
        msg = m.group("msg").strip()
        exc = f"MySQL {code} ({sqlstate})"
        return "mysql", exc, msg, None
    # 2) MSSQL: ``Msg 207, Level 16, State 1, Line 5`` + next-line
    #    message ``Invalid column name 'x'.``
    m = _SQL_MSSQL.search(text)
    if m:
        code = m.group("code")
        line_ = int(m.group("line")) if m.group("line") else None
        # The actual message sits on the LINE AFTER the Msg header.
        # Pull it by walking forward from m.end() to the next newline
        # and taking the following non-empty line.
        after = text[m.end():]
        msg = ""
        for raw in after.splitlines():
            line = raw.strip()
            if line:
                msg = line.rstrip(".")
                break
        exc = f"MSSQL Msg {code}"
        return "mssql", exc, msg, line_
    # 3) SQLite: ``Error: near "x": syntax error`` -- the vocabulary
    #    discriminator inside the regex keeps us off other ``Error:``
    #    lines.
    m = _SQL_SQLITE.search(text)
    if m:
        msg = m.group("msg").strip().rstrip(".")
        return "sqlite", "SQLite Error", msg, None
    # 4) PostgreSQL: ``ERROR:  syntax error at or near "x"``. We
    #    intentionally run this LAST because ``ERROR:`` is the most
    #    generic prelude and would steal a SQLite ``Error:`` line if
    #    case-insensitivity collided.
    m = _SQL_POSTGRES.search(text)
    if m:
        msg = m.group("msg").strip().rstrip(".")
        # Postgres prints ``LINE N:`` on a separate line below the
        # ERROR: prelude; pick it up if present.
        line_ = None
        line_m = _SQL_POSTGRES_LINE.search(text)
        if line_m:
            line_ = int(line_m.group("line"))
        return "postgres", "PostgreSQL ERROR", msg, line_
    return None


def _sql_likely_cause(dialect: str, message: str | None) -> str | None:
    """Return an operator-friendly hint for the SQL error."""
    msg = (message or "").lower()
    # Cross-dialect vocabulary first.
    if "syntax error" in msg:
        return "SQL syntax error; check the highlighted token / quoting."
    if "no such table" in msg or "does not exist" in msg and "relation" in msg:
        return "Table / relation does not exist; check schema / migration state."
    if "no such column" in msg or "unknown column" in msg or (
        "column" in msg and "does not exist" in msg
    ):
        return "Column does not exist; check schema and the SELECT list."
    if "duplicate" in msg and ("entry" in msg or "key" in msg):
        return "Unique-constraint violation; row already exists."
    if "foreign key" in msg:
        return "Foreign-key constraint violation; referenced row missing."
    if "deadlock" in msg:
        return "Transaction deadlocked; retry with backoff."
    if "lock wait timeout" in msg or "lock timeout" in msg:
        return "Row-level lock contention; reduce transaction span."
    if "permission denied" in msg or "access denied" in msg:
        return "Database role / user lacks the required privilege."
    if "connection refused" in msg:
        return "Database not reachable on the given host / port."
    if "data too long" in msg:
        return "Value exceeds the column's declared length."
    if "cannot be null" in msg or "null value in column" in msg:
        return "NOT NULL column received a NULL; set a value or DEFAULT."
    if "invalid column name" in msg:
        return "Column does not exist; check schema and the SELECT list."
    if dialect == "mysql":
        return "MySQL error; inspect the message and SQLSTATE for the rule."
    if dialect == "postgres":
        return "PostgreSQL error; inspect the message and HINT line."
    if dialect == "sqlite":
        return "SQLite error; inspect the message and statement."
    if dialect == "mssql":
        return "MSSQL error; inspect the Msg / Level / State header."
    return None


def _parse_php_fatal(
    text: str,
) -> tuple[str, str, str | None, int | None] | None:
    if not text:
        return None
    exc_m = _PHP_EXC.search(text)
    if not exc_m:
        # Without the explicit ``Fatal error`` prelude we don't claim
        # the trace. PHP stack traces (``Stack trace:`` + ``#0 ...``)
        # also appear inside warnings / notices that aren't fatals,
        # and we don't want to mis-tag those as ``php`` errors.
        return None
    exc = exc_m.group("exc").strip()
    msg = exc_m.group("msg").strip().rstrip(".")
    # Strip a leading ``in /path/file.php:N`` tail from the message
    # so the inline-location form doesn't pollute the message text.
    msg_loc = _PHP_INLINE_LOC.search(msg)
    if msg_loc:
        msg = (msg[: msg_loc.start()] + msg[msg_loc.end():]).strip().rstrip(",")
    # Prefer ``thrown in PATH on line N`` because it's the innermost
    # frame; fall back to the inline ``in PATH:LINE`` form from the
    # exception line itself.
    file_, line_ = None, None
    thrown = _PHP_THROWN_IN.search(text)
    if thrown:
        file_ = thrown.group("file")
        line_ = int(thrown.group("line"))
    else:
        inline = _PHP_INLINE_LOC.search(exc_m.group(0))
        if inline:
            file_ = inline.group("file")
            line_ = int(inline.group("line"))
    return exc, msg, file_, line_


def _php_likely_cause(exception: str | None, message: str | None) -> str | None:
    """Return operator-friendly hints for common PHP fatal crashes."""
    exc = (exception or "").lower()
    msg = (message or "").lower()
    if "typeerror" in exc or "argument" in msg and "must be of type" in msg:
        return "Argument type mismatch; check the caller's value against the signature."
    if "valueerror" in exc:
        return "Function received a value outside the expected range."
    if "argumentcounterror" in exc or "too few arguments" in msg:
        return "Method called with the wrong number of arguments."
    if "divisionbyzeroerror" in exc or "division by zero" in msg:
        return "Division by zero; guard the denominator."
    if "parseerror" in exc or "syntax error" in msg:
        return "PHP parse error; check the highlighted token / closing brace."
    if "error" in exc and "class" in msg and "not found" in msg:
        return "Autoloader could not resolve the class; check use / namespace."
    if "runtimeexception" in exc:
        return "Generic runtime failure; inspect the message."
    if "logicexception" in exc:
        return "Programming-logic violation; the call should not have happened."
    if "invalidargumentexception" in exc:
        return "Argument failed validation; check caller invariants."
    if "outofboundsexception" in exc or "outofrangeexception" in exc:
        return "Index / key outside the collection's bounds."
    if "pdoexception" in exc or "mysqli" in exc:
        return "Database driver raised; check query SQL and connection state."
    if "exception" in exc and ("permission" in msg or "denied" in msg):
        return "Filesystem / socket permission denied; check ownership."
    if "exception" in exc:
        return "PHP exception; inspect the message and stack trace."
    if "error" in exc:
        return "PHP fatal error; inspect the message and stack trace."
    return None


def _parse_beam_crash(
    text: str,
) -> tuple[str, str, str | None, int | None] | None:
    if not text:
        return None
    elixir = _BEAM_EXC_ELIXIR.search(text)
    if elixir:
        exc = elixir.group("exc")
        file_, line_ = None, None
        frame = _BEAM_FRAME_ELIXIR.search(text)
        if frame:
            file_ = frame.group("file")
            line_ = int(frame.group("line"))
        return "elixir", exc, file_, line_
    erlang = _BEAM_EXC_ERLANG.search(text)
    if erlang:
        exc = erlang.group("exc").lower()
        file_, line_ = None, None
        # Newer OTP frames include ``(file.erl, line N)`` -- pick up
        # the first one that does. Older frames are just function/arity
        # so the framework tag still fires but file/line stay None.
        for m in _BEAM_FRAME_ERLANG.finditer(text):
            if m.group("file"):
                file_ = m.group("file")
                line_ = int(m.group("line"))
                break
        return "erlang", exc, file_, line_
    return None


def _parse_rust_panic(text: str) -> tuple[str, int, str] | None:
    """Return ``(file, line, message)`` for a Rust panic, or None."""
    m = _RUST_PANIC_OLD.search(text)
    if m:
        return m.group("file"), int(m.group("line")), m.group("msg").strip()
    m = _RUST_PANIC_NEW.search(text)
    if m:
        return m.group("file"), int(m.group("line")), m.group("msg").strip()
    return None


def _parse_pytest_failure(
    text: str,
) -> tuple[str, int, str | None, str | None] | None:
    """Return ``(file, line, exception, assert_expr or message)`` for a
    pytest failure summary, or None.

    The exception is taken from the trailing ``FILE:LINE: ExcName``
    line because it always reflects the actual exception class. When
    an ``assert foo`` line is present (the ``>`` indicator pytest
    prints) we surface the bare expression as the message so dashboards
    can show ``assert foo == bar`` instead of the noisy multi-line
    AssertionError detail.
    """
    tail = _PYTEST_FAILURE_TAIL.search(text)
    if not tail:
        return None
    file_ = tail.group("file")
    line_ = int(tail.group("line"))
    exc = tail.group("exc")
    expr_m = _PYTEST_ASSERT_EXPR.search(text)
    if expr_m:
        expr = expr_m.group("expr").strip()
        # Strip a leading ``assert `` so dashboards show the comparison
        # rather than the keyword. ``assert foo == bar`` -> ``foo == bar``.
        if expr.startswith("assert "):
            expr = expr[len("assert "):]
        return file_, line_, exc, expr
    # Fall back to the ``E   AssertionError: <msg>`` line if present.
    msg_m = _PYTEST_ASSERT_LINE.search(text)
    msg = msg_m.group("msg").strip() if msg_m else None
    return file_, line_, exc, msg


# Rust likely_cause helpers. Like Go panics, Rust panics commonly
# print plain English messages, so we lean on substring matches
# rather than parsing the panic type.
def _rust_likely_cause(message: str | None) -> str | None:
    if not message:
        return None
    low = message.lower()
    if "index out of bounds" in low:
        return "Index outside slice / vector bounds; check len() before indexing."
    if "unwrap" in low and ("none" in low or "err" in low):
        return "unwrap() on Err/None; use `?` or `match` to propagate."
    if "attempt to divide by zero" in low:
        return "Division by zero; guard the denominator."
    if "stack overflow" in low:
        return "Unbounded recursion; rewrite iteratively or grow the stack."
    if "called `option::unwrap()` on a `none` value" in low:
        return "unwrap() on None; use `?` or `match` to propagate."
    if "called `result::unwrap()` on an `err` value" in low:
        return "unwrap() on Err; use `?` or `match` to propagate."
    if "attempt to subtract with overflow" in low or "attempt to add with overflow" in low:
        return "Integer arithmetic overflowed; use checked_/saturating_ ops."
    return None


# HTTP status line patterns. Common shapes captured:
#   HTTP/1.1 500 Internal Server Error
#   HTTP 404 Not Found
#   GET /api/users -> 502 Bad Gateway
#   status: 503
#   Response: 401 Unauthorized
# We accept any 1xx-5xx three-digit code that follows the word HTTP or
# an explicit "status"/"response" prefix to avoid catching arbitrary
# three-digit numbers in stacktraces (line numbers, byte offsets).
_HTTP_LINE = re.compile(
    r"\b(?:HTTP(?:/\d+(?:\.\d+)?)?|status|response)\b[^\d\n]{0,12}"
    r"(?P<code>[1-5]\d{2})\b\s*(?P<reason>[A-Za-z][\w \-/.]{0,40})?",
    re.IGNORECASE,
)
# Reason-phrase only path: "404 Not Found" with no HTTP prefix. We
# require the reason phrase to start with an uppercase letter so a
# bare "500 dollars" cannot match.
_HTTP_CODE_REASON = re.compile(
    r"\b(?P<code>[1-5]\d{2})\s+(?P<reason>(?:Not Found|Unauthorized|Forbidden|"
    r"Internal Server Error|Bad Gateway|Bad Request|Service Unavailable|"
    r"Gateway Timeout|Too Many Requests|Method Not Allowed|Conflict|"
    r"Unprocessable Entity|Payload Too Large|OK|Created|Accepted|"
    r"No Content|Moved Permanently|Found|See Other|Not Modified|"
    r"Temporary Redirect|Permanent Redirect))\b"
)


def _http_status_class(code: int) -> str:
    if 100 <= code < 200:
        return "informational"
    if 200 <= code < 300:
        return "success"
    if 300 <= code < 400:
        return "redirect"
    if 400 <= code < 500:
        return "client error"
    return "server error"


def _http_likely_cause(code: int, reason: str | None) -> str | None:
    """Return a one-line operator-friendly hint for the HTTP status."""
    # Specific high-frequency codes get tailored hints; the rest fall
    # back to the class so the field is always populated when we
    # tagged the framework as ``http``.
    specific = {
        400: "Malformed request payload or query.",
        401: "Auth credentials missing or invalid.",
        403: "Credentials valid but the action is not permitted.",
        404: "Endpoint or resource does not exist.",
        405: "Endpoint exists but the HTTP method is wrong.",
        409: "Concurrent modification or unique constraint conflict.",
        413: "Request body exceeds the server upload cap.",
        422: "Validation failed on a well-formed request body.",
        429: "Rate-limited; back off and retry with jitter.",
        500: "Server crashed handling the request; check upstream logs.",
        502: "Upstream service returned an invalid response.",
        503: "Upstream temporarily unavailable; circuit-break or retry.",
        504: "Upstream timed out before responding.",
    }
    if code in specific:
        return specific[code]
    cls = _http_status_class(code)
    return f"HTTP {code} ({cls})."


def parse_http_status(text: str) -> tuple[int, str | None] | None:
    """Return ``(code, reason_phrase or None)`` for the first HTTP
    status found in ``text``, or ``None`` if nothing matched.

    Recognises ``HTTP/1.1 500 Internal Server Error`` style preludes,
    bare ``status: 404`` lines, and well-known reason phrases
    (``404 Not Found``) even when no ``HTTP`` prefix is present.
    """
    if not text:
        return None
    # Try the prefixed form first so a bare "404 Not Found" that also
    # appears later does not steal a real "HTTP 500" prelude.
    m = _HTTP_LINE.search(text)
    if m:
        code = int(m.group("code"))
        reason = (m.group("reason") or "").strip(" -:.") or None
        return code, reason
    m = _HTTP_CODE_REASON.search(text)
    if m:
        return int(m.group("code")), m.group("reason").strip()
    return None


def _parse_swift_crash(
    text: str,
) -> tuple[str, str, str | None, int | None] | None:
    """Return ``(exception, message, file or None, line or None)`` for
    a Swift fatalError() / NSException uncaught throw, or ``None``.

    Recognised shapes:

    * Swift ``Fatal error: <msg>: file X.swift, line N``.
    * Swift ``Fatal error: <msg>`` without the trailing file directive
      (Xcode debugger output sometimes prints only the message line).
    * ObjC ``*** Terminating app due to uncaught exception 'NSFooException',
      reason: '<msg>'``.

    The Swift fatal exception slot is the literal string ``"Fatal error"``
    because Swift fatals carry no typed exception class; the discriminator
    is the message wording. ObjC exceptions carry the ``NSXxxException``
    class as the exception. File / line are pulled from the Swift
    ``file X, line N`` directive when present; ObjC throws don't carry
    one inline so the slots stay ``None``.
    """
    if not text:
        return None
    # ObjC NSException FIRST because the ``***`` prelude is more specific
    # than the bare Swift ``Fatal error:`` prefix. A crash that has BOTH
    # (some Swift apps wrap ObjC bridges) tags as ObjC because the
    # NSException class is the most useful identifier in that case.
    objc = _OBJC_EXC.search(text)
    if objc:
        return objc.group("exc"), objc.group("msg"), None, None
    swift = _SWIFT_FATAL.search(text)
    if swift:
        msg = swift.group("msg").strip().rstrip(":")
        file_ = swift.group("file")
        line_ = int(swift.group("line")) if swift.group("line") else None
        return "Fatal error", msg, file_, line_
    runtime = _SWIFT_RUNTIME.search(text)
    if runtime:
        return "Swift runtime failure", runtime.group("msg").strip(), None, None
    return None


def _swift_likely_cause(exception: str | None, message: str | None) -> str | None:
    """Return operator-friendly hints for common Swift / ObjC crashes."""
    exc = (exception or "").lower()
    msg = (message or "").lower()
    if "unexpectedly found nil" in msg or "unwrapping an optional" in msg:
        return "Force-unwrapped a nil Optional; use guard let or if let."
    if "nsinvalidargumentexception" in exc:
        return "Invalid argument passed to a Cocoa API; check the call site."
    if "nsrangeexception" in exc or "index" in msg and "beyond bounds" in msg:
        return "Index out of bounds; check count before subscripting."
    if "nsinternalinconsistencyexception" in exc:
        return "Cocoa internal invariant violated; usually wrong thread or state."
    if "index out of range" in msg:
        return "Swift array index outside bounds; check count before subscripting."
    if "divide by zero" in msg or "division by zero" in msg:
        return "Division by zero; guard the denominator."
    if "fatal error: precondition" in msg or "precondition failed" in msg:
        return "preconditionFailure tripped; check the failing invariant."
    if "fatal error: assertion" in msg or "assertion failed" in msg:
        return "assertionFailure tripped; check the failing assertion."
    if "nilliteral" in msg or "nil while" in msg:
        return "Operation on nil reference; add a nil-guard or default."
    if "nsfilenosuchfileerror" in exc or "no such file" in msg:
        return "File not found on disk; check path and bundle resources."
    if "nsurlerror" in exc or "url" in msg and ("offline" in msg or "could not connect" in msg):
        return "URL session error; check network and request URL."
    if "objc_exception_throw" in msg:
        return "Objective-C exception thrown from a C bridge."
    return None


def _parse_kotlin_coroutine(
    text: str,
) -> tuple[str | None, str | None, str | None, int | None] | None:
    """Return ``(exception, message, file or None, line or None)`` for a
    Kotlin coroutine crash, or ``None`` when no coroutine signature is
    present.

    Two discriminators trigger the branch: a top-level
    ``kotlinx.coroutines.X`` exception class, OR a regular Throwable
    trace whose frame list contains either ``kotlinx.coroutines.`` or
    a synthesised ``invokeSuspend`` frame (the suspending-function
    wrapper the Kotlin compiler emits). When the top exception IS a
    ``kotlinx.coroutines.`` class we surface that as the exception;
    otherwise we surface whatever exception class appears in the
    standard JVM ``ClassName: message`` line.

    File / line come from the innermost Kotlin (.kt / .kts) frame.
    A pure-Java frame (.java) is ignored as the location because the
    coroutine root cause is almost always in Kotlin code -- Java
    frames on the bottom are framework plumbing (kotlinx.coroutines /
    JobSupport / DispatchedTask) that doesn't help triage.
    """
    if not text:
        return None
    # First check: do we even see a coroutine signal?
    coroutine_exc = _KOTLIN_COROUTINE_EXC.search(text)
    coroutine_frame = _KOTLIN_COROUTINE_FRAME.search(text)
    if not coroutine_exc and not coroutine_frame:
        return None
    # Exception class: prefer the coroutine-specific name when present;
    # otherwise fall back to the standard JVM exception header.
    exc: str | None
    msg: str | None
    if coroutine_exc:
        exc = coroutine_exc.group("exc")
        msg = coroutine_exc.group("msg").strip() or None
    else:
        java = _JAVA_EXC.search(text)
        if java:
            exc = java.group(1)
            msg = java.group(2).strip() or None
        else:
            exc = None
            msg = None
    # Innermost Kotlin frame for file/line. Walk every frame; the LAST
    # one wins (matches the existing python / dotnet / go conventions).
    file_: str | None = None
    line_: int | None = None
    for m in _KOTLIN_FRAME_KT.finditer(text):
        file_, line_ = m.group(1), int(m.group(2))
    return exc, msg, file_, line_


def _kotlin_likely_cause(exception: str | None, message: str | None) -> str | None:
    """Return operator-friendly hints for common Kotlin coroutine crashes."""
    exc = (exception or "").lower()
    msg = (message or "").lower()
    if "jobcancellationexception" in exc or "job was cancelled" in msg:
        return "Coroutine job was cancelled; check cancellation handler / scope."
    if "timeoutcancellationexception" in exc or "timed out waiting" in msg:
        return "withTimeout exceeded; raise the timeout or add fast-fail."
    if "channelclosedexception" in exc or "channel was closed" in msg:
        return "Channel closed under sender or receiver; fix close() lifecycle."
    if "deadlock" in msg and "coroutine" in msg:
        return "Coroutines deadlocked; check Dispatchers and blocking calls."
    if "kotlinnullpointerexception" in exc or ("npe" in exc and "kotlin" in exc):
        return "Force-unwrapped a null value (!!); use ?: or ?.let."
    if "uninitializedpropertyaccessexception" in exc:
        return "Accessed lateinit before initialization; init before use."
    if "illegalstateexception" in exc and ("suspend" in msg or "coroutine" in msg):
        return "Suspending call from wrong context; check Dispatcher / Job state."
    if "illegalstateexception" in exc:
        return "Object in invalid state for the operation; inspect lifecycle."
    if "concurrentmodificationexception" in exc:
        return "Collection mutated during iteration; copy or use synchronized."
    if "kotlinx.coroutines" in exc:
        return "Coroutine framework error; inspect the JobSupport / Dispatcher trace."
    return None


def _likely_cause(framework: str, exception: str | None, message: str | None) -> str | None:
    exc = (exception or "").lower()
    msg = (message or "").lower()
    if "keyerror" in exc:
        return "Missing dictionary key; check upstream source."
    if "attributeerror" in exc:
        return "Object is missing the named attribute; likely None or wrong type."
    if "typeerror" in exc:
        return "Incompatible types passed to a function or operator."
    if "modulenotfounderror" in exc or "no module named" in msg:
        return "Dependency not installed in the active environment."
    if "syntaxerror" in exc:
        # Common Python syntax-error wordings have a tight set of
        # culprits. The caret span isn't used here -- the message text
        # is enough to disambiguate.
        if "invalid syntax" in msg:
            return "Parser hit invalid syntax; check the highlighted token."
        if "unexpected eof" in msg or "unexpected end of file" in msg:
            return "File ended mid-statement; close every brace / paren / quote."
        if "unmatched" in msg:
            return "Unmatched bracket / quote; check pair balance above."
        if "expected" in msg and ":" in msg:
            return "Statement missing trailing ':' (def / if / for / class)."
        if "f-string" in msg:
            return "F-string syntax error; check braces and nested quotes."
        return "Python syntax error; the caret points at the bad token."
    if "indentationerror" in exc:
        return "Indentation is inconsistent; mix of tabs and spaces likely."
    if "taberror" in exc:
        return "TabError: tabs mixed with spaces; use one consistently."
    if "connectionrefused" in msg.replace(" ", "") or "econnrefused" in msg:
        return "Target service is down or wrong host/port."
    if "permission denied" in msg:
        return "File or socket permission denied; check ownership."
    if "nullpointer" in exc:
        return "Dereferenced null reference; add null check or initialize."
    if "indexerror" in exc or "out of bounds" in msg:
        return "Index outside collection length."
    # Go-specific causes (panics commonly print plain messages).
    if framework == "go":
        if "nil pointer" in msg or "invalid memory address" in msg:
            return "Dereferenced a nil pointer; check the value before use."
        if "index out of range" in msg or "slice bounds out of range" in msg:
            return "Slice or array index outside bounds."
        if "concurrent map" in msg:
            return "Concurrent map read/write; protect with sync.Mutex or use sync.Map."
        if "send on closed channel" in msg:
            return "Sender wrote to a channel after close(); fix lifecycle."
        if "deadlock" in msg:
            return "All goroutines asleep; missing receiver / unlock."
    # Ruby / Rails causes.
    if framework == "ruby":
        if "nomethoderror" in exc or "undefined method" in msg:
            return "Receiver does not respond to the called method; likely nil."
        if "namerror" in exc:
            return "Undefined local variable or constant in scope."
        if "argumenterror" in exc or "wrong number of arguments" in msg:
            return "Method invoked with the wrong arity or keyword set."
        if "loaderror" in exc:
            return "Gem or file failed to load; check Gemfile / load path."
        if "activerecord::recordnotfound" in exc:
            return "ActiveRecord lookup returned no row; guard with find_by."
    # .NET / CLR causes. The .NET branch tags ``framework='dotnet'`` and
    # the exception name keeps its namespace (``System.NullReferenceException``)
    # so dashboards can still group by short or full form.
    if framework == "dotnet":
        if "nullreferenceexception" in exc:
            return "Dereferenced a null reference; add null check or initialize."
        if "argumentnullexception" in exc:
            return "Argument was null where the method requires a value."
        if "argumentoutofrangeexception" in exc or "indexoutofrangeexception" in exc:
            return "Index or argument outside the allowed range."
        if "invalidoperationexception" in exc:
            return "Object is in a state that does not permit the operation."
        if "filenotfoundexception" in exc:
            return "Referenced file is missing on disk; check path and packaging."
        if "unauthorizedaccessexception" in exc:
            return "Filesystem or registry permission denied; check ACLs."
        if "dividebyzeroexception" in exc:
            return "Division by zero; guard the denominator."
        if "stackoverflowexception" in exc:
            return "Unbounded recursion; add a base case or convert to iteration."
        if "outofmemoryexception" in exc:
            return "Process exceeded its memory budget; reduce working set."
        if "taskcanceledexception" in exc or "operationcanceledexception" in exc:
            return "Operation was cancelled (timeout or token); inspect deadlines."
    return None


# NestJS framework log shapes. The official Nest logger prints lines
# with a distinctive ``[Nest]`` PID prefix and an ``ERROR [<context>]``
# tag where ``<context>`` is the failing component (``ExceptionsHandler``
# for the default global filter, or ``HttpExceptionFilter`` /
# ``RpcExceptionFilter`` / ``WsExceptionFilter`` for custom filter
# classes; user-defined filters can also surface here).
#
# Example shapes:
#   [Nest] 12345  - 12/22/2026, 10:23:45 AM   ERROR [ExceptionsHandler] User not found
#   [Nest] 12345 - 12/22/2026, 10:23:45 AM   ERROR [HttpException] Unauthorized
#   [Nest] 100 - 01/15/2027, 11:22:33 AM   ERROR [ValidationPipe] Validation failed
#
# The PID + timestamp formatting is consistent across Nest 6+ but the
# exact width / punctuation varies between versions; we accept any
# whitespace between the bracketed prefix and the ERROR tag.
_NEST_PRELUDE = re.compile(
    r"\[Nest\][^\n]*?ERROR\s+\[(?P<context>[\w]+(?:Filter|Handler|Pipe|Exception|Guard)?)\]"
    r"\s*(?P<msg>[^\n]*)",
    re.MULTILINE,
)

# Nest commonly throws subclasses of ``HttpException`` whose names
# follow the ``XxxException`` convention. The exception class is
# usually printed on a subsequent line (a JS stacktrace header like
# ``HttpException: Unauthorized`` / ``NotFoundException: User not
# found`` / ``BadRequestException: Validation failed``).
_NEST_EXC = re.compile(
    r"^(?P<exc>(?:Http|NotFound|Unauthorized|Forbidden|BadRequest|Conflict|"
    r"Gone|UnprocessableEntity|TooManyRequests|InternalServerError|BadGateway|"
    r"ServiceUnavailable|GatewayTimeout|PayloadTooLarge|NotImplemented|"
    r"NotAcceptable|RequestTimeout|MethodNotAllowed|MisdirectedRequest|"
    r"ImATeapot|PreconditionFailed|UnsupportedMediaType|Rpc|"
    r"Ws|Validation)Exception)"
    r"\s*:\s*(?P<msg>.*)$",
    re.MULTILINE,
)


# Spring Boot WhiteLabel error page. Spring's default ``/error`` HTML
# endpoint surfaces a small standalone HTML page that screenshots
# capture often -- a user hits a 404 / 500 and the WhiteLabel page is
# what they paste into their bug report. The page has a distinctive
# layout that doesn't appear anywhere else:
#
#   Whitelabel Error Page
#   This application has no explicit mapping for /error, so you are seeing this as a fallback.
#   Sat May 21 16:14:21 IST 2023
#   There was an unexpected error (type=Not Found, status=404).
#   No message available
#
# Spring Boot 2.x and 3.x both ship this same fallback. The
# ``Whitelabel Error Page`` heading is the unambiguous discriminator;
# the ``type=...`` and ``status=...`` fields carry the exception
# class (Spring's reason phrase) and HTTP status code. The trailing
# ``message`` line is the captured exception message (or the literal
# ``No message available`` when Spring couldn't extract one).
#
# A modern Spring Boot deployment can be configured to disable the
# WhiteLabel page (``server.error.whitelabel.enabled=false``) and
# return a structured JSON body instead -- those cases would tag as
# generic ``jvm`` via the regular stacktrace branch, not here.
_SPRING_WHITELABEL_PRELUDE = re.compile(
    r"Whitelabel\s+Error\s+Page",
    re.IGNORECASE,
)
# The summary line: ``There was an unexpected error (type=Not Found, status=404).``
# Status is always present and always a 3-digit integer; the type
# string is Spring's HTTP reason phrase (``Not Found`` / ``Internal
# Server Error`` / ``Bad Request`` / etc).
_SPRING_WHITELABEL_TYPE = re.compile(
    r"\(\s*type\s*=\s*(?P<type>[^,)]+?)\s*,\s*status\s*=\s*(?P<status>\d{3})\s*\)",
    re.IGNORECASE,
)
# The timestamp line: ``Sat May 21 16:14:21 IST 2023`` (Java's
# Date.toString() format). Captured optionally so it can land in the
# message slot when the printed message is just "No message
# available".
_SPRING_WHITELABEL_DATE = re.compile(
    r"^(?P<date>(?:Sun|Mon|Tue|Wed|Thu|Fri|Sat)\s+"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"\d{1,2}\s+\d{1,2}:\d{2}:\d{2}(?:\s+[A-Z]{2,5})?\s+\d{4})\s*$",
    re.MULTILINE,
)
# Spring's "No message available" placeholder. When the printed
# message line matches this, the real message text is missing.
_SPRING_WHITELABEL_NO_MSG = re.compile(r"^\s*No\s+message\s+available\s*$", re.MULTILINE)
# Path line: ``This application has no explicit mapping for /error``
# - used to capture the request path when present. We stop at the
# first whitespace, comma, semicolon, or closing-paren so trailing
# punctuation in Spring's "/path, so you are seeing this" wording
# doesn't bleed into the path. Path chars per RFC 3986 (plus the
# common query/fragment chars) are: a-z A-Z 0-9 ._~!$&'()*+:@%/?#=&-
# We restrict to a conservative set so OCR noise doesn't run away.
_SPRING_WHITELABEL_PATH = re.compile(
    r"no\s+explicit\s+mapping\s+for\s+(?P<path>/[A-Za-z0-9._~!$&'*+:@%/?#=&\-]*)",
    re.IGNORECASE,
)
# Spring stack-trace exception class can sometimes appear below the
# summary line in a stack-trace dump (when server.error.include-
# stacktrace is set). The shape is ``com.foo.Bar$Baz: message`` --
# the same as JVM but we capture it here separately so we don't have
# to walk into _JAVA_EXC.
_SPRING_WHITELABEL_EXC = re.compile(
    r"^(?P<exc>[a-z][\w]*(?:\.[A-Za-z][\w]*)+(?:Exception|Error))\s*:?\s*(?P<msg>.*)$",
    re.MULTILINE,
)


def _parse_spring_whitelabel(
    text: str,
) -> tuple[str, str, str | None, int | None] | None:
    """Return (exception, message, path, status) for a Spring Boot
    WhiteLabel error page, or None.

    Detection requires the literal ``Whitelabel Error Page`` heading
    (Spring's unambiguous signature) AND the typed summary line
    ``(type=..., status=NNN)``. Without both we return None so a
    document that mentions the phrase in prose (a runbook entry, a
    bug-report template) doesn't false-positive.

    The exception slot is populated with the most informative tag
    available, in this priority:

    1. A Java-style stack-trace exception class
       (``com.example.app.NotFoundException``) when included in the
       output (server.error.include-stacktrace=always).
    2. Spring's HTTP reason phrase as ``Type: <type>``
       (``Not Found`` / ``Internal Server Error``) -- this is always
       printed.

    The message slot is the captured exception message when present;
    when Spring printed ``No message available`` we fall back to a
    composed ``HTTP <status> on <path>`` summary so the dashboard
    still has triage information. The path is pulled from the
    ``no explicit mapping for /xxx`` line when present, else None.
    The status is the integer HTTP status code from the summary
    line (always present when the WhiteLabel page renders).

    Returns ``None`` when the text is not recognisably a Spring
    WhiteLabel page, so the caller can fall through to the regular
    JVM branch (which would otherwise tag the stack-trace dump as
    framework='jvm').
    """
    if not text:
        return None
    if _SPRING_WHITELABEL_PRELUDE.search(text) is None:
        return None
    summary = _SPRING_WHITELABEL_TYPE.search(text)
    if summary is None:
        return None
    type_phrase = summary.group("type").strip()
    try:
        status = int(summary.group("status"))
    except ValueError:
        return None
    # Path lookup (informational; not a hard requirement).
    path_match = _SPRING_WHITELABEL_PATH.search(text)
    path = path_match.group("path") if path_match else None
    # Exception class preference: a Java-style FQCN in the body wins
    # over the bare HTTP reason phrase.
    exc: str | None = None
    msg: str | None = None
    exc_match = _SPRING_WHITELABEL_EXC.search(text)
    if exc_match is not None:
        # Defence: don't accept the WhiteLabel summary line itself or
        # the prelude as the exception. Both contain dots but the
        # WhiteLabel page heading isn't a FQCN.
        candidate = exc_match.group("exc")
        # Reject anything that's clearly not a Java class (no dot, or
        # a single dotted segment that's actually a host like
        # localhost.example.com which wouldn't end in Exception/Error
        # but we add the safety belt).
        if "." in candidate and (
            candidate.endswith("Exception") or candidate.endswith("Error")
        ):
            exc = candidate
            msg_candidate = exc_match.group("msg").strip()
            msg = msg_candidate or None
    if exc is None:
        # Fall back to the HTTP reason phrase tag.
        exc = f"Type: {type_phrase}"
    if msg is None:
        # Look for the printed message line (everything after the
        # summary that isn't the No-message placeholder).
        if _SPRING_WHITELABEL_NO_MSG.search(text):
            # No real message available; compose a triage summary.
            if path:
                msg = f"HTTP {status} on {path}"
            else:
                msg = f"HTTP {status}"
        else:
            # Find the first non-empty line AFTER the type=..., status=...
            # summary that isn't the timestamp or the no-explicit-
            # mapping prose. Spring prints "Message: <msg>" or "<msg>"
            # on a line of its own when include-message=always is set.
            #
            # We iterate by LINE boundaries (not by the summary regex's
            # end offset, which may sit mid-line and leave the line's
            # trailing punctuation as the first "tail" token). Walk
            # ahead to the first newline after the summary's start,
            # then split the rest on newlines.
            summary_line_end = text.find("\n", summary.start())
            if summary_line_end == -1:
                tail = ""
            else:
                tail = text[summary_line_end + 1:]
            for raw in tail.splitlines():
                stripped = raw.strip()
                if not stripped:
                    continue
                # Skip Spring's own date line and the mapping notice.
                if _SPRING_WHITELABEL_DATE.match(raw):
                    continue
                if "no explicit mapping" in stripped.lower():
                    continue
                if "whitelabel" in stripped.lower():
                    continue
                # Skip stack-trace frame lines (they start with ``at ``
                # or are empty). The exception line itself would have
                # been picked up by _SPRING_WHITELABEL_EXC above.
                if stripped.startswith("at "):
                    continue
                # Skip pure HTML closing tags (``</body></html>``) that
                # screenshot-OCR captures from the rendered HTML page.
                if stripped.startswith("<") and stripped.endswith(">") and "</" in stripped:
                    continue
                # Strip a leading "Message:" prefix when present (some
                # Spring versions print this label).
                if stripped.lower().startswith("message:"):
                    stripped = stripped[8:].strip()
                if stripped:
                    msg = stripped
                    break
            if msg is None:
                if path:
                    msg = f"HTTP {status} on {path}"
                else:
                    msg = f"HTTP {status}"
    return exc, msg, path, status


def _spring_whitelabel_likely_cause(status: int | None, exc: str | None, message: str | None) -> str | None:
    """Return operator-friendly hints for common Spring WhiteLabel pages."""
    if status is None:
        return None
    exc_l = (exc or "").lower()
    msg_l = (message or "").lower()
    # Class-level hits dominate the cause hint when present.
    if "notfoundexception" in exc_l or "nosuchelementexception" in exc_l:
        return "Resource missing; check repository lookup before the controller returns."
    if "methodargumentnotvalidexception" in exc_l or "constraintviolationexception" in exc_l:
        return "Request body / params failed validation; check @Valid annotations and DTO."
    if "accessdeniedexception" in exc_l or "authenticationexception" in exc_l:
        return "Spring Security denied the request; check role hierarchy and method security."
    if "httpmessagenotreadable" in exc_l:
        return "Request body could not be deserialised; check Content-Type and JSON schema."
    if "datainsertionexception" in exc_l or "dataintegrityviolation" in exc_l:
        return "DB constraint violated; check unique key / foreign key / not-null."
    if "httpmediatypenotsupported" in exc_l:
        return "Endpoint cannot consume the request Content-Type."
    if "httprequestmethodnotsupported" in exc_l:
        return "Endpoint cannot handle the request method (POST vs GET / etc)."
    if "responsestatusexception" in exc_l or "errorresponseexception" in exc_l:
        return "Controller raised a typed ResponseStatusException; check the source endpoint."
    # Status-level fallback.
    if status == 404:
        return "Route did not match any @RequestMapping; check controller path."
    if status == 401:
        return "Missing or invalid auth credentials; check Spring Security filter chain."
    if status == 403:
        return "Authenticated but lacking required role / permission."
    if status == 400:
        return "Request failed validation; check binding result and validator."
    if status == 409:
        return "Resource conflict; check unique constraint or optimistic lock."
    if status == 415:
        return "Endpoint does not accept the request Content-Type."
    if status == 422:
        return "Semantic validation failed; payload is well-formed but invalid."
    if status == 429:
        return "Rate limit triggered upstream; back off and retry."
    if status == 500 and "no message" in msg_l:
        return "Spring caught an unhandled exception with no message; enable include-stacktrace."
    if status == 500:
        return "Unhandled server exception reached the default error handler."
    if status == 502:
        return "Upstream HTTP / gateway call failed; check RestTemplate / WebClient."
    if status == 503:
        return "Downstream dependency is down or refusing connections."
    if status == 504:
        return "Upstream call exceeded the deadline; raise timeout or add circuit breaker."
    return None


# GraphQL execution error parsing. The GraphQL spec defines a strict
# error shape that every server library (graphql-js, Apollo, Hasura,
# Strawberry, graphene, Yoga, Mercurius) emits when execution fails:
#
#   {
#     "errors": [
#       {
#         "message": "Cannot query field 'foo' on type 'Query'.",
#         "locations": [{"line": 3, "column": 5}],
#         "path": ["users", 0, "name"],
#         "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"}
#       }
#     ],
#     "data": null
#   }
#
# The shape is unambiguous: an "errors" key holding an array of error
# objects each carrying "message" + optional "locations" + optional
# "path" + optional "extensions.code". Compared with the regular HTTP
# 200 OK status that GraphQL servers conventionally return (errors
# live in the JSON body, not the HTTP status), this is the ONLY
# reliable cross-vendor signal that a GraphQL request failed.
#
# Detection requires AT LEAST:
# 1. An ``"errors"`` JSON key (with optional whitespace),
# 2. AT LEAST one ``"message"`` field somewhere after it,
# 3. The discriminator vocabulary -- one of the GraphQL-specific
#    keys (``locations``, ``path``, ``extensions``) OR a GraphQL
#    vocabulary word (``GraphQL``, ``query``, ``mutation``,
#    ``subscription``) on the same OCR capture so plain JSON with
#    an ``errors`` array (a generic API response) isn't false-
#    positiving.
#
# The error code (extensions.code) carries the most useful triage
# signal because GraphQL servers standardise on a small vocabulary:
#
#   GRAPHQL_PARSE_FAILED      - syntax error in the request document
#   GRAPHQL_VALIDATION_FAILED - field doesn't exist, type mismatch
#   BAD_USER_INPUT            - argument validation failed
#   UNAUTHENTICATED           - missing / invalid auth token
#   FORBIDDEN                 - authenticated but no permission
#   PERSISTED_QUERY_NOT_FOUND - APQ cache miss
#   INTERNAL_SERVER_ERROR     - unhandled resolver exception
#
# Apollo / Hasura / Yoga all use this vocabulary; non-conformant
# servers may emit custom codes which we surface verbatim.
_GRAPHQL_ERRORS_KEY = re.compile(r'"errors"\s*:\s*\[', re.IGNORECASE)
_GRAPHQL_MESSAGE_FIELD = re.compile(
    r'"message"\s*:\s*"(?P<msg>(?:[^"\\]|\\.)*)"',
    re.IGNORECASE,
)

# Apollo Client / Apollo Server error preludes. Apollo's client SDK
# wraps GraphQL responses in either a ``Network error: ...`` (fetch
# layer failure) or ``GraphQL error: ...`` (server returned errors)
# message inside a top-level ``ApolloError:`` line. Apollo Server
# additionally throws typed exception classes (``AuthenticationError``,
# ``ForbiddenError``, ``UserInputError``, ``SyntaxError``,
# ``ValidationError``, ``PersistedQueryNotFoundError``, etc) that
# print without the JSON ``errors`` array wrapping.
#
# The bracketed form ``[GraphQLError: <message>]`` shows up in stack
# tails from both client and server (e.g. JS arrays of error objects
# coerced to string via .toString()).
_APOLLO_TOPLEVEL_RE = re.compile(
    # ``ApolloError: <message>`` (client + server both)
    r"\bApolloError\b\s*:\s*(?P<msg>[^\n\r]*)",
)
_APOLLO_BRACKETED_RE = re.compile(
    # ``[GraphQLError: <message>]`` or ``[ApolloError: <message>]``
    # form used by JS array stringification.
    r"\[(?P<exc>(?:GraphQL|Apollo)Error)\s*:\s*(?P<msg>[^\]\n\r]*)\]",
)
# Apollo Server typed exception classes raised before the JSON
# response shape is materialised (e.g. inside a resolver, before
# Apollo wraps into ``errors: []``). When the OCR capture shows the
# raw thrown exception line we want to tag the framework as
# ``apollo`` not generic ``node`` / ``graphql``.
_APOLLO_SERVER_EXC_RE = re.compile(
    r"\b(?P<exc>AuthenticationError|ForbiddenError|UserInputError"
    r"|SyntaxError|ValidationError|PersistedQueryNotFoundError"
    r"|PersistedQueryNotSupportedError"
    r"|ApolloError|ApolloServerError|MissingFieldError)"
    r"\s*:\s*(?P<msg>[^\n\r]+)"
)
# Bare ``ApolloError:`` is the strongest discriminator; the typed
# server classes (SyntaxError / ValidationError) are NOT --
# SyntaxError is a built-in JS class that also fires on plain JS code
# captures. We require an Apollo-vocabulary anchor in the same text
# (``ApolloServer`` / ``apollo`` / ``GraphQLError`` / ``resolveType`` /
# ``Resolver`` / ``graphql`` / ``gql\``) before we accept the typed
# class as Apollo-tagged. Without an anchor those classes fall
# through to whatever framework branch matches next (typically Node).
_APOLLO_ANCHOR_RE = re.compile(
    r"\b(?:Apollo(?:Server|Client|Link)?|apollo-(?:client|server|link)"
    r"|\@apollo/(?:client|server|link)|graphql|GraphQLError|resolveType"
    r"|gql`|useQuery|useMutation|useSubscription|writeQuery|readQuery"
    r"|apolloServer|apolloClient)\b",
    re.IGNORECASE,
)
# Path / line extracted from a stack frame inside the Apollo error.
# Reuses the Node ``at Foo.bar (file.ts:N:M)`` shape so we share
# logic with the existing _JS_AT pattern.
_GRAPHQL_CODE_FIELD = re.compile(
    r'"code"\s*:\s*"(?P<code>[A-Z][A-Z0-9_]{0,79})"',
    re.IGNORECASE,
)
_GRAPHQL_LOCATIONS_FIELD = re.compile(
    r'"locations"\s*:\s*\[\s*\{\s*"line"\s*:\s*(?P<line>\d+)\s*,\s*"column"\s*:\s*(?P<col>\d+)',
    re.IGNORECASE,
)
_GRAPHQL_PATH_FIELD = re.compile(
    r'"path"\s*:\s*\[\s*(?P<path>(?:"[^"]*"|\d+)(?:\s*,\s*(?:"[^"]*"|\d+))*)\s*\]',
    re.IGNORECASE,
)
# Discriminator vocabulary -- any of these strongly suggests GraphQL
# rather than a generic JSON error response. The presence of even
# one is enough to commit because real GraphQL responses always
# carry at least one (the spec mandates that errors must be a list
# and locations/path are conventionally included for actionable
# diagnostics).
_GRAPHQL_DISCRIMINATORS = (
    '"locations"',
    '"path"',
    '"extensions"',
    "graphql",
    "Apollo",
    "apollo",
    "mutation",
    "subscription",
    " query ",
    " query{",
    " query ",
)


def _parse_graphql_error(
    text: str,
) -> tuple[str, str, str | None, int | None] | None:
    """Return (exception, message, path, line) for a GraphQL error
    response, or None.

    Detection requires:
    * An ``"errors": [`` array literal in the text
    * At least one ``"message": "..."`` field inside
    * One discriminator (``"locations"`` / ``"path"`` /
      ``"extensions"`` / GraphQL vocabulary) so a generic JSON
      error response doesn't false-positive

    The exception slot prefers ``extensions.code`` when present
    (the standard GraphQL classification: GRAPHQL_VALIDATION_FAILED,
    BAD_USER_INPUT, UNAUTHENTICATED, FORBIDDEN, etc); falls back to
    a generic ``GraphQLError`` tag when no code is included.

    The message slot is the FIRST error's ``message`` field. When
    multiple errors are present we surface the first because GraphQL
    typically returns them in document order and the first failure
    is usually the root cause.

    The file slot is the dotted/indexed GraphQL path (``users.0.name``)
    when present -- this is GraphQL's equivalent of "where in the
    response did the error happen". The line slot is the source-
    document line number from ``locations[0].line`` when present.

    Returns None when the text is not recognisably a GraphQL error
    response.
    """
    if not text:
        return None
    if _GRAPHQL_ERRORS_KEY.search(text) is None:
        return None
    msg_match = _GRAPHQL_MESSAGE_FIELD.search(text)
    if msg_match is None:
        return None
    # Discriminator check -- one of the GraphQL-specific keys or
    # vocabulary words must be present somewhere in the capture.
    text_lower = text.lower()
    if not any(d.lower() in text_lower for d in _GRAPHQL_DISCRIMINATORS):
        return None
    # Unescape JSON string escapes in the message body.
    raw_msg = msg_match.group("msg")
    msg = _json_string_unescape(raw_msg)
    # Pull the extensions.code from the FIRST error entry. We need to
    # restrict the code search to the same error object as the
    # message -- otherwise an error array with [error1, error2] could
    # cross-stitch message of error1 with code of error2. We use a
    # simple bracket-depth tracker to find the closing brace of the
    # first error object.
    first_error_block = _isolate_first_graphql_error(text, msg_match.start())
    code: str | None = None
    if first_error_block is not None:
        code_match = _GRAPHQL_CODE_FIELD.search(first_error_block)
        if code_match is not None:
            code = code_match.group("code")
    # Locations: line + column from the FIRST error's locations[0].
    line_no: int | None = None
    if first_error_block is not None:
        loc_match = _GRAPHQL_LOCATIONS_FIELD.search(first_error_block)
        if loc_match is not None:
            try:
                line_no = int(loc_match.group("line"))
            except ValueError:
                line_no = None
    # Path: GraphQL ``path`` is an array of string + int segments.
    # We render it as a dotted string for the file slot, matching
    # how GraphQL clients display it (``users.0.name``).
    path_str: str | None = None
    if first_error_block is not None:
        path_match = _GRAPHQL_PATH_FIELD.search(first_error_block)
        if path_match is not None:
            raw_path = path_match.group("path")
            # Parse the comma-separated segments: each is either a
            # quoted string or a bare integer.
            segments: list[str] = []
            for seg_match in re.finditer(r'"([^"]*)"|(\d+)', raw_path):
                if seg_match.group(1) is not None:
                    segments.append(seg_match.group(1))
                elif seg_match.group(2) is not None:
                    segments.append(seg_match.group(2))
            if segments:
                path_str = ".".join(segments)
    # Exception slot: prefer the extensions.code tag; fall back to a
    # generic GraphQLError when no code was emitted.
    if code:
        exc = code
    else:
        exc = "GraphQLError"
    return exc, msg, path_str, line_no


def _isolate_first_graphql_error(text: str, message_pos: int) -> str | None:
    """Return the JSON object containing the message at ``message_pos``,
    or None when bracket-matching fails.

    Walks backwards from ``message_pos`` to find the opening ``{`` of
    the error object, then forwards counting bracket depth to find
    the matching ``}``. The slice between is the JSON object body
    that ``_GRAPHQL_CODE_FIELD`` / ``_GRAPHQL_LOCATIONS_FIELD`` /
    ``_GRAPHQL_PATH_FIELD`` can safely search without picking up
    fields from a sibling error.
    """
    if message_pos < 0 or message_pos >= len(text):
        return None
    # Walk backwards from the message position to find the most
    # recent unmatched '{' that opens the containing object. We
    # track depth so a nested object (like extensions: {code: "X"})
    # before the message gets properly balanced.
    depth = 0
    start = -1
    for i in range(message_pos - 1, -1, -1):
        ch = text[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            if depth == 0:
                start = i
                break
            depth -= 1
    if start == -1:
        return None
    # Now walk forward from start finding the matching closing brace.
    depth = 0
    end = -1
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if escaped:
            escaped = False
            continue
        if in_string:
            if ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        return None
    return text[start:end + 1]


def _json_string_unescape(s: str) -> str:
    """Unescape JSON string escapes (``\\\"`` / ``\\\\`` / ``\\n`` /
    ``\\t`` / ``\\u00XX``). Conservative -- malformed sequences are
    left as-is rather than raising.
    """
    if "\\" not in s:
        return s
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch != "\\" or i + 1 >= len(s):
            out.append(ch)
            i += 1
            continue
        nxt = s[i + 1]
        if nxt == '"':
            out.append('"')
            i += 2
        elif nxt == "\\":
            out.append("\\")
            i += 2
        elif nxt == "/":
            out.append("/")
            i += 2
        elif nxt == "n":
            out.append("\n")
            i += 2
        elif nxt == "t":
            out.append("\t")
            i += 2
        elif nxt == "r":
            out.append("\r")
            i += 2
        elif nxt == "b":
            out.append("\b")
            i += 2
        elif nxt == "f":
            out.append("\f")
            i += 2
        elif nxt == "u" and i + 5 < len(s):
            hex_part = s[i + 2:i + 6]
            try:
                out.append(chr(int(hex_part, 16)))
                i += 6
            except ValueError:
                out.append(ch)
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _parse_apollo_error(
    text: str,
) -> tuple[str, str, str | None, int | None] | None:
    """Return (exception, message, file or None, line or None) for an
    Apollo Client / Apollo Server error, or None when no Apollo
    signature is detectable.

    Apollo has three distinct text shapes that are NOT covered by the
    JSON ``errors: []`` parser in :func:`_parse_graphql_error`:

    1. ``ApolloError: Network error: Failed to fetch``
       (Apollo Client wrapping a fetch failure)
    2. ``ApolloError: GraphQL error: Cannot query field "foo"``
       (Apollo Client wrapping a server GraphQL error)
    3. ``[GraphQLError: Cannot query field "foo" on type "Bar"]``
       (server-side GraphQLError stringified into a stack tail)
    4. ``AuthenticationError: ...`` / ``ForbiddenError: ...`` /
       ``UserInputError: ...`` / ``ValidationError: ...`` /
       ``PersistedQueryNotFoundError: ...`` (Apollo Server typed
       exception classes thrown from a resolver, alongside the
       generic JS stack-trace)

    The typed-server-exception shapes (case 4) ONLY count as Apollo
    when an Apollo-vocabulary anchor sits in the same text -- without
    an anchor those names collide with built-in JS classes (``Syntax
    Error`` / ``ValidationError`` from form libraries) so we let them
    fall through to whatever generic branch matches next.

    Exception slot priority:
      * Bracketed form: ``GraphQLError`` / ``ApolloError`` literal.
      * Top-level ``ApolloError:`` form: ``ApolloError`` literal.
      * Typed-server form: the matched class name.

    Message slot: text after the colon, trimmed. For nested
    ``ApolloError: Network error: detail`` we PRESERVE the inner
    classifier (``Network error: detail``) because dashboards want
    the distinction between network-vs-graphql wrapping.

    File / line: from the innermost JS ``at file.ts:N:M`` frame when
    present; otherwise ``None``.

    Returns ``None`` when:
      * No Apollo / GraphQL prelude is detectable, OR
      * Only a typed-server exception fires but no Apollo anchor is
        present in the surrounding text.
    """
    if not text:
        return None

    # 1) Bracketed [GraphQLError: msg] / [ApolloError: msg] form.
    #    This is the most distinctive shape -- the brackets + colon +
    #    typed class name don't appear anywhere else, so we don't
    #    require an anchor.
    bracket = _APOLLO_BRACKETED_RE.search(text)

    # 2) Top-level ``ApolloError: <msg>`` form. Distinctive enough
    #    that the bare class name alone is sufficient evidence.
    toplevel = _APOLLO_TOPLEVEL_RE.search(text)

    # 3) Typed Apollo-server exception classes. Require an Apollo /
    #    GraphQL anchor in the same text so a stand-alone JS
    #    ``ValidationError: ...`` from a form-library doesn't tag.
    typed = _APOLLO_SERVER_EXC_RE.search(text)
    has_anchor = _APOLLO_ANCHOR_RE.search(text) is not None

    if bracket is None and toplevel is None and (typed is None or not has_anchor):
        return None

    # Priority: bracket > toplevel > typed. The bracket form carries
    # the most-specific class name + body. The toplevel form is
    # explicit about the Apollo wrapper. The typed form is the last
    # resort.
    exc: str
    msg: str
    if bracket is not None:
        exc = bracket.group("exc")
        msg = bracket.group("msg").strip()
    elif toplevel is not None:
        exc = "ApolloError"
        msg = toplevel.group("msg").strip()
    else:
        # typed is not None and has_anchor is True (per the guard above)
        assert typed is not None
        exc = typed.group("exc")
        msg = typed.group("msg").strip()

    # File / line from the innermost JS frame.
    file_: str | None = None
    line_: int | None = None
    for m in _JS_AT.finditer(text):
        file_, line_ = m.group(1), int(m.group(2))

    return exc, msg, file_, line_


def _apollo_likely_cause(exception: str, message: str) -> str | None:
    """Return operator-friendly hints for common Apollo errors.

    Handles both:
      * Apollo Client wrapping shapes (``Network error: ...``,
        ``GraphQL error: ...`` inside an ApolloError message).
      * Apollo Server typed exception classes
        (AuthenticationError / ForbiddenError / UserInputError /
        ValidationError / PersistedQueryNotFoundError).
    """
    exc_l = exception.lower()
    msg_l = message.lower()
    # Apollo Client wrappers -- the inner classifier carries the signal.
    if "network error" in msg_l:
        if "failed to fetch" in msg_l or "fetch failed" in msg_l:
            return (
                "Apollo Client fetch failed; check server URL, CORS, and "
                "network connectivity."
            )
        if "timeout" in msg_l or "timed out" in msg_l:
            return "Apollo Client request timed out; raise timeout or check upstream."
        if "abort" in msg_l:
            return "Apollo Client request aborted; check link middleware and AbortController."
        return "Apollo Client transport error; inspect the link chain and response."
    if "graphql error" in msg_l:
        # The inner GraphQL error tail is the actual server message.
        if "cannot query field" in msg_l:
            return "Field doesn't exist on the parent type; check schema and field name."
        if "syntax" in msg_l:
            return "Request document has a GraphQL syntax error; validate the query string."
        return "Apollo Client received a GraphQL response with errors; inspect the resolver."
    # Apollo Server typed exception classes.
    if "authenticationerror" in exc_l:
        return "Authentication failed; check Authorization header or session cookie."
    if "forbiddenerror" in exc_l:
        return "Authenticated but lacking permission; check role / directive guard."
    if "userinputerror" in exc_l:
        return "Resolver input validation failed; check the variables match scalar / type."
    if "persistedquerynotfounderror" in exc_l:
        return "Automatic Persisted Queries cache miss; resend with full document."
    if "persistedquerynotsupportederror" in exc_l:
        return "Server doesn't support APQ; configure client to send full document."
    if "missingfielderror" in exc_l:
        return "Cache miss for the requested field; check writeQuery / writeFragment shape."
    if "syntaxerror" in exc_l:
        return "Request document has a GraphQL syntax error; validate the query string."
    if "validationerror" in exc_l:
        return "Schema validation failed; check field names, argument types, fragment shape."
    if "apolloservererror" in exc_l or "apolloerror" in exc_l:
        return "Apollo Server reported an unhandled resolver exception; check logs."
    return None


def parse_apollo_error(
    text: str,
) -> tuple[str, str, str | None, int | None] | None:
    """Return ``(exception, message, file or None, line or None)`` for
    an Apollo Client / Apollo Server error, or ``None`` when no Apollo
    signature is present.

    Three recognised shapes:
    * ``[GraphQLError: <msg>]`` / ``[ApolloError: <msg>]`` (stringified
      array entry from JS array of error objects)
    * ``ApolloError: <msg>`` (Apollo Client wrapper; ``<msg>`` is
      typically ``Network error: ...`` or ``GraphQL error: ...``)
    * Apollo Server typed exception classes
      (``AuthenticationError`` / ``ForbiddenError`` / ``UserInputError``
      / ``ValidationError`` / ``PersistedQueryNotFoundError`` /
      ``MissingFieldError``)

    The typed-server-exception shape ONLY counts as Apollo when an
    Apollo vocabulary anchor (``Apollo`` / ``GraphQLError`` / ``gql\\``
    / ``useQuery`` / ``useMutation`` / etc) sits in the same text.
    """
    return _parse_apollo_error(text)


def _graphql_likely_cause(code: str | None, message: str | None) -> str | None:
    """Return operator-friendly hints for common GraphQL error codes."""
    code_l = (code or "").lower()
    msg_l = (message or "").lower()
    if "graphql_parse_failed" in code_l or "syntax error" in msg_l:
        return "Request document has a GraphQL syntax error; validate the query string."
    if "graphql_validation_failed" in code_l:
        return "Schema validation failed; check field names, argument types, fragment shape."
    if "cannot query field" in msg_l:
        return "Field doesn't exist on the parent type; check schema and field name."
    if "bad_user_input" in code_l:
        return "Argument validation failed; check the input scalar / type constraints."
    if "unauthenticated" in code_l or "not authenticated" in msg_l:
        return "Missing or invalid auth token; check Authorization header."
    if "forbidden" in code_l or "not authorized" in msg_l or "permission" in msg_l:
        return "Authenticated but lacking permission; check role / directive guard."
    if "persisted_query_not_found" in code_l:
        return "Automatic Persisted Queries cache miss; resend with full document."
    if "persisted_query_not_supported" in code_l:
        return "Server doesn't support APQ; configure client to send full document."
    if "internal_server_error" in code_l or "internal error" in msg_l:
        return "Unhandled resolver exception; inspect server logs at the resolver path."
    if "rate_limit" in code_l or "too many requests" in msg_l:
        return "Rate limit hit; back off and retry with jitter."
    if "timeout" in code_l or "timed out" in msg_l:
        return "Resolver exceeded the deadline; raise timeout or add field-level caching."
    if "downstream service" in msg_l:
        return "Resolver upstream call failed; check downstream service health."
    if "n+1" in msg_l or "data loader" in msg_l:
        return "N+1 query pattern detected; batch with DataLoader / batched resolver."
    if "complexity" in code_l or "query complexity" in msg_l:
        return "Query exceeds complexity budget; reduce depth / breadth or paginate."
    if "depth" in code_l or "query depth" in msg_l:
        return "Query exceeds depth limit; flatten recursive selection."
    return None


def _parse_nest_error(
    text: str,
) -> tuple[str, str, str | None, int | None] | None:
    """Return (exception, message, file, line) for a NestJS log, or None.

    Detection requires the ``[Nest]`` PID prefix AND an ERROR tag with
    a recognised Nest context (``ExceptionsHandler`` / one of the
    *Filter / *Pipe / *Guard / *Exception suffixed names). When the
    log also includes a JS-style frame (``at Foo.bar (file.ts:N:M)``)
    we pull the innermost frame for file + line.

    Returns ``None`` when the text is not recognisably a NestJS log
    (no ``[Nest]`` prelude or no ERROR tag), so the caller can fall
    through to the generic Node branch.
    """
    if not text:
        return None
    prelude = _NEST_PRELUDE.search(text)
    if prelude is None:
        return None
    # Prefer the typed NestJS exception class if printed (most common
    # in real captures because Nest's filter prints the bare message
    # on the prelude line PLUS a separate exception-class line in
    # the stack tail).
    exc_match = _NEST_EXC.search(text)
    if exc_match is not None:
        exc = exc_match.group("exc")
        # When the exception line has a non-empty message, prefer it
        # over the prelude message (the prelude often duplicates the
        # exception message exactly).
        exc_msg = exc_match.group("msg").strip() or None
        msg = exc_msg or prelude.group("msg").strip() or None
    else:
        # No typed exception class -- fall back to the Nest context
        # name (ExceptionsHandler / HttpExceptionFilter / etc) as the
        # exception slot. This still distinguishes Nest errors from
        # generic JS errors for dashboards.
        exc = prelude.group("context")
        msg = prelude.group("msg").strip() or None
    # Innermost JS frame for file + line (when a stack tail is
    # printed alongside the Nest prelude). The existing _JS_AT
    # pattern handles ``at Foo.bar (file.ts:N:M)`` and TypeScript
    # files (.ts / .tsx) come through fine because the regex
    # captures up to the first ``:`` -- which a .ts path doesn't
    # contain except as the line/column separator.
    file_: str | None = None
    line_: int | None = None
    for m in _JS_AT.finditer(text):
        file_, line_ = m.group(1), int(m.group(2))
    return exc, msg or "", file_, line_


def _nest_likely_cause(exception: str | None, message: str | None) -> str | None:
    """Return operator-friendly hints for common NestJS errors."""
    exc = (exception or "").lower()
    msg = (message or "").lower()
    if "notfoundexception" in exc or "not found" in msg:
        return "Resource missing; check route param and DB row before throwing."
    if "unauthorizedexception" in exc or "unauthorized" in msg:
        return "Missing / expired auth token; check JWT issuer and guard."
    if "forbiddenexception" in exc or "forbidden" in msg:
        return "RBAC denied; check role guard or policy decorator."
    if "badrequestexception" in exc or "bad request" in msg:
        return "Request body / params failed validation; check DTO."
    if "validationexception" in exc or "validation failed" in msg:
        return "class-validator rejected the payload; check DTO constraints."
    if "conflictexception" in exc or "conflict" in msg:
        return "Resource already exists or version conflict; check unique constraint."
    if "unprocessableentityexception" in exc or "unprocessable" in msg:
        return "Semantic validation failed; payload is well-formed but invalid."
    if "toomanyrequestsexception" in exc or "too many requests" in msg:
        return "Rate-limit hit; back off and retry with jitter."
    if "internalservererrorexception" in exc or "internal server error" in msg:
        return "Unhandled downstream failure; check the lower-frame stack."
    if "badgatewayexception" in exc or "bad gateway" in msg:
        return "Upstream HTTP call failed; check timeouts and DNS."
    if "serviceunavailableexception" in exc or "service unavailable" in msg:
        return "Downstream is down or unhealthy; check health endpoint."
    if "gatewaytimeoutexception" in exc or "gateway timeout" in msg:
        return "Upstream call exceeded deadline; raise timeout or add cache."
    if "rpcexception" in exc:
        return "Microservice transport (gRPC / TCP / Redis) failure."
    if "wsexception" in exc:
        return "WebSocket gateway failure; check connection lifecycle."
    if "httpexception" in exc:
        return "HTTP-status exception thrown; check status code and source guard."
    return None


# Vue.js component error shapes. Vue's warnHandler / errorHandler
# (and the default console output in dev mode) emit messages in a
# very characteristic format:
#
#   [Vue warn]: Error in v-on handler: "TypeError: Cannot read properties of undefined (reading 'x')"
#     at <Button onClick=fn> at <HelloWorld>
#
#   [Vue warn]: Error in render: "ReferenceError: foo is not defined"
#     found in
#
#     ---> <HelloWorld> at src/components/HelloWorld.vue
#            <App>
#              <Root>
#
#   [Vue warn]: Error in callback for watcher "count": "TypeError: ..."
#     found in
#       ---> <Counter> at src/components/Counter.vue
#
#   [Vue warn]: Error in mounted hook: "TypeError: Cannot read properties of null"
#     found in
#       ---> <App>
#
# Vue 3 also emits:
#   [Vue warn]: Unhandled error during execution of mounted hook
#     at <App>
#   [Vue warn]: Hydration node mismatch: ...
#
# The ``[Vue warn]:`` prefix is the unambiguous discriminator -- no
# other JS framework prints that bracketed prefix. The ``Error in
# <slot>`` shape names which Vue lifecycle slot blew up
# (v-on handler / render / mounted hook / created hook / updated
# hook / callback for watcher / setup / etc) so dashboards can
# group errors by component lifecycle phase.
_VUE_PRELUDE = re.compile(
    r"\[Vue\s+warn\]\s*:\s*(?P<body>[^\n]+)",
    re.IGNORECASE,
)
# The ``Error in <slot>`` slot identifies the failing lifecycle
# hook / handler. Recognised slots include the canonical Vue
# lifecycle hooks plus the broader ``v-on``, ``render``, ``setup``,
# ``watcher``, ``hydration``, and ``directive`` slots. The slot
# name is captured verbatim so dashboards can group by
# ``v-on handler`` vs ``mounted hook`` vs ``render`` etc.
_VUE_SLOT = re.compile(
    r"Error\s+in\s+(?P<slot>"
    r"v-on\s+handler"
    r"|render(?:\s+function)?"
    r"|setup\s+function"
    r"|render"
    r"|callback\s+for\s+watcher(?:\s+\"[^\"]*\")?"
    r"|directive\s+\w+\s+hook(?:\s+\"[^\"]*\")?"
    r"|(?:beforeCreate|created|beforeMount|mounted|beforeUpdate|updated|"
    r"activated|deactivated|beforeUnmount|unmounted|"
    r"beforeDestroy|destroyed|errorCaptured|renderTracked|renderTriggered|"
    r"serverPrefetch)\s+hook"
    r")\s*:\s*(?P<rest>.*)",
    re.IGNORECASE,
)
# Quoted-string error message: ``"TypeError: foo is not defined"`` --
# the inner exception class + message is what dashboards want as
# the exception slot. The prefix is optional so the bare ``"Error:
# foo"`` shape also lands as exc="Error".
_VUE_QUOTED_ERROR = re.compile(
    r"\"(?P<exc>(?:[A-Z][A-Za-z]*?)?(?:Error|Exception|Warning))\s*:\s*(?P<msg>[^\"]*)\""
)
# Component path / file location from the ``found in`` block:
#   ---> <HelloWorld> at src/components/HelloWorld.vue
# Vue prints the source file alongside the component tag in the
# ``found in`` chain. We pull the INNERMOST component (first ``--->``
# pointer) because that's the leaf where the error originated.
_VUE_COMPONENT_FILE = re.compile(
    r"--->?\s+<\w+>\s+at\s+(?P<file>[\w./\-]+\.vue)",
    re.IGNORECASE,
)
# Component tag without file path: ``<HelloWorld>`` or ``<App>``.
# Fallback when no file path is printed. Two shapes accepted: the
# ``---> <Tag>`` arrow-prefixed entry inside the ``found in`` tree
# AND the bare ``at <Tag>`` indent-prefixed entry from Vue 3's
# Unhandled error handler.
_VUE_COMPONENT_TAG = re.compile(
    r"(?:--->?|\bat)\s+<(?P<tag>\w+)>",
)
# Unhandled error during execution shape (Vue 3 default handler).
_VUE_UNHANDLED = re.compile(
    r"Unhandled\s+error\s+during\s+execution\s+of\s+"
    r"(?P<slot>[\w\s\-]+?(?:\s+hook|\s+handler|\s+watcher|\s+effect)?)\s*(?:[\.:]|$)",
    re.IGNORECASE,
)
# Hydration mismatch shape (Vue 3 SSR/SSG).
_VUE_HYDRATION = re.compile(
    r"Hydration\s+(?P<kind>node|text|class|style|attribute|children)\s+mismatch",
    re.IGNORECASE,
)


def _parse_vue_error(
    text: str,
) -> tuple[str, str, str | None, int | None] | None:
    """Return (exception, message, file, line) for a Vue.js error, or None.

    Detection requires the ``[Vue warn]:`` prefix combined with a
    recognised Vue slot (``Error in v-on handler``, ``Error in
    mounted hook``, ``Error in render``, ``Unhandled error during
    execution``, ``Hydration <kind> mismatch``). Without the prefix
    we never tag as Vue because the slot wording alone is too
    generic to discriminate from prose.

    The exception slot is pulled from the quoted-string error inside
    the warning body (``"TypeError: x is not defined"``) when present;
    otherwise the slot name itself becomes the exception (``v-on
    handler error`` / ``mounted hook error`` / ``hydration mismatch``).

    The file slot is the innermost component file from the ``found
    in`` tree (``src/components/HelloWorld.vue``). When no file is
    printed, fall back to ``<ComponentTag>`` so dashboards still
    have a triage anchor. Line is None because Vue's warn handler
    doesn't print line numbers per-frame.

    Returns None when the prefix is absent so the caller can fall
    through to the generic Node branch (a vanilla JS error caught
    by Vue's errorHandler that doesn't go through ``[Vue warn]``
    looks like a Node error and should tag as such).
    """
    if not text:
        return None
    prelude = _VUE_PRELUDE.search(text)
    if prelude is None:
        return None
    body = prelude.group("body")

    # Identify the slot. Three families: standard ``Error in <slot>``
    # shape, ``Unhandled error during execution of <slot>`` (Vue 3
    # default handler), or ``Hydration <kind> mismatch`` (SSR/SSG).
    slot_match = _VUE_SLOT.search(body)
    unhandled_match = _VUE_UNHANDLED.search(body) if slot_match is None else None
    hydration_match = (
        _VUE_HYDRATION.search(body)
        if (slot_match is None and unhandled_match is None)
        else None
    )

    if slot_match is None and unhandled_match is None and hydration_match is None:
        return None

    # Determine exception + message.
    exc: str
    msg: str | None
    if hydration_match is not None:
        # ``Hydration node mismatch`` / ``Hydration text mismatch`` etc.
        kind = hydration_match.group("kind").lower()
        exc = f"Hydration{kind.capitalize()}Mismatch"
        # Capture the rest of the body (after the mismatch keyword)
        # as the message, trimmed.
        rest = body[hydration_match.end():].strip(" :.")
        msg = rest or None
    elif unhandled_match is not None:
        # ``Unhandled error during execution of mounted hook``.
        slot = unhandled_match.group("slot").strip()
        # Normalise multi-space -> single space.
        slot = re.sub(r"\s+", " ", slot)
        exc = f"VueUnhandledError({slot})"
        # No quoted inner error in this shape; the slot phrase IS
        # the diagnostic. Capture the optional trailing message from
        # the rest of the body if anything follows the slot keyword.
        tail = body[unhandled_match.end():].strip(" :.")
        msg = tail or None
    else:
        assert slot_match is not None  # narrowed
        slot = slot_match.group("slot").strip()
        # Normalise multi-space -> single space for stable storage.
        slot = re.sub(r"\s+", " ", slot)
        rest = slot_match.group("rest") or ""
        # Look for a quoted inner exception in the slot's rest tail
        # OR in the broader text (Vue often line-wraps the quoted
        # message so the closing quote is on a continuation line).
        quoted = _VUE_QUOTED_ERROR.search(rest) or _VUE_QUOTED_ERROR.search(text)
        if quoted is not None:
            exc = quoted.group("exc")
            msg = (
                f"Error in {slot}: " + quoted.group("msg").strip()
            ).strip()
        else:
            # No quoted inner exception -- the slot phrase becomes the
            # exception slot. The body tail becomes the message.
            exc_tag = re.sub(r"\s+", "", slot.title()).replace("-", "")
            exc = f"VueError({slot})" if not exc_tag else f"Vue{exc_tag}Error"
            msg = rest.strip(" :.\"") or None

    # File slot: innermost component file from the ``found in`` tree.
    file_match = _VUE_COMPONENT_FILE.search(text)
    file_: str | None
    if file_match is not None:
        file_ = file_match.group("file").strip()
    else:
        # No .vue file path -- fall back to the leaf component tag.
        tag_match = _VUE_COMPONENT_TAG.search(text)
        if tag_match is not None:
            file_ = f"<{tag_match.group('tag')}>"
        else:
            file_ = None

    return exc, msg or "", file_, None


def _vue_likely_cause(exception: str | None, message: str | None) -> str | None:
    """Return operator-friendly hints for common Vue.js errors."""
    exc = (exception or "").lower()
    msg = (message or "").lower()
    # Hydration mismatches first (most specific class).
    if "hydration" in exc:
        return (
            "SSR / client rendered output differs; check for non-deterministic "
            "data (Date.now, Math.random, window-only refs) inside render."
        )
    # Inner exception class hints (when quoted with a meaningful tail)
    # checked FIRST so a TypeError with "undefined" surfaces the
    # optional-chaining hint instead of the generic slot hint.
    if "typeerror" in exc:
        if "undefined" in msg or "null" in msg:
            return "Property access on undefined / null reactive value; check optional chaining."
    if "referenceerror" in exc:
        return "Variable not defined in template scope; check data / computed / props names."
    if "rangeerror" in exc:
        return "Numeric / iteration overflow; check recursive watchers or v-for keys."
    # Lifecycle / slot-specific causes pulled from the slot phrase.
    if "v-on handler" in msg or "v-on handler" in exc:
        return "Event handler threw; check guard logic and bound function refs."
    if "render" in msg.split(":", 1)[0] or "vuerender" in exc:
        return "Render function threw; check template bindings and component props."
    if "watcher" in msg or "callback for watcher" in msg:
        return "Watcher callback threw; check side-effect inside the watch handler."
    if "mounted hook" in msg or "vuemounted" in exc:
        return "Mounted hook threw; check refs / DOM access deferred to $nextTick."
    if "created hook" in msg or "vuecreated" in exc:
        return "Created hook threw; check data initialisation / API calls in setup."
    if "setup function" in msg or "vuesetup" in exc:
        return "setup() composition function threw; check ref / reactive init."
    if "beforeunmount" in msg or "vuebeforeunmount" in exc:
        return "beforeUnmount hook threw; check cleanup of listeners / timers."
    if "directive" in msg:
        return "Custom directive hook threw; check bind / inserted / componentUpdated."
    if "errorcaptured" in msg or "vueerrorcaptured" in exc:
        return "errorCaptured hook threw; the error handler itself failed."
    # Generic Vue-unhandled / fallthrough.
    if "vueunhandlederror" in exc or "unhandled error" in msg:
        return "Vue caught an unhandled error; provide app.config.errorHandler for triage."
    # Fallback TypeError when no undefined/null hint.
    if "typeerror" in exc:
        return "Type mismatch; check prop types vs component contract."
    return "Vue component error; inspect the component tree and the failing lifecycle hook."


# React error boundary detection. React 16+ prints a distinctive
# console output when an error bubbles up to an error boundary OR
# when no boundary catches the error and the whole tree unmounts.
# The output has a recognisable signature combining one of these
# wrappers:
#
#   * ``The above error occurred in the <Component> component`` --
#     the canonical React 16+ message prepended to every render-
#     phase error not caught by an error boundary.
#   * ``React will try to recreate this component tree`` -- the
#     React 15 / pre-boundary legacy wrapper.
#   * ``Consider adding an error boundary to your tree`` -- the
#     suggestion footer React appends.
#   * ``componentDidCatch`` / ``getDerivedStateFromError`` --
#     typed lifecycle method names that appear in console traces
#     when an error boundary's own handler throws.
#
# Plus the React component-tree dump that follows the wrapper:
#
#   in App (at src/App.tsx:42)
#       in ErrorBoundary
#       in StrictMode
#       in Root (at src/index.tsx:18)
_REACT_BOUNDARY_PRELUDE = re.compile(
    r"The above error occurred in the\s*<(?P<comp>\w+)>\s*component"
    r"|React will try to recreate this component tree"
    r"|Consider adding an error boundary",
    re.IGNORECASE,
)
# Typed lifecycle method markers (used to detect React contexts
# where the prelude wasn't printed but the trace is clearly a
# boundary method failure).
_REACT_LIFECYCLE = re.compile(
    r"\b(componentDidCatch|getDerivedStateFromError)\b"
)
# React component-tree entry: ``in App (at src/App.tsx:42)`` or bare
# ``in App``. The innermost (first-printed in the tree) is the leaf
# component where the error originated.
_REACT_TREE_ENTRY = re.compile(
    r"\bin\s+(?P<name>[A-Z][\w$]+)"
    r"(?:\s*\(at\s+(?P<file>[\w./\-]+):(?P<line>\d+)\))?",
)
# React quoted inner exception inside the trace (Error: x is not a
# function). React surfaces the original error class verbatim in
# the console wrapper, prefixed before the "The above error
# occurred" line. Reuses the standard JS exception shape with
# optional ``Uncaught`` / ``Unhandled`` / ``Warning:`` prefix.
_REACT_INNER_EXC = re.compile(
    r"^(?:Uncaught\s+|Unhandled\s+)?"
    r"(?P<exc>\w*(?:Error|Exception|Warning))\s*:\s*(?P<msg>.+?)$",
    re.MULTILINE,
)
# React-specific anchor vocabulary used to discriminate the typed
# lifecycle catch from other JS / TS code that happens to mention
# componentDidCatch (which is React-API-specific so seldom prose).
_REACT_VOCAB = re.compile(
    r"(?:\b(?:React|JSX|ReactDOM|useState|useEffect|hooks?"
    r"|component tree|boundary|StrictMode|ErrorBoundary)\b"
    r"|render\(\))",
    re.IGNORECASE,
)


def _parse_react_error_boundary(
    text: str,
) -> tuple[str, str, str | None, int | None] | None:
    """Return (exception, message, file, line) for a React error, or None.

    Detection requires EITHER:
    * The ``The above error occurred in the <Comp> component`` /
      ``React will try to recreate this component tree`` /
      ``Consider adding an error boundary`` wrapper, OR
    * A ``componentDidCatch`` / ``getDerivedStateFromError`` lifecycle
      method name with React-vocabulary anchor on the same text
      (so a generic JS string mentioning componentDidCatch in
      prose doesn't false-positive).

    The exception slot prefers a typed inner exception
    (``Error: x is not defined``) when present in the trace;
    otherwise composes ``ReactRenderError(<Component>)``.

    The file slot is the innermost component-tree entry's ``(at
    file:line)`` location, falling back to ``<Component>`` form
    when no file path is printed.

    Returns None when no React signature is present so the caller
    can fall through to the generic Node branch.
    """
    if not text:
        return None
    prelude = _REACT_BOUNDARY_PRELUDE.search(text)
    lifecycle = _REACT_LIFECYCLE.search(text)
    # Lifecycle-only detection requires a React-vocabulary anchor
    # for safety (componentDidCatch in prose without React context
    # shouldn't fire).
    if prelude is None and lifecycle is None:
        return None
    if prelude is None and lifecycle is not None:
        if _REACT_VOCAB.search(text) is None:
            return None

    # Determine exception + message.
    exc: str
    msg: str | None = None

    # Inner exception search (the typed Error / TypeError /
    # ReferenceError line printed BEFORE the wrapper).
    inner = _REACT_INNER_EXC.search(text)
    if inner is not None:
        exc = inner.group("exc").strip()
        msg = inner.group("msg").strip()
    else:
        # Fallback to ``ReactRenderError(<comp>)`` when prelude
        # carries a component name OR ``ReactBoundaryError`` for
        # the lifecycle-only branch.
        comp_name = None
        if prelude is not None:
            try:
                comp_name = prelude.group("comp")
            except IndexError:
                comp_name = None
        if comp_name:
            exc = f"ReactRenderError({comp_name})"
        elif lifecycle is not None:
            method = lifecycle.group(1)
            exc = f"ReactBoundaryError({method})"
        else:
            exc = "ReactBoundaryError"
        msg = ""

    # Find the innermost component-tree entry (the FIRST one
    # printed -- React lists the leaf-most component first).
    file_: str | None = None
    line_: int | None = None
    tree_match = _REACT_TREE_ENTRY.search(text)
    if tree_match is not None:
        file_grp = tree_match.group("file")
        line_grp = tree_match.group("line")
        if file_grp:
            file_ = file_grp.strip()
            try:
                line_ = int(line_grp) if line_grp else None
            except (ValueError, TypeError):
                line_ = None
        else:
            # Bare ``in App`` form -- emit <Name> as the file
            # anchor so dashboards still have a triage tag.
            name = tree_match.group("name")
            if name:
                file_ = f"<{name}>"

    # File slot fallback to the prelude's <Component> when no
    # tree entry was printed.
    if file_ is None and prelude is not None:
        try:
            comp = prelude.group("comp")
            if comp:
                file_ = f"<{comp}>"
        except IndexError:
            pass

    return exc, msg or "", file_, line_


def _react_likely_cause(
    exception: str | None, message: str | None, text: str | None = None
) -> str | None:
    """Return operator-friendly hints for common React errors."""
    exc = (exception or "").lower()
    msg = (message or "").lower()
    body = (text or "").lower()

    # Typed inner exceptions checked FIRST so they win over
    # generic React-lifecycle hints when an inner exception is
    # detected.
    if "typeerror" in exc:
        if "undefined" in msg or "null" in msg:
            return (
                "Property access on undefined / null state or props; "
                "check optional chaining and default values."
            )
        if "is not a function" in msg:
            return (
                "Calling a non-function value; check destructured handler "
                "props are correctly bound."
            )
        return "Type mismatch in render path; check prop types and state shape."
    if "referenceerror" in exc:
        return (
            "Variable not defined in render scope; check imports / hooks order."
        )
    if "rangeerror" in exc:
        if "maximum update depth" in msg or "depth exceeded" in body:
            return (
                "Infinite render loop; setState was called inside render or "
                "useEffect without proper deps."
            )
        return "Range / iteration error; check array bounds and recursion."
    if "syntaxerror" in exc:
        return "JSX syntax error; check unclosed tags and missing braces."

    # React-specific message hints from the text body.
    if "minified react error" in body:
        return (
            "Minified React error from production build; look up the error "
            "code at reactjs.org/docs/error-decoder.html."
        )
    if "maximum update depth" in body or "too many re-renders" in body:
        return (
            "Infinite render loop; setState inside render or useEffect "
            "without correct deps."
        )
    if "rendered fewer hooks than expected" in body or "rendered more hooks" in body:
        return "Hook rules violated; hooks called conditionally or in loops."
    if "invalid hook call" in body:
        return "Invalid hook call; hooks only callable inside function components."
    if "cannot update a component while rendering" in body:
        return (
            "setState called during render of another component; defer to "
            "useEffect."
        )
    if "objects are not valid as a react child" in body:
        return "Rendering a plain object directly; wrap it in a serialiser."
    if "each child in a list should have a unique" in body:
        return "Missing key prop on list items; add a stable unique key."
    if "react.children.only expected" in body:
        return "React.Children.only requires exactly one child element."
    if "context.consumer requires a function" in body:
        return "Context.Consumer expects a render-prop function as child."
    if "componentdidcatch" in exc or "componentdidcatch" in body:
        return (
            "Error boundary's componentDidCatch handler itself threw; "
            "check the boundary's recovery logic."
        )
    if "getderivedstatefromerror" in exc or "getderivedstatefromerror" in body:
        return (
            "Error boundary's getDerivedStateFromError handler threw; "
            "ensure it returns a plain state object."
        )
    if "boundary" in body and "consider adding" in body:
        return (
            "No error boundary caught the error; wrap the failing subtree "
            "in an <ErrorBoundary> component."
        )
    return "React component error; check the component tree and inspect props/state."


# AWS Lambda / boto3 client error shapes. The botocore library is
# the standard AWS Python SDK and prints errors using a distinctive
# message format that embeds both the AWS error code AND the API
# operation that failed:
#
#   botocore.exceptions.ClientError: An error occurred (NoSuchBucket)
#       when calling the HeadBucket operation: The specified bucket
#       does not exist
#
#   botocore.errorfactory.NoSuchKey: An error occurred (NoSuchKey)
#       when calling the GetObject operation: The specified key does
#       not exist.
#
# Additional boto3 / botocore exception classes that surface in Lambda
# logs and Python error captures:
#
#   * BotoCoreError                 -- generic botocore failure
#   * EndpointConnectionError       -- network can't reach AWS endpoint
#   * NoCredentialsError            -- missing AWS_ACCESS_KEY_ID env
#   * PartialCredentialsError       -- only one of access/secret set
#   * SSLError                      -- TLS handshake failure
#   * ReadTimeoutError              -- API call exceeded read timeout
#   * ConnectTimeoutError           -- TCP connect timed out
#   * ConnectionError               -- generic boto3 connection error
#   * ParamValidationError          -- SDK input validation failed
#   * ProfileNotFound               -- ~/.aws/credentials has no profile
#   * EventStreamError              -- Kinesis / Lambda streaming
#   * UnknownServiceError           -- typo in client(service_name)
#   * WaiterError                   -- waiter.wait() timeout
#
# The ClientError message format `An error occurred (CODE) when
# calling the OPERATION operation:` carries the most useful
# triage signal. We surface error_code + operation_name in the
# message slot so dashboards can group by AWS API + error pair
# without an LLM pass.
_BOTO_CLIENT_ERROR = re.compile(
    r"An error occurred\s*\((?P<code>[\w.]+)\)\s+when calling\s+"
    r"the\s+(?P<op>[\w.]+)\s+operation"
    r"(?:\s*:\s*(?P<detail>.*))?",
)
_BOTO_EXC_HEADER = re.compile(
    r"(?:^|\n)\s*(?:botocore\.(?:exceptions|errorfactory|client)\.|boto3\.exceptions\.)"
    r"(?P<exc>[A-Z][\w]+)"
    r"\s*:?\s*(?P<msg>[^\n]*)",
)


def _parse_boto_error(
    text: str,
) -> tuple[str, str, str | None, str | None] | None:
    """Return (exception, message, error_code, operation) for a boto3
    error, or None.

    Detection requires EITHER:
    * A ``botocore.exceptions.X``/``botocore.errorfactory.X``/
      ``boto3.exceptions.X`` exception header (the standard module
      paths for the boto3 SDK)
    * OR a ``botocore.errorfactory.ServiceSpecificError`` (where
      ServiceSpecificError is a dynamically generated exception
      class like ``NoSuchKey`` / ``BucketAlreadyExists``)
    * OR a ``An error occurred (CODE) when calling the OPERATION
      operation:`` pattern (the canonical ClientError message)

    The error_code and operation_name are extracted from the
    canonical message when present so dashboards can group by AWS
    API + error pair. Returns ``None`` when the text is not
    recognisably a boto3 error.
    """
    if not text:
        return None
    exc_match = _BOTO_EXC_HEADER.search(text)
    client_err = _BOTO_CLIENT_ERROR.search(text)
    # Require at least one of (exception header, client-error message)
    # to fire. We can't gate on JUST the client-error message because
    # a doc captured with that phrase isn't necessarily a real error
    # trace -- the boto exception header is the stronger signal.
    if exc_match is None and client_err is None:
        return None
    # When we have the boto exception header, use it as the exception
    # name. When we don't (the ClientError message landed without the
    # surrounding traceback), fall back to "ClientError" so dashboards
    # still get the AWS-specific tag.
    if exc_match is not None:
        exc = exc_match.group("exc")
        msg_raw = exc_match.group("msg").strip() or None
    else:
        exc = "ClientError"
        msg_raw = None
    # Prefer the canonical "An error occurred ..." message when it
    # carries detail; otherwise use whatever message followed the
    # exception class. We always surface the error code + operation
    # in a structured tail so dashboards can parse it without
    # re-running the regex.
    error_code: str | None = None
    operation: str | None = None
    detail: str | None = None
    if client_err is not None:
        error_code = client_err.group("code")
        operation = client_err.group("op")
        detail = client_err.group("detail")
        if detail is not None:
            detail = detail.strip() or None
    # Compose the final message. Format:
    #   "<detail> [code=ErrorCode op=OperationName]"
    # When detail is None, fall back to whatever followed the
    # exception class header.
    base = detail or msg_raw or ""
    parts: list[str] = []
    if base:
        parts.append(base)
    tags: list[str] = []
    if error_code:
        tags.append(f"code={error_code}")
    if operation:
        tags.append(f"op={operation}")
    if tags:
        parts.append("[" + " ".join(tags) + "]")
    msg = " ".join(parts).strip() or None
    return exc, msg or "", error_code, operation


def _boto_likely_cause(
    exception: str | None, error_code: str | None, message: str | None
) -> str | None:
    """Return operator-friendly hints for common boto3 / AWS errors.

    Inspects BOTH the exception class name AND the AWS error code
    captured from the canonical ClientError message -- the error
    code carries the AWS-specific signal (NoSuchBucket vs
    AccessDenied), while the class name carries the SDK-failure
    mode (NoCredentialsError vs ClientError).
    """
    exc = (exception or "").lower()
    code = (error_code or "").lower()
    msg = (message or "").lower()
    # SDK-level failures (no AWS round trip happened).
    if "nocredentials" in exc:
        return (
            "AWS credentials missing; set AWS_ACCESS_KEY_ID + "
            "AWS_SECRET_ACCESS_KEY or attach an instance profile."
        )
    if "partialcredentials" in exc:
        return "Only one of access_key / secret_key is set; set both or neither."
    if "profilenotfound" in exc:
        return "AWS profile not in ~/.aws/credentials; check AWS_PROFILE env or profile name."
    if "endpointconnection" in exc:
        return "Network can't reach the AWS endpoint; check VPC routing / DNS / endpoint URL."
    if "readtimeout" in exc:
        return "AWS API call exceeded read timeout; raise timeout or retry with backoff."
    if "connecttimeout" in exc:
        return "TCP connect to AWS endpoint timed out; check VPC NAT / endpoint reachability."
    if "ssl" in exc:
        return "TLS handshake with AWS endpoint failed; check system CA bundle and TLS version."
    if "paramvalidation" in exc:
        return "boto3 SDK input validation failed; check the operation's required params."
    if "unknownservice" in exc:
        return "Service name passed to boto3.client() is not recognised; check the spelling."
    if "waiter" in exc:
        return "boto3 waiter timed out before the resource reached the target state."
    if "eventstream" in exc:
        return "Kinesis / Lambda streaming response stream failed mid-stream."
    # AWS service-level error codes (a real AWS round trip happened
    # and the service returned a typed error).
    if "nosuchbucket" in code:
        return "S3 bucket does not exist; check the bucket name and region."
    if "nosuchkey" in code:
        return "S3 object key does not exist; check the key path."
    if "bucketalreadyexists" in code or "bucketalreadyownedbyyou" in code:
        return "S3 bucket name is already taken (globally unique namespace)."
    if "accessdenied" in code or "access denied" in msg:
        return "IAM policy denies this action; check the principal's role permissions."
    if "unauthorizedoperation" in code:
        return "EC2 / IAM denied the action; check resource-level policies."
    if "invalidaccesskeyid" in code:
        return "AWS access key id is invalid or deactivated; rotate or check the key."
    if "signaturedoesnotmatch" in code:
        return "Signature mismatch; check the secret key and system clock skew."
    if "throttling" in code or "throttling" in exc or "ratelimit" in code:
        return "AWS API rate limit hit; add exponential backoff or request a quota increase."
    if "limitexceeded" in code or "quotaexceeded" in code:
        return "AWS service quota exceeded; request a quota increase or reduce usage."
    if "resourcenotfound" in code:
        return "Referenced AWS resource doesn't exist; check the ARN / id."
    if "validationexception" in code:
        return "AWS service rejected the request shape; check API parameter constraints."
    if "tokenexpired" in code or "expiredtoken" in code:
        return "STS session token expired; refresh credentials."
    if "dependencyfailure" in code:
        return "Downstream AWS dependency failed; retry or check the dependent service health."
    if "internalfailure" in code or "internalerror" in code or "servicefailure" in code:
        return "AWS service-side internal error; retry with exponential backoff."
    if "serviceunavailable" in code:
        return "AWS service is temporarily unavailable; retry with backoff."
    return None


def parse_error_text(text: str) -> ErrorFields:
    if not text:
        return ErrorFields()
    framework: str | None = None
    file_ = None
    line_ = None
    exc = None
    msg = None
    # pytest first: it's a Python failure but the tail-line + assert
    # expression shape is unique enough that we extract test_name and
    # the bare ``assert foo == bar`` expression instead of letting the
    # surrounding Traceback branch take the trace.
    pytest_hit = _parse_pytest_failure(text)
    if pytest_hit and _PYTEST_ASSERT_EXPR.search(text):
        file_, line_, exc, msg = pytest_hit
        framework = "pytest"
        return ErrorFields(
            framework=framework,
            exception=exc,
            message=msg,
            likely_cause="Assertion failed; check the expression on the `>` line.",
            file=file_,
            line=line_,
        )
    # GraphQL execution error check runs BEFORE the python / node /
    # framework branches because a GraphQL response is JSON that can
    # contain a JS-style stack-trace inside extensions.exception.
    # stacktrace (Apollo Server includes the resolver stack tail).
    # Without this early check the Node branch's _JS_AT regex would
    # steal the response and tag it framework='node', losing the
    # GraphQL-specific signal (the error code, the resolver path,
    # the source-document location). Detection requires an
    # ``"errors": [`` array literal + at least one ``"message"``
    # field + one discriminator (locations / path / extensions /
    # GraphQL vocabulary) so a generic JSON error response (a REST
    # API failure that happens to nest an ``errors`` array) doesn't
    # false-positive.
    gql = _parse_graphql_error(text)
    if gql is not None:
        gql_exc, gql_msg, gql_path, gql_line = gql
        # Extract just the code part for the likely-cause lookup
        # (the exception slot may be ``GraphQLError`` when no code
        # was emitted; pass it through and the helper handles None).
        code_for_cause = gql_exc if gql_exc != "GraphQLError" else None
        return ErrorFields(
            framework="graphql",
            exception=gql_exc,
            message=gql_msg,
            likely_cause=_graphql_likely_cause(code_for_cause, gql_msg),
            file=gql_path,
            line=gql_line,
        )
    # Apollo Client / Apollo Server text-shape errors run AFTER the
    # GraphQL JSON branch (so a real GraphQL response with errors[]
    # wins) but BEFORE the python / node / framework branches so a
    # bare ``ApolloError: Network error: ...`` line doesn't get
    # mis-tagged as ``node``. The Apollo parser is conservative:
    # the bracketed [GraphQLError: ...] form and top-level
    # ``ApolloError:`` form fire unconditionally, but the typed
    # server-exception classes (AuthenticationError /
    # ValidationError / etc) ONLY fire when an Apollo-vocabulary
    # anchor sits in the same text -- without an anchor those
    # generic JS class names would steal innocent JS captures.
    apollo = _parse_apollo_error(text)
    if apollo is not None:
        apollo_exc, apollo_msg, apollo_file, apollo_line = apollo
        return ErrorFields(
            framework="apollo",
            exception=apollo_exc,
            message=apollo_msg,
            likely_cause=_apollo_likely_cause(apollo_exc, apollo_msg),
            file=apollo_file,
            line=apollo_line,
        )
    if _PY_TRACE.search(text):
        framework = "python"
        # boto3 / botocore detection runs FIRST within the Python
        # branch: when the Python traceback also carries a boto-
        # specific exception class (``botocore.exceptions.ClientError``,
        # ``botocore.errorfactory.NoSuchKey``, etc.) OR the canonical
        # ``An error occurred (CODE) when calling the OPERATION
        # operation:`` message, we return a framework='boto3' result
        # with the AWS error code + operation pulled out of the
        # message. Without this override the trace would tag as
        # generic ``python`` and dashboards would lose the AWS-specific
        # signal.
        boto = _parse_boto_error(text)
        if boto is not None:
            boto_exc, boto_msg, error_code, operation = boto
            # File / line from the innermost Python frame (the boto
            # exception itself is raised from inside botocore but the
            # caller's frame is more useful for triage).
            boto_file: str | None = None
            boto_line: int | None = None
            for m in _PY_FRAME.finditer(text):
                boto_file, boto_line = m.group(1), int(m.group(2))
            return ErrorFields(
                framework="boto3",
                exception=boto_exc,
                message=boto_msg,
                likely_cause=_boto_likely_cause(boto_exc, error_code, boto_msg),
                file=boto_file,
                line=boto_line,
            )
        for m in _PY_FRAME.finditer(text):
            file_, line_ = m.group(1), int(m.group(2))
        em = _PY_EXC.search(text)
        if em:
            exc, msg = em.group(1), em.group(2).strip()
        # SyntaxError-class enrichment: when CPython prints the caret
        # indicator (the ``^^^^^^^`` pointer to the bad token), surface
        # the offending source line and the caret column span in the
        # ``message`` field so dashboards can render a highlighted code
        # snippet without needing to re-parse the trace. The bare
        # SyntaxError ``msg`` (already populated above) is preserved as
        # a prefix; we append the source-line context and a "col N..M"
        # tail. The exception name is whatever CPython printed (one of
        # SyntaxError / IndentationError / TabError / Unicode*Error).
        syn = parse_syntax_caret(text)
        if syn is not None:
            syn_exc, source, col_start, col_end = syn
            exc = syn_exc
            base_msg = msg or ""
            # Trim leading whitespace from the source for display while
            # adjusting the caret span by the trimmed-prefix width.
            trim = len(source) - len(source.lstrip())
            display = source[trim:]
            disp_start = max(0, col_start - trim)
            disp_end = max(disp_start, col_end - trim)
            caret_tail = f" [at {display!r}, col {disp_start}..{disp_end}]"
            msg = (base_msg + caret_tail).strip()
    elif _NEST_PRELUDE.search(text):
        # NestJS framework log. Placed BEFORE the generic Node branch
        # because Nest runs on Node and the ``at Foo.bar (file.ts:N:M)``
        # frame shape is identical -- without this branch a Nest
        # exception would tag as ``node`` and dashboards would lose
        # the framework-specific signal (filters, pipes, guards,
        # exception classes). The discriminator is the ``[Nest]``
        # PID prefix combined with an ``ERROR [<context>]`` tag.
        nest_hit = _parse_nest_error(text)
        assert nest_hit is not None  # narrowed by the elif guard
        exc, msg, file_, line_ = nest_hit
        return ErrorFields(
            framework="nestjs",
            exception=exc,
            message=msg,
            likely_cause=_nest_likely_cause(exc, msg),
            file=file_,
            line=line_,
        )
    elif _parse_vue_error(text) is not None:
        # Vue.js component error. Placed BEFORE the generic Node
        # branch because Vue runs on the JS runtime and a Vue
        # capture often includes a JS stack tail (``at Component
        # (file.vue:N:M)``) that the bare _JS_AT would steal. The
        # discriminator is the literal ``[Vue warn]:`` prefix
        # combined with one of: ``Error in <lifecycle> hook``,
        # ``Error in v-on handler``, ``Error in render``, ``Error
        # in callback for watcher``, ``Unhandled error during
        # execution``, or ``Hydration <kind> mismatch``. We tag
        # ``framework='vue'`` so dashboards group all Vue runtime
        # errors together regardless of which lifecycle slot blew
        # up; the slot itself is preserved in the message so per-
        # lifecycle filtering still works.
        vue_hit = _parse_vue_error(text)
        assert vue_hit is not None  # narrowed by the elif guard
        exc, msg, file_, line_ = vue_hit
        return ErrorFields(
            framework="vue",
            exception=exc,
            message=msg,
            likely_cause=_vue_likely_cause(exc, msg),
            file=file_,
            line=line_,
        )
    elif _parse_react_error_boundary(text) is not None:
        # React error-boundary console dump. Placed BEFORE the
        # generic Node branch because React runs on the JS runtime
        # and a React error often includes a JS stack tail that
        # the bare _JS_AT would steal as framework='node', losing
        # the React-specific signal (component name, boundary
        # status, lifecycle method). Placed AFTER Vue because Vue
        # uses an even more specific ``[Vue warn]:`` prefix.
        #
        # Discriminator: one of ``The above error occurred in the
        # <Comp> component`` / ``Consider adding an error
        # boundary`` / ``React will try to recreate this component
        # tree`` wrappers, OR a typed lifecycle method
        # (``componentDidCatch`` / ``getDerivedStateFromError``)
        # combined with React-vocabulary anchor on the same text.
        react_hit = _parse_react_error_boundary(text)
        assert react_hit is not None  # narrowed by the elif guard
        exc, msg, file_, line_ = react_hit
        return ErrorFields(
            framework="react",
            exception=exc,
            message=msg,
            likely_cause=_react_likely_cause(exc, msg, text),
            file=file_,
            line=line_,
        )
    elif _JS_AT.search(text) or "at Object" in text or "node:" in text:
        framework = "node"
        m = _JS_AT.search(text)
        if m:
            file_, line_ = m.group(1), int(m.group(2))
        em = _JS_EXC.search(text)
        if em:
            exc, msg = em.group(1), em.group(2).strip()
    elif _DOTNET_FRAME_FILE.search(text) or (
        _DOTNET_FRAME_BARE.search(text) and _DOTNET_EXC.search(text)
    ):
        # .NET / CLR. We detect on the FRAME shape (``at NS.T.M() in
        # foo.cs:line 12`` OR bare ``at NS.T.M()`` paired with a
        # ``\w.\w+Exception`` exception line) so we don't steal JVM
        # traces that print frames as ``at com.x.Y.z(Y.java:12)``.
        framework = "dotnet"
        em = _DOTNET_EXC.search(text)
        if em:
            exc, msg = em.group(1), em.group(2).strip()
        # Walk every "in foo.cs:line N" frame; the LAST one wins,
        # mirroring how the Python branch finds the innermost frame.
        for m in _DOTNET_FRAME_FILE.finditer(text):
            file_, line_ = m.group("file").strip(), int(m.group("line"))
    elif _PHP_EXC.search(text):
        # PHP fatal-error. Placed BEFORE the JVM branch because the
        # PHP exception name is also a ``\w+Exception`` / ``\w+Error``
        # pattern that satisfies _JAVA_EXC. We tag framework='php',
        # keep any namespace prefix on the exception, and pull file +
        # line from the trailing ``thrown in PATH on line N`` (the
        # innermost frame) or from the inline ``in PATH:LINE`` on the
        # exception line itself when the multi-line stack tail is
        # absent.
        php_hit = _parse_php_fatal(text)
        assert php_hit is not None  # narrowed by the elif guard
        exc, msg, file_, line_ = php_hit
        return ErrorFields(
            framework="php",
            exception=exc,
            message=msg,
            likely_cause=_php_likely_cause(exc, msg),
            file=file_,
            line=line_,
        )
    elif _parse_swift_crash(text) is not None:
        # Swift fatalError() / Objective-C NSException. Placed AFTER
        # PHP because PHP's ``Fatal error: Uncaught X:`` prelude is
        # more specific than the bare Swift ``Fatal error: <msg>``
        # prelude (Swift fatals never carry the ``Uncaught`` keyword)
        # -- this ordering means a PHP fatal that happens to have a
        # Swift-looking message tail still tags as PHP. We tag
        # framework='swift' for BOTH Swift and Objective-C because
        # most Apple apps are mixed-language and dashboards group by
        # platform, not by source language.
        swift_hit = _parse_swift_crash(text)
        assert swift_hit is not None  # narrowed by the elif guard
        exc, msg, file_, line_ = swift_hit
        return ErrorFields(
            framework="swift",
            exception=exc,
            message=msg,
            likely_cause=_swift_likely_cause(exc, msg),
            file=file_,
            line=line_,
        )
    elif _parse_kotlin_coroutine(text) is not None:
        # Kotlin coroutine crash. Placed BEFORE the JVM branch because
        # Kotlin compiles to JVM bytecode and the frame shape is the
        # same -- without this branch a coroutine cancellation would
        # tag as ``jvm`` and dashboards would lose the coroutine-specific
        # signal (Job lifecycle, suspending functions, Dispatchers).
        # The discriminator is either a top-level
        # ``kotlinx.coroutines.X`` exception class OR a frame that
        # references ``kotlinx.coroutines.`` / ``invokeSuspend`` so a
        # pure-Java trace that happens to throw IllegalStateException
        # is NOT stolen from JVM.
        kt = _parse_kotlin_coroutine(text)
        assert kt is not None  # narrowed by the elif guard
        exc, msg, file_, line_ = kt
        return ErrorFields(
            framework="kotlin",
            exception=exc,
            message=msg,
            likely_cause=_kotlin_likely_cause(exc, msg),
            file=file_,
            line=line_,
        )
    elif _parse_spring_whitelabel(text) is not None:
        # Spring Boot WhiteLabel error page. Placed BEFORE the JVM
        # branch because the page often includes a JVM-style
        # stacktrace dump (when server.error.include-stacktrace is
        # enabled) and the bare JVM branch would tag the
        # ``com.example.app.NotFoundException`` line as ``jvm`` --
        # missing the Spring-specific HTTP status + reason phrase
        # signal that dashboards want for triage. The discriminator
        # is the literal ``Whitelabel Error Page`` heading combined
        # with the ``(type=..., status=NNN)`` summary line, both of
        # which only appear together on Spring's default fallback
        # page -- a regular JVM trace lacks both so it can't be
        # stolen.
        spring = _parse_spring_whitelabel(text)
        assert spring is not None  # narrowed by the elif guard
        spring_exc, spring_msg, spring_path, spring_status = spring
        return ErrorFields(
            framework="spring_boot_whitelabel",
            exception=spring_exc,
            message=spring_msg,
            likely_cause=_spring_whitelabel_likely_cause(
                spring_status, spring_exc, spring_msg
            ),
            file=spring_path,
            line=spring_status,
        )
    elif _JAVA_EXC.search(text):
        framework = "jvm"
        em = _JAVA_EXC.search(text)
        if em:
            exc, msg = em.group(1), em.group(2).strip()
    elif _GO_PANIC.search(text) or _GO_GOROUTINE.search(text):
        framework = "go"
        pm = _GO_PANIC.search(text)
        if pm:
            full = pm.group(1).strip()
            # Go panics typically look like:
            #   panic: runtime error: invalid memory address ...
            #   panic: assignment to entry in nil map
            # Treat the first colon-separated token as the exception type
            # when it reads like a Go runtime tag; otherwise the whole
            # line is the message and the exception is "panic".
            head, _, tail = full.partition(":")
            head = head.strip()
            tail = tail.strip()
            if head.lower() in {"runtime error", "fatal error"} and tail:
                exc, msg = head, tail
            elif head and tail and " " not in head:
                exc, msg = head, tail
            else:
                exc, msg = "panic", full
        for m in _GO_FRAME.finditer(text):
            file_, line_ = m.group(1), int(m.group(2))
    elif _parse_beam_crash(text) is not None:
        # Erlang / Elixir crash report. We branch on the literal ``**``
        # prelude with either a parenthesised Elixir exception or the
        # ``** exception error|throw|exit:`` Erlang form. The framework
        # tag (``elixir`` / ``erlang``) preserves which runtime we
        # parsed so dashboards can group separately. The BEAM branch
        # is intentionally placed AFTER the Go branch even though the
        # signatures do not conflict -- it keeps the systems-language
        # group (Go, Rust, BEAM) clustered together in the elif chain
        # for readability.
        beam = _parse_beam_crash(text)
        assert beam is not None  # narrowed by the elif guard
        framework, exc, file_, line_ = beam
        # For Elixir, the message is whatever followed the
        # parenthesised exception. For Erlang, the message is the
        # tail after ``** exception error: ...``. Recover both from
        # the same regex hits the helper already ran.
        elixir = _BEAM_EXC_ELIXIR.search(text)
        if elixir:
            msg = elixir.group("msg").strip() or None
        else:
            erlang = _BEAM_EXC_ERLANG.search(text)
            if erlang:
                msg = erlang.group("msg").strip() or None
        return ErrorFields(
            framework=framework,
            exception=exc,
            message=msg,
            likely_cause=_beam_likely_cause(exc, msg),
            file=file_,
            line=line_,
        )
    elif _RUBY_EXC.search(text) or _RUBY_FRAME.search(text):
        framework = "ruby"
        em = _RUBY_EXC.search(text)
        if em:
            exc = em.group(1)
        mm = _RUBY_MSG.search(text)
        if mm:
            msg = mm.group(1).strip()
        for m in _RUBY_FRAME.finditer(text):
            file_, line_ = m.group(1), int(m.group(2))
    elif _parse_rust_panic(text) is not None:
        # Rust panic: ``thread 'main' panicked at 'msg', src/foo.rs:5:8``
        # (older) or ``thread 'main' panicked at src/foo.rs:5:8:\nmsg``
        # (1.72+). We tag framework='rust' so dashboards can group Rust
        # alongside the other systems-language panics. The exception
        # name is always ``panic`` because Rust panics do not have a
        # typed exception class -- the message is the discriminator.
        framework = "rust"
        result = _parse_rust_panic(text)
        assert result is not None  # narrowed by the elif guard
        file_, line_, msg = result
        exc = "panic"
        return ErrorFields(
            framework=framework,
            exception=exc,
            message=msg,
            likely_cause=_rust_likely_cause(msg),
            file=file_,
            line=line_,
        )
    else:
        # Try the SQL error branch BEFORE HTTP so a postgres ``ERROR:
        # syntax error`` line is recognised as a SQL failure (not
        # caught by HTTP because no status code is present, but the
        # generic fallback would tag it ``unknown`` and miss the
        # dialect identifier).
        sql = _parse_sql_error(text)
        if sql is not None:
            dialect, exc_name, sql_msg, sql_line = sql
            return ErrorFields(
                framework="sql",
                exception=exc_name,
                message=sql_msg,
                likely_cause=_sql_likely_cause(dialect, sql_msg),
                file=None,
                line=sql_line,
            )
        # Try the HTTP status branch BEFORE the generic Error/Exception
        # regex so a line like "HTTP/1.1 500 Internal Server Error" is
        # recognised as an HTTP failure, not as a plain "InternalServerError"
        # exception name (it isn't one).
        http = parse_http_status(text)
        if http is not None:
            code, reason = http
            framework = "http"
            exc = f"HTTP {code}"
            msg = reason
            cause = _http_likely_cause(code, reason)
            return ErrorFields(
                framework=framework,
                exception=exc,
                message=msg,
                likely_cause=cause,
                file=None,
                line=None,
            )
        em = re.search(r"^([\w.]*(?:Error|Exception))\s*:\s*(.*)$", text, re.MULTILINE)
        if em:
            exc, msg = em.group(1), em.group(2).strip()
            framework = "unknown"
    return ErrorFields(
        framework=framework,
        exception=exc,
        message=msg,
        likely_cause=_likely_cause(framework or "", exc, msg),
        file=file_,
        line=line_,
    )


def enrich_error(existing: ErrorFields | None, ocr: OCRResult) -> ErrorFields:
    parsed = parse_error_text(ocr.text or "")
    if existing is None:
        return parsed
    merged = existing.model_copy()
    for f in ("framework", "exception", "message", "likely_cause", "file", "line"):
        if getattr(merged, f) in (None, "", 0):
            setattr(merged, f, getattr(parsed, f))
    return merged
