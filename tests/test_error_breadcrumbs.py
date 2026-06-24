"""Sentry-style breadcrumb extraction tests.

ErrorFields.breadcrumbs captures the user-action / HTTP / log /
navigation trail that Sentry, Bugsnag, Rollbar, and Honeybadger
print above the stacktrace. Two recognised shapes:

* Table form: ``Breadcrumbs`` header line followed by
  ``CATEGORY  MESSAGE  TIME`` rows.
* JSON form: inline SDK payload ``{"category": "...", ...}``.
"""
from __future__ import annotations

from shotclassify_common import ErrorFields, OCRResult
from shotclassify_extract.error import enrich_error, extract_breadcrumbs

# ---- Empty / no-trail cases --------------------------------------


def test_empty_text():
    assert extract_breadcrumbs("") == []


def test_none_text():
    assert extract_breadcrumbs(None) == []  # type: ignore[arg-type]


def test_random_prose_no_trail():
    text = "Some random log output\nwith no breadcrumbs anywhere"
    assert extract_breadcrumbs(text) == []


def test_stacktrace_only_no_trail():
    text = (
        "TypeError: undefined is not a function\n"
        "    at Object.fn (/app/src/x.js:1:1)"
    )
    assert extract_breadcrumbs(text) == []


def test_header_only_no_rows():
    text = "Breadcrumbs\n\n\nNext section"
    assert extract_breadcrumbs(text) == []


# ---- Table-form full Sentry trail --------------------------------


def test_full_sentry_trail():
    text = (
        "Breadcrumbs\n"
        "navigation     /home -> /checkout                10:42:01\n"
        "http           GET /api/cart 200                 10:42:03\n"
        "ui.click       button#submit                     10:42:08\n"
        "console        warning  Form validation skipped  10:42:09\n"
        "exception      TypeError: undefined is not ...   10:42:09\n"
    )
    out = extract_breadcrumbs(text)
    assert len(out) == 5
    assert out[0] == {
        "category": "navigation",
        "message": "/home -> /checkout",
        "level": None,
        "timestamp": "10:42:01",
    }
    assert out[1]["category"] == "http"
    assert out[1]["message"] == "GET /api/cart 200"
    assert out[3]["category"] == "console"
    assert out[3]["level"] == "warning"
    assert out[3]["message"] == "Form validation skipped"
    assert out[4]["category"] == "exception"


def test_navigation_only():
    text = "Breadcrumbs\nnavigation  /home -> /about  10:00\n"
    out = extract_breadcrumbs(text)
    assert len(out) == 1
    assert out[0]["category"] == "navigation"
    assert out[0]["message"] == "/home -> /about"


def test_http_breadcrumb_with_status():
    text = (
        "Breadcrumbs\n"
        "http  POST /api/users 201  10:00\n"
        "http  GET /api/me 401  10:01\n"
    )
    out = extract_breadcrumbs(text)
    assert len(out) == 2
    assert out[0]["message"] == "POST /api/users 201"
    assert out[1]["message"] == "GET /api/me 401"


def test_ui_click_event():
    text = "Breadcrumbs\nui.click  button#login  09:00\n"
    out = extract_breadcrumbs(text)
    assert len(out) == 1
    assert out[0]["category"] == "ui.click"
    assert out[0]["message"] == "button#login"


def test_ui_input_event():
    text = "Breadcrumbs\nui.input  form input[name=email]  09:00\n"
    out = extract_breadcrumbs(text)
    assert len(out) == 1
    assert out[0]["category"] == "ui.input"


def test_console_with_level_warning():
    text = (
        "Breadcrumbs\n"
        "console  warning  Validation skipped  10:00\n"
    )
    out = extract_breadcrumbs(text)
    assert len(out) == 1
    assert out[0]["level"] == "warning"
    assert out[0]["message"] == "Validation skipped"


def test_console_with_level_error():
    text = (
        "Breadcrumbs\n"
        "console  error  Failed to load resource  10:00\n"
    )
    out = extract_breadcrumbs(text)
    assert out[0]["level"] == "error"
    assert out[0]["message"] == "Failed to load resource"


def test_console_with_level_debug():
    text = "Breadcrumbs\nconsole  debug  state updated  10:00\n"
    out = extract_breadcrumbs(text)
    assert out[0]["level"] == "debug"


def test_console_with_level_info():
    text = "Breadcrumbs\nconsole  info  user signed in  10:00\n"
    out = extract_breadcrumbs(text)
    assert out[0]["level"] == "info"


