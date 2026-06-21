"""HTTP status code classifier for error captures.

The error extractor previously handled language stacktraces (Python /
Node / JVM / Go / Ruby) but ignored bare HTTP failures, which are
common in API screenshots, browser dev-tools captures, and CLI tool
output ("HTTP/1.1 502 Bad Gateway"). This branch catches them
BEFORE the generic Error/Exception fallback so:

* framework -> "http"
* exception -> "HTTP <code>"
* message   -> the reason phrase ("Bad Gateway" / "Not Found" / ...)
* likely_cause -> operator-friendly hint for the common codes
  (and a class label for the rest: "informational"/"success"/
  "redirect"/"client error"/"server error").

A real language stacktrace that happens to mention "HTTP 500" in a
string literal still classifies as the stacktrace's language (the
HTTP branch is the final fallback before the generic exception regex).
"""
from __future__ import annotations

import pytest
from shotclassify_extract import parse_http_status
from shotclassify_extract.error import parse_error_text


@pytest.mark.parametrize(
    "text,code,reason",
    [
        ("HTTP/1.1 500 Internal Server Error", 500, "Internal Server Error"),
        ("HTTP/2 404 Not Found", 404, "Not Found"),
        ("HTTP 401 Unauthorized", 401, "Unauthorized"),
        ("Response: 403 Forbidden", 403, "Forbidden"),
        ("status: 503", 503, None),
        ("status=429", 429, None),
        ("GET /api/users -> HTTP 502 Bad Gateway", 502, "Bad Gateway"),
    ],
)
def test_parse_http_status_recognises_prefixed_lines(text, code, reason):
    got = parse_http_status(text)
    assert got is not None
    got_code, got_reason = got
    assert got_code == code
    assert got_reason == reason


@pytest.mark.parametrize(
    "text,code,reason",
    [
        ("Server returned 404 Not Found for /missing", 404, "Not Found"),
        ("Got 429 Too Many Requests, backing off", 429, "Too Many Requests"),
        ("Upstream gave 502 Bad Gateway", 502, "Bad Gateway"),
        ("Returned 422 Unprocessable Entity", 422, "Unprocessable Entity"),
    ],
)
def test_parse_http_status_recognises_bare_code_reason_pairs(text, code, reason):
    got = parse_http_status(text)
    assert got is not None
    got_code, got_reason = got
    assert got_code == code
    assert got_reason == reason


def test_parse_http_status_no_match_returns_none():
    assert parse_http_status("nothing interesting") is None
    assert parse_http_status("") is None
    assert parse_http_status("500 dollars in change") is None  # no reason phrase, no HTTP prefix


def test_parse_http_status_first_prefixed_line_wins():
    """When both a prefixed and a bare line are present, the prefixed
    one wins because it is the more specific signal."""
    text = "HTTP/1.1 500 Internal Server Error\nlater: 404 Not Found\n"
    got = parse_http_status(text)
    assert got is not None
    assert got[0] == 500


# ---- error extractor integration ------------------------------------------


def test_error_extractor_tags_http_500():
    text = (
        "GET /api/orders/123\n"
        "HTTP/1.1 500 Internal Server Error\n"
        "Content-Type: application/json\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "http"
    assert fields.exception == "HTTP 500"
    assert fields.message == "Internal Server Error"
    assert fields.likely_cause is not None
    assert "crashed" in fields.likely_cause.lower() or "upstream" in fields.likely_cause.lower()


def test_error_extractor_tags_http_404_with_likely_cause():
    text = "GET /api/missing -> HTTP 404 Not Found"
    fields = parse_error_text(text)
    assert fields.framework == "http"
    assert fields.exception == "HTTP 404"
    assert fields.message == "Not Found"
    assert fields.likely_cause is not None
    assert "does not exist" in fields.likely_cause.lower()


def test_error_extractor_tags_http_429_rate_limited():
    text = "POST /api/v1/messages -> HTTP 429 Too Many Requests"
    fields = parse_error_text(text)
    assert fields.framework == "http"
    assert fields.exception == "HTTP 429"
    assert "rate-limited" in (fields.likely_cause or "").lower()


def test_error_extractor_http_class_fallback_for_uncommon_code():
    """A code not in the specific-hint table still gets a class label."""
    text = "HTTP/1.1 418 I'm a teapot"
    fields = parse_error_text(text)
    assert fields.framework == "http"
    assert fields.exception == "HTTP 418"
    assert fields.likely_cause is not None
    assert "client error" in fields.likely_cause.lower()


def test_python_traceback_still_wins_over_http_string_literal():
    """Regression: a Python stacktrace that prints `HTTP 500` inside a
    string literal must still classify as python, not as http."""
    text = (
        'Traceback (most recent call last):\n'
        '  File "/x.py", line 1, in <module>\n'
        '    raise RuntimeError("HTTP 500 came back")\n'
        'RuntimeError: HTTP 500 came back\n'
    )
    fields = parse_error_text(text)
    assert fields.framework == "python"
    assert fields.exception == "RuntimeError"


def test_node_stacktrace_still_wins_over_http_string_literal():
    """Same regression for Node: an error stacktrace beats a string
    that mentions HTTP 500."""
    text = (
        "TypeError: HTTP 500 happened\n"
        "    at Object.<anonymous> (/srv/app.js:10:7)\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "node"
    assert fields.exception == "TypeError"


def test_http_3xx_redirect_class():
    text = "HTTP/1.1 301 Moved Permanently"
    fields = parse_error_text(text)
    assert fields.framework == "http"
    assert fields.exception == "HTTP 301"
    # 301 not in the specific table -> class label.
    assert "redirect" in (fields.likely_cause or "").lower()


def test_http_2xx_success_still_recognised():
    """We still tag a 200 as http -- dashboards can decide whether to
    filter successes; the extractor's job is to identify the line."""
    text = "HTTP/1.1 200 OK"
    fields = parse_error_text(text)
    assert fields.framework == "http"
    assert fields.exception == "HTTP 200"
