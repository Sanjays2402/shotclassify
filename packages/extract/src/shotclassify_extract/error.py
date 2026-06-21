"""Error / stacktrace extractor."""
from __future__ import annotations

import re

from shotclassify_common import ErrorFields, OCRResult

_PY_TRACE = re.compile(r"Traceback \(most recent call last\):")
_PY_FRAME = re.compile(r'File "([^"]+)", line (\d+)')
_PY_EXC = re.compile(r"^([A-Z][A-Za-z0-9_]*Error|Exception)\s*:?\s*(.*)$", re.MULTILINE)
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
    if _PY_TRACE.search(text):
        framework = "python"
        for m in _PY_FRAME.finditer(text):
            file_, line_ = m.group(1), int(m.group(2))
        em = _PY_EXC.search(text)
        if em:
            exc, msg = em.group(1), em.group(2).strip()
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