def test_console_warn_normalises_to_warning():
    text = "Breadcrumbs\nconsole  warn  Deprecated API used  10:00\n"
    out = extract_breadcrumbs(text)
    assert out[0]["level"] == "warning"  # warn -> warning


def test_exception_category():
    text = (
        "Breadcrumbs\nexception  TypeError: undefined is not a function  10:00\n"
    )
    out = extract_breadcrumbs(text)
    assert out[0]["category"] == "exception"


def test_query_breadcrumb():
    text = "Breadcrumbs\nquery  SELECT * FROM users WHERE id = ?  10:00\n"
    out = extract_breadcrumbs(text)
    assert out[0]["category"] == "query"


def test_redirect_breadcrumb():
    text = "Breadcrumbs\nredirect  /login -> /dashboard  10:00\n"
    out = extract_breadcrumbs(text)
    assert out[0]["category"] == "redirect"


def test_xhr_breadcrumb():
    text = "Breadcrumbs\nxhr  POST /graphql  10:00\n"
    out = extract_breadcrumbs(text)
    assert out[0]["category"] == "xhr"


def test_fetch_breadcrumb():
    text = "Breadcrumbs\nfetch  GET https://api.example.com/v1/me  10:00\n"
    out = extract_breadcrumbs(text)
    assert out[0]["category"] == "fetch"


def test_websocket_breadcrumb():
    text = "Breadcrumbs\nwebsocket  connected to wss://chat.example.com  10:00\n"
    out = extract_breadcrumbs(text)
    assert out[0]["category"] == "websocket"


def test_transaction_breadcrumb():
    text = "Breadcrumbs\ntransaction  Begin checkout flow  10:00\n"
    out = extract_breadcrumbs(text)
    assert out[0]["category"] == "transaction"


# ---- Timestamp shape variations -----------------------------------


def test_timestamp_with_seconds():
    text = "Breadcrumbs\nhttp  GET /api  10:42:01\n"
    out = extract_breadcrumbs(text)
    assert out[0]["timestamp"] == "10:42:01"


def test_timestamp_without_seconds():
    text = "Breadcrumbs\nhttp  GET /api  10:42\n"
    out = extract_breadcrumbs(text)
    assert out[0]["timestamp"] == "10:42"


def test_timestamp_iso_form():
    text = "Breadcrumbs\nhttp  GET /api  2024-01-15T10:42:01Z\n"
    out = extract_breadcrumbs(text)
    assert out[0]["timestamp"] == "2024-01-15T10:42:01Z"


def test_timestamp_iso_date_only():
    text = "Breadcrumbs\nhttp  GET /api  2024-01-15\n"
    out = extract_breadcrumbs(text)
    assert out[0]["timestamp"] == "2024-01-15"


def test_no_timestamp():
    text = "Breadcrumbs\nhttp  GET /api/users\n"
    out = extract_breadcrumbs(text)
    assert len(out) == 1
    assert out[0]["timestamp"] is None
    assert out[0]["message"] == "GET /api/users"


# ---- Header variations -------------------------------------------


def test_uppercase_header():
    text = "BREADCRUMBS\nnavigation  /home  10:00\n"
    out = extract_breadcrumbs(text)
    assert len(out) == 1


def test_breadcrumb_trail_header():
    text = "breadcrumb trail\nnavigation  /home  10:00\n"
    out = extract_breadcrumbs(text)
    assert len(out) == 1


def test_event_breadcrumbs_header():
    text = "Event breadcrumbs\nnavigation  /home  10:00\n"
    out = extract_breadcrumbs(text)
    assert len(out) == 1


def test_header_with_colon():
    text = "Breadcrumbs:\nnavigation  /home  10:00\n"
    out = extract_breadcrumbs(text)
    assert len(out) == 1


# ---- Safety / false-positive defences ----------------------------


def test_no_header_table_rejected():
    """Random table-shaped lines without 'Breadcrumbs' header don't fire."""
    text = (
        "Some data\n"
        "navigation  /home -> /checkout  10:00\n"
        "http  GET /api  10:01\n"
    )
    assert extract_breadcrumbs(text) == []


def test_random_multi_column_table_rejected():
    """A random multi-column table without breadcrumb header rejects."""
    text = (
        "Status    URL              Time\n"
        "OK        /home            10:00\n"
        "OK        /about           10:01\n"
    )
    assert extract_breadcrumbs(text) == []


