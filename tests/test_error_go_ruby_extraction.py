"""Go panic + Ruby/Rails stacktrace parser tests.

Adds Go and Ruby to the existing extractor catalog (which already
handled Python, Node, JVM). The framework field uses lowercase tags
(``go``, ``ruby``) consistent with the rest of the catalog. Likely
cause hints cover the panics and exceptions that show up most often
in production support tickets.
"""
from __future__ import annotations

from shotclassify_common import OCRResult
from shotclassify_extract.error import parse_error_text


def test_go_panic_nil_pointer():
    text = (
        "panic: runtime error: invalid memory address or nil pointer dereference\n"
        "[signal SIGSEGV: segmentation violation]\n"
        "\n"
        "goroutine 1 [running]:\n"
        "main.run(...)\n"
        "        /app/cmd/main.go:42 +0x12\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "go"
    assert fields.exception == "runtime error"
    assert "nil pointer" in (fields.message or "").lower()
    assert fields.file == "/app/cmd/main.go"
    assert fields.line == 42
    assert fields.likely_cause is not None
    assert "nil pointer" in fields.likely_cause.lower()


def test_go_panic_assignment_to_nil_map():
    text = (
        "panic: assignment to entry in nil map\n"
        "\n"
        "goroutine 7 [running]:\n"
        "main.assign(...)\n"
        "        /srv/svc/maps.go:88 +0x42\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "go"
    # No leading 'runtime error:' tag, so the whole line is the message
    # and the exception is "panic".
    assert fields.exception == "panic"
    assert "nil map" in (fields.message or "")
    assert fields.file == "/srv/svc/maps.go"
    assert fields.line == 88


def test_go_panic_index_out_of_range_likely_cause():
    text = (
        "panic: runtime error: index out of range [5] with length 3\n"
        "\n"
        "goroutine 1 [running]:\n"
        "main.main()\n"
        "        /a/b/c.go:10\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "go"
    assert fields.likely_cause is not None
    # We say "outside bounds" rather than the Go-internal "out of range"
    # so the hint reads like English.
    assert "outside bounds" in fields.likely_cause.lower()


def test_go_panic_concurrent_map_write():
    text = (
        "fatal error: concurrent map writes\n"
        "panic: concurrent map read and map write\n"
        "\n"
        "goroutine 4 [running]:\n"
        "main.write(...)\n"
        "        /srv/m.go:21 +0x10\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "go"
    assert "concurrent map" in (fields.likely_cause or "").lower()


def test_go_panic_send_on_closed_channel():
    text = (
        "panic: send on closed channel\n"
        "\n"
        "goroutine 2 [running]:\n"
        "main.producer(...)\n"
        "        /srv/p.go:5\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "go"
    assert (fields.likely_cause or "").startswith("Sender wrote")


def test_ruby_nomethoderror():
    text = (
        "/app/services/user.rb:42:in `name': "
        "undefined method `name' for nil:NilClass (NoMethodError)\n"
        "\tfrom /app/controllers/users_controller.rb:10:in `show'\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "ruby"
    assert fields.exception == "NoMethodError"
    assert "undefined method" in (fields.message or "")
    # _RUBY_FRAME.finditer leaves us on the LAST frame in the trace.
    assert fields.file == "/app/controllers/users_controller.rb"
    assert fields.line == 10
    assert fields.likely_cause is not None
    assert "respond" in fields.likely_cause.lower() or "nil" in fields.likely_cause.lower()


def test_ruby_argumenterror():
    text = (
        "/app/lib/calc.rb:7:in `add': wrong number of arguments "
        "(given 1, expected 2) (ArgumentError)\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "ruby"
    assert fields.exception == "ArgumentError"
    assert (fields.likely_cause or "").startswith("Method invoked")


def test_rails_activerecord_recordnotfound():
    text = (
        "/app/controllers/posts_controller.rb:12:in `show': "
        "Couldn't find Post with 'id'=999 (ActiveRecord::RecordNotFound)\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "ruby"
    assert fields.exception == "ActiveRecord::RecordNotFound"
    assert "ActiveRecord lookup" in (fields.likely_cause or "")


def test_python_still_wins_when_traceback_present():
    """Regression: the new Go / Ruby branches must come AFTER the
    Python / Node / JVM branches, so a Python traceback that happens
    to mention 'goroutine' in a string literal still classifies as
    Python."""
    text = (
        'Traceback (most recent call last):\n'
        '  File "/x.py", line 1, in <module>\n'
        '    raise ValueError("goroutine word in message")\n'
        'ValueError: goroutine word in message\n'
    )
    fields = parse_error_text(text)
    assert fields.framework == "python"
    assert fields.exception == "ValueError"


def _unused_ocr_helper() -> OCRResult:  # pragma: no cover
    # Kept so the OCRResult import is not flagged unused if the file is
    # ever extended with full-pipeline integration cases.
    return OCRResult(text="", language="und")
