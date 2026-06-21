"""Erlang / Elixir crash report parsing for the error extractor.

Adds two new frameworks to the catalog -- ``elixir`` and ``erlang``
-- both keyed off the literal ``** `` prelude that the BEAM runtime
uses for top-of-process crash reports. Elixir prints
``** (ExceptionModule) message`` followed by frames of the shape
``(app vers) file.ex:LINE: Module.fn/arity``. Erlang prints
``** exception error|throw|exit: message`` followed by frames of
``in function mod:fn/arity`` (with optional ``(file.erl, line N)`` in
newer OTP). The new branch is wired into ``parse_error_text`` between
the Go and Ruby branches so neither steals the BEAM signal.

Tests cover:
* Elixir RuntimeError / MatchError / ArgumentError / KeyError shapes
  with file + line capture from the first frame.
* Erlang error / throw / exit kinds, including the older "no
  file/line" frame shape and the newer OTP file/line shape.
* ``parse_beam_crash`` helper returning ``None`` for non-BEAM text.
* Ordering: a BEAM crash that also contains a generic ``Error: msg``
  line tags as elixir/erlang, not as ``unknown``.
* ``likely_cause`` hints fire for the common high-frequency crashes
  (no function clause, badarg, badkey, undefined function, match
  error, generic throw).
"""
from __future__ import annotations

from shotclassify_extract import parse_beam_crash
from shotclassify_extract.error import parse_error_text

# ---- parse_beam_crash helper ------------------------------------------


def test_beam_crash_returns_none_for_plain_text():
    assert parse_beam_crash("") is None
    assert parse_beam_crash("nothing here") is None
    # A Python traceback must NOT be misread as BEAM.
    py = (
        "Traceback (most recent call last):\n"
        '  File "foo.py", line 1, in <module>\n'
        "ValueError: bad value\n"
    )
    assert parse_beam_crash(py) is None


def test_beam_crash_elixir_shape_with_frame():
    text = (
        "** (RuntimeError) something blew up\n"
        "    (my_app 0.1.0) lib/my_app/foo.ex:42: MyApp.Foo.bar/2\n"
    )
    got = parse_beam_crash(text)
    assert got is not None
    framework, exc, file_, line_ = got
    assert framework == "elixir"
    assert exc == "RuntimeError"
    assert file_ == "lib/my_app/foo.ex"
    assert line_ == 42


def test_beam_crash_erlang_error_shape_with_newer_otp_frame():
    text = (
        "** exception error: no function clause matching foo:bar(undefined)\n"
        "     in function  foo:bar/1 (foo.erl, line 12)\n"
        "     in call from foo:baz/0\n"
    )
    got = parse_beam_crash(text)
    assert got is not None
    framework, exc, file_, line_ = got
    assert framework == "erlang"
    assert exc == "error"
    assert file_ == "foo.erl"
    assert line_ == 12


def test_beam_crash_erlang_throw_without_file_or_line():
    """Older OTP frames omit file/line; the framework still tags."""
    text = (
        "** exception throw: oops\n"
        "     in function  foo:bar/1\n"
    )
    got = parse_beam_crash(text)
    assert got is not None
    framework, exc, file_, line_ = got
    assert framework == "erlang"
    assert exc == "throw"
    assert file_ is None
    assert line_ is None


def test_beam_crash_erlang_exit_kind():
    text = "** exception exit: shutdown\n"
    got = parse_beam_crash(text)
    assert got is not None
    framework, exc, _, _ = got
    assert framework == "erlang"
    assert exc == "exit"


# ---- parse_error_text integration -------------------------------------


def test_parse_error_elixir_runtime_error():
    text = (
        "** (RuntimeError) something blew up\n"
        "    (my_app 0.1.0) lib/my_app/foo.ex:42: MyApp.Foo.bar/2\n"
        "    (elixir 1.14.0) lib/elixir/agent.ex:99: anonymous fn/0\n"
    )
    out = parse_error_text(text)
    assert out.framework == "elixir"
    assert out.exception == "RuntimeError"
    assert out.message == "something blew up"
    assert out.file == "lib/my_app/foo.ex"
    assert out.line == 42
    assert out.likely_cause is not None