def test_non_vocab_category_rejected():
    """A row whose category isn't in the vocab list rejects."""
    text = "Breadcrumbs\nfoo  bar  10:00\nbaz  qux  10:01\n"
    assert extract_breadcrumbs(text) == []


def test_single_space_separator_rejected():
    """Single-space separator rejects (we require 2+ for table form)."""
    text = "Breadcrumbs\nhttp GET /api 10:00\n"
    out = extract_breadcrumbs(text)
    # Single-space form does match because re cat\b matches; the body is
    # then "GET /api 10:00" -- but separator was one space. Our regex
    # requires 2+ spaces so this rejects.
    assert out == []


def test_blank_line_terminates_table():
    text = (
        "Breadcrumbs\n"
        "navigation  /home  10:00\n"
        "\n"
        "\n"
        "Some other section\n"
        "http  /should/not/fire  10:01\n"
    )
    out = extract_breadcrumbs(text)
    assert len(out) == 1
    assert out[0]["category"] == "navigation"


# ---- JSON form -----------------------------------------------------


def test_json_form_single_entry():
    text = (
        '{"category": "navigation", "message": "/home -> /checkout", '
        '"level": "info", "timestamp": "2024-01-15T10:42:01Z"}'
    )
    out = extract_breadcrumbs(text)
    assert len(out) == 1
    assert out[0]["category"] == "navigation"
    assert out[0]["message"] == "/home -> /checkout"
    assert out[0]["level"] == "info"
    assert out[0]["timestamp"] == "2024-01-15T10:42:01Z"


def test_json_form_multiple_entries():
    text = """
    {
      "breadcrumbs": [
        {"category": "navigation", "message": "/home", "level": "info", "timestamp": "10:00:00"},
        {"category": "http", "message": "GET /api/me 200", "level": "info", "timestamp": "10:00:01"},
        {"category": "exception", "message": "TypeError: x", "level": "error", "timestamp": "10:00:02"}
      ]
    }
    """
    out = extract_breadcrumbs(text)
    assert len(out) == 3
    assert out[0]["category"] == "navigation"
    assert out[1]["category"] == "http"
    assert out[2]["category"] == "exception"


def test_json_form_unescapes_message():
    text = '{"category": "console", "message": "expected \\"foo\\" but got bar"}'
    out = extract_breadcrumbs(text)
    assert len(out) == 1
    assert out[0]["message"] == 'expected "foo" but got bar'


def test_json_form_warn_normalises_to_warning():
    text = '{"category": "console", "message": "deprecated API", "level": "warn"}'
    out = extract_breadcrumbs(text)
    assert out[0]["level"] == "warning"


def test_json_form_missing_message_keeps_entry():
    text = '{"category": "navigation", "timestamp": "10:00"}'
    out = extract_breadcrumbs(text)
    assert len(out) == 1
    assert out[0]["category"] == "navigation"
    assert out[0]["message"] == ""


def test_json_form_non_vocab_category_rejected():
    text = '{"category": "foobar", "message": "anything"}'
    assert extract_breadcrumbs(text) == []


# ---- Mixed JSON + table forms ------------------------------------


def test_mixed_json_then_table():
    """A capture that has BOTH a JSON dump and a table -- both surface,
    de-duped on (category, message)."""
    text = (
        '{"category": "navigation", "message": "/home", "level": "info"}\n\n'
        "Breadcrumbs\n"
        "http  GET /api  10:00\n"
        "navigation  /home  10:00\n"  # Same as JSON -> dedup
    )
    out = extract_breadcrumbs(text)
    # JSON nav + table http = 2 entries (table nav dedups)
    assert len(out) == 2
    cats = [e["category"] for e in out]
    assert "navigation" in cats
    assert "http" in cats


# ---- Cap at 50 entries -------------------------------------------


def test_cap_at_50_entries():
    lines = ["Breadcrumbs"]
    for i in range(60):
        lines.append(f"http  GET /api/{i}  10:{i:02d}")
    text = "\n".join(lines)
    out = extract_breadcrumbs(text)
    assert len(out) == 50


# ---- enrich_error integration ------------------------------------


def test_enrich_error_writes_breadcrumbs_when_no_existing():
    text = (
        "Breadcrumbs\n"
        "navigation  /home  10:00\n"
        "http  GET /api  10:01\n"
        "exception  TypeError: x  10:02\n\n"
        "TypeError: undefined is not a function\n"
        '  File "/app/x.py", line 42, in foo'
    )
    out = enrich_error(None, OCRResult(text=text))
    assert len(out.breadcrumbs) == 3
    assert out.breadcrumbs[0]["category"] == "navigation"


def test_enrich_error_caller_breadcrumbs_preserved():
    """Caller-supplied breadcrumbs are NOT overridden by regex pass."""
    text = (
        "Breadcrumbs\n"
        "navigation  /from-ocr  10:00\n"
    )
    existing = ErrorFields(
        framework="python",
        exception="ValueError",
        breadcrumbs=[
            {
                "category": "log",
                "message": "from llm",
                "level": "info",
                "timestamp": "09:00",
            }
        ],
    )
    out = enrich_error(existing, OCRResult(text=text))
    # Caller's single LLM entry preserved verbatim, regex result discarded
    assert len(out.breadcrumbs) == 1
    assert out.breadcrumbs[0]["message"] == "from llm"


def test_enrich_error_empty_caller_breadcrumbs_backfilled():
    """When caller has empty breadcrumbs, regex result fills the slot."""
    text = (
        "Breadcrumbs\n"
        "navigation  /home  10:00\n"
    )
    existing = ErrorFields(framework="python", exception="ValueError", breadcrumbs=[])
    out = enrich_error(existing, OCRResult(text=text))
    assert len(out.breadcrumbs) == 1


def test_enrich_error_default_when_no_breadcrumbs():
    text = "TypeError: undefined is not a function"
    out = enrich_error(None, OCRResult(text=text))
    assert out.breadcrumbs == []


# ---- Real-world Sentry-shaped captures ---------------------------


def test_real_world_sentry_react_capture():
    """Realistic OCR capture of a Sentry event page for a React app."""
    text = """SENTRY  Issues  My Org  React App
Issue #ERR-1234: TypeError: Cannot read property 'name' of undefined
Last seen 5 min ago | 23 events | 12 users

Breadcrumbs
navigation     /dashboard -> /profile/42        10:42:01
http           GET /api/users/42 200            10:42:02
ui.click       a.profile-link                   10:42:05
ui.input       input[name=email]                10:42:07
http           POST /api/users/42 500           10:42:09
console        error  Save failed: Internal     10:42:09
exception      TypeError: Cannot read prop...   10:42:09

Stacktrace
  at ProfileForm.handleSubmit (ProfileForm.tsx:42:5)
  at onClick (Button.tsx:18:3)
"""
    out = extract_breadcrumbs(text)
    assert len(out) == 7
    assert [e["category"] for e in out] == [
        "navigation",
        "http",
        "ui.click",
        "ui.input",
        "http",
        "console",
        "exception",
    ]
    # console row carried the warning level
    console_entry = next(e for e in out if e["category"] == "console")
    assert console_entry["level"] == "error"
    assert console_entry["message"] == "Save failed: Internal"


def test_real_world_django_sentry_capture():
    text = """Sentry — DjangoApp
ValueError at /checkout
'foo' is not a valid choice.

Breadcrumbs
session       New session                       2024-01-15T10:42:01Z
auth          User signed in (uid=42)           2024-01-15T10:42:02Z
navigation    /products -> /cart                2024-01-15T10:42:05Z
ui.click      button#checkout                   2024-01-15T10:42:10Z
http          POST /checkout/ 400               2024-01-15T10:42:11Z
exception     ValueError at /checkout           2024-01-15T10:42:11Z

Stacktrace (most recent call last):
  File "/app/views.py", line 42, in checkout
    do_checkout(request)
"""
    out = extract_breadcrumbs(text)
    assert len(out) == 6
    assert out[0]["category"] == "session"
    assert out[1]["category"] == "auth"
    assert out[-1]["category"] == "exception"
    # Verify ISO timestamps came through verbatim
    assert all("2024-01-15T" in (e["timestamp"] or "") for e in out)


def test_real_world_bugsnag_style_capture():
    """Bugsnag prints a similar trail header."""
    text = (
        "BugSnag Error Report\n"
        "Exception: TypeError\n\n"
        "Event breadcrumbs\n"
        "navigation  /home  10:00\n"
        "ui.click    submit  10:01\n"
        "http        POST /api 500  10:02\n"
    )
    out = extract_breadcrumbs(text)
    assert len(out) == 3