def test_parse_error_elixir_match_error_likely_cause():
    text = (
        "** (MatchError) no match of right hand side value: 1\n"
        "    (my_app 0.1.0) lib/my_app/foo.ex:7: MyApp.Foo.bar/0\n"
    )
    out = parse_error_text(text)
    assert out.framework == "elixir"
    assert out.exception == "MatchError"
    assert "pattern match failed" in (out.likely_cause or "").lower()


def test_parse_error_elixir_key_error_hint():
    text = (
        "** (KeyError) key :missing not found in: %{a: 1}\n"
        "    (my_app 0.1.0) lib/my_app/foo.ex:11: MyApp.Foo.bar/1\n"
    )
    out = parse_error_text(text)
    assert out.framework == "elixir"
    assert out.exception == "KeyError"
    assert "missing key" in (out.likely_cause or "").lower()


def test_parse_error_elixir_argument_error_hint():
    text = (
        "** (ArgumentError) argument error\n"
        "    (my_app 0.1.0) lib/my_app/foo.ex:3: MyApp.Foo.bar/1\n"
    )
    out = parse_error_text(text)
    assert out.framework == "elixir"
    assert out.exception == "ArgumentError"
    assert "argument" in (out.likely_cause or "").lower()


def test_parse_error_erlang_no_function_clause():
    text = (
        "** exception error: no function clause matching foo:bar(undefined)\n"
        "     in function  foo:bar/1\n"
    )
    out = parse_error_text(text)
    assert out.framework == "erlang"
    assert out.exception == "error"
    assert "no function clause" in (out.message or "").lower()
    assert "no function clause" in (out.likely_cause or "").lower()


def test_parse_error_erlang_badarg_hint():
    text = (
        "** exception error: bad argument\n"
        "     in function  erlang:length/1\n"
    )
    out = parse_error_text(text)
    assert out.framework == "erlang"
    assert "bad argument" in (out.likely_cause or "").lower()


def test_parse_error_erlang_undefined_function_hint():
    text = (
        "** exception error: undefined function foo:does_not_exist/0\n"
        "     in function  foo:caller/0\n"
    )
    out = parse_error_text(text)
    assert out.framework == "erlang"
    assert "function does not exist" in (out.likely_cause or "").lower()


# ---- ordering / non-conflict -----------------------------------------


def test_beam_branch_beats_generic_error_regex():
    """A BEAM crash that also contains a generic ``Error: msg`` line
    must tag elixir/erlang, not fall through to ``unknown``."""
    text = (
        "** (RuntimeError) generic problem\n"
        "    (my_app 0.1.0) lib/my_app/foo.ex:1: MyApp.Foo.bar/0\n"
        "\n"
        "Some other line that says Error: noise\n"
    )
    out = parse_error_text(text)
    assert out.framework == "elixir"
    assert out.exception == "RuntimeError"


def test_go_panic_not_misread_as_beam():
    """Go panics start with ``panic:`` (no ``** ``); BEAM branch must
    not steal them."""
    text = (
        "panic: runtime error: invalid memory address\n"
        "\n"
        "goroutine 1 [running]:\n"
        "main.run(...)\n"
        "        /app/main.go:42 +0x12\n"
    )
    out = parse_error_text(text)
    assert out.framework == "go"


def test_python_traceback_not_misread_as_beam():
    text = (
        "Traceback (most recent call last):\n"
        '  File "foo.py", line 1, in <module>\n'
        "    raise ValueError('bad')\n"
        "ValueError: bad\n"
    )
    out = parse_error_text(text)
    assert out.framework == "python"
    assert out.exception == "ValueError"


def test_beam_with_no_frame_still_tags_framework():
    """The very first line is enough to identify the runtime; frame
    extraction failing only drops file/line, not the tag."""
    text = "** (RuntimeError) oops\n"
    out = parse_error_text(text)
    assert out.framework == "elixir"
    assert out.exception == "RuntimeError"
    assert out.file is None
    assert out.line is None
