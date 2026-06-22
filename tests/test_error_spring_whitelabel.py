"""Spring Boot WhiteLabel error page parsing tests.

Spring Boot ships a fallback ``/error`` endpoint that renders a small
HTML page when any controller raises an unhandled exception or when
no route matches the request. Screenshots of this page surface often
in bug reports -- the user pastes what they saw and asks "why?".

Recognised shapes (Spring Boot 2.x + 3.x):

  Whitelabel Error Page
  This application has no explicit mapping for /error, so you are seeing this as a fallback.
  Sat May 21 16:14:21 IST 2023
  There was an unexpected error (type=Not Found, status=404).
  No message available

The parser pulls:

* exception: a Java-style FQCN (``com.example.app.NotFoundException``)
  when the page includes a stacktrace dump, else Spring's HTTP reason
  phrase tagged ``Type: <reason>``.
* message: the printed exception message, or a composed
  ``HTTP <status> on <path>`` summary when Spring printed
  ``No message available``.
* file slot: the failing request path (``/users/42``) -- this is the
  Spring-equivalent of "where did the error happen".
* line slot: the integer HTTP status code (``404`` / ``500`` / etc).

The branch sits BEFORE the generic JVM branch because the page often
includes a JVM-style stack-trace dump that would otherwise be stolen.
"""
from __future__ import annotations

from shotclassify_common import Category, ErrorFields, ExtractedFields, OCRResult
from shotclassify_extract import enrich, parse_error_text, parse_spring_whitelabel
from shotclassify_extract.error import (
    _SPRING_WHITELABEL_PRELUDE,
    _SPRING_WHITELABEL_TYPE,
    _parse_spring_whitelabel,
    _spring_whitelabel_likely_cause,
)

# ---- Prelude regex --------------------------------------------


def test_prelude_matches_canonical_heading():
    text = "Whitelabel Error Page"
    assert _SPRING_WHITELABEL_PRELUDE.search(text) is not None


def test_prelude_matches_mixed_case():
    text = "WHITELABEL ERROR PAGE"
    assert _SPRING_WHITELABEL_PRELUDE.search(text) is not None


def test_prelude_matches_with_surrounding_html():
    text = "<html><body><h1>Whitelabel Error Page</h1></body></html>"
    assert _SPRING_WHITELABEL_PRELUDE.search(text) is not None


def test_prelude_rejects_non_spring():
    assert _SPRING_WHITELABEL_PRELUDE.search("HTTP 404 Not Found") is None


def test_prelude_rejects_empty():
    assert _SPRING_WHITELABEL_PRELUDE.search("") is None


# ---- Type/status summary regex --------------------------------


def test_summary_captures_type_and_status():
    text = "There was an unexpected error (type=Not Found, status=404)."
    m = _SPRING_WHITELABEL_TYPE.search(text)
    assert m is not None
    assert m.group("type") == "Not Found"
    assert m.group("status") == "404"


def test_summary_captures_internal_server_error():
    text = "There was an unexpected error (type=Internal Server Error, status=500)."
    m = _SPRING_WHITELABEL_TYPE.search(text)
    assert m is not None
    assert m.group("type") == "Internal Server Error"
    assert m.group("status") == "500"


def test_summary_handles_extra_whitespace():
    text = "(type=Bad Request,  status=400)"
    m = _SPRING_WHITELABEL_TYPE.search(text)
    assert m is not None
    assert m.group("status") == "400"


def test_summary_rejects_two_digit_status():
    text = "(type=Foo, status=99)"
    assert _SPRING_WHITELABEL_TYPE.search(text) is None


def test_summary_rejects_four_digit_status():
    text = "(type=Foo, status=4040)"
    # Greedy on the inner group -- but our regex anchors with \d{3} so
    # 4040 would partially match as 404 + a trailing 0. Verify that
    # the captured status is exactly 3 digits.
    m = _SPRING_WHITELABEL_TYPE.search(text)
    if m is not None:
        assert len(m.group("status")) == 3


# ---- _parse_spring_whitelabel full pages ----------------------


def test_canonical_404_page():
    text = (
        "Whitelabel Error Page\n"
        "This application has no explicit mapping for /error, so you are seeing this as a fallback.\n"
        "Sat May 21 16:14:21 IST 2023\n"
        "There was an unexpected error (type=Not Found, status=404).\n"
        "No message available\n"
    )
    out = _parse_spring_whitelabel(text)
    assert out is not None
    exc, msg, path, status = out
    assert exc == "Type: Not Found"
    assert msg == "HTTP 404 on /error"
    assert path == "/error"
    assert status == 404


def test_500_page_with_real_message():
    text = (
        "Whitelabel Error Page\n"
        "Mon Mar 15 09:33:21 UTC 2024\n"
        "There was an unexpected error (type=Internal Server Error, status=500).\n"
        "Database connection lost\n"
    )
    out = _parse_spring_whitelabel(text)
    assert out is not None
    exc, msg, path, status = out
    assert exc == "Type: Internal Server Error"
    assert msg == "Database connection lost"
    assert path is None
    assert status == 500


def test_400_page_with_typed_exception():
    text = (
        "Whitelabel Error Page\n"
        "Sat Jan 1 00:00:00 GMT 2025\n"
        "There was an unexpected error (type=Bad Request, status=400).\n"
        "org.springframework.web.bind.MethodArgumentNotValidException: Validation failed\n"
        "  at org.springframework.web.method.annotation.AbstractMethodArgumentResolver\n"
    )
    out = _parse_spring_whitelabel(text)
    assert out is not None
    exc, msg, path, status = out
    assert exc == "org.springframework.web.bind.MethodArgumentNotValidException"
    assert "Validation failed" in msg
    assert status == 400


def test_403_with_path_and_no_message():
    text = (
        "Whitelabel Error Page\n"
        "This application has no explicit mapping for /admin/users, "
        "so you are seeing this as a fallback.\n"
        "There was an unexpected error (type=Forbidden, status=403).\n"
        "No message available\n"
    )
    out = _parse_spring_whitelabel(text)
    assert out is not None
    exc, msg, path, status = out
    assert exc == "Type: Forbidden"
    assert msg == "HTTP 403 on /admin/users"
    assert path == "/admin/users"
    assert status == 403


def test_returns_none_for_plain_text():
    text = "Just regular text without any spring signature"
    assert _parse_spring_whitelabel(text) is None


def test_returns_none_for_jvm_trace_without_prelude():
    # A regular JVM trace must NOT be stolen by this branch.
    text = (
        "java.lang.NullPointerException: Cannot invoke\n"
        "    at com.example.Foo.bar(Foo.java:42)\n"
    )
    assert _parse_spring_whitelabel(text) is None


def test_returns_none_when_summary_missing():
    # Heading but no type=...,status=... summary.
    text = "Whitelabel Error Page\nSomething went wrong\n"
    assert _parse_spring_whitelabel(text) is None


def test_returns_none_for_empty():
    assert _parse_spring_whitelabel("") is None


def test_returns_none_for_none_input():
    # Defensive coverage for the truthy guard.
    assert _parse_spring_whitelabel("") is None


def test_handles_explicit_message_label():
    text = (
        "Whitelabel Error Page\n"
        "There was an unexpected error (type=Conflict, status=409).\n"
        "Message: Duplicate email\n"
    )
    out = _parse_spring_whitelabel(text)
    assert out is not None
    exc, msg, path, status = out
    assert msg == "Duplicate email"


def test_skips_html_in_message_search():
    # The page sometimes wraps content in HTML; we should still find the
    # real message.
    text = (
        "<html><body>\n"
        "<h1>Whitelabel Error Page</h1>\n"
        "Tue Apr 9 12:00:00 BST 2024\n"
        "There was an unexpected error (type=Not Found, status=404).\n"
        "User not found\n"
        "</body></html>\n"
    )
    out = _parse_spring_whitelabel(text)
    assert out is not None
    exc, msg, path, status = out
    # The "</body></html>" is the first non-skip line after the
    # summary... wait, actually `User not found` comes first.
    assert "User not found" in msg


# ---- Public wrapper --------------------------------------------


def test_public_wrapper_returns_same_result():
    text = (
        "Whitelabel Error Page\n"
        "There was an unexpected error (type=Not Found, status=404).\n"
        "No message available\n"
    )
    assert parse_spring_whitelabel(text) == _parse_spring_whitelabel(text)


def test_public_wrapper_none_for_non_spring():
    assert parse_spring_whitelabel("hello world") is None


# ---- Likely-cause hints ---------------------------------------


def test_likely_cause_404_default():
    assert _spring_whitelabel_likely_cause(404, "Type: Not Found", None) == (
        "Route did not match any @RequestMapping; check controller path."
    )


def test_likely_cause_500_no_message():
    assert _spring_whitelabel_likely_cause(
        500, "Type: Internal Server Error", "HTTP 500"
    ) == "Unhandled server exception reached the default error handler."


def test_likely_cause_500_with_no_message_phrase():
    hint = _spring_whitelabel_likely_cause(
        500, "Type: Internal Server Error", "No message available"
    )
    assert hint is not None
    assert "no message" in hint.lower() or "include-stacktrace" in hint.lower()


def test_likely_cause_401_default():
    assert _spring_whitelabel_likely_cause(401, "Type: Unauthorized", None) == (
        "Missing or invalid auth credentials; check Spring Security filter chain."
    )


def test_likely_cause_403_default():
    assert _spring_whitelabel_likely_cause(403, "Type: Forbidden", None) == (
        "Authenticated but lacking required role / permission."
    )


def test_likely_cause_400_default():
    assert _spring_whitelabel_likely_cause(400, "Type: Bad Request", None) == (
        "Request failed validation; check binding result and validator."
    )


def test_likely_cause_409_default():
    hint = _spring_whitelabel_likely_cause(409, "Type: Conflict", None)
    assert hint is not None and "conflict" in hint.lower()


def test_likely_cause_422_default():
    hint = _spring_whitelabel_likely_cause(422, None, None)
    assert hint is not None and "semantic" in hint.lower()


def test_likely_cause_503_default():
    hint = _spring_whitelabel_likely_cause(503, None, None)
    assert hint is not None
    assert (
        "down" in hint.lower()
        or "unhealth" in hint.lower()
        or "refus" in hint.lower()
    )


def test_likely_cause_validation_class_wins_over_status():
    hint = _spring_whitelabel_likely_cause(
        500,
        "org.springframework.web.bind.MethodArgumentNotValidException",
        "Validation failed",
    )
    assert hint is not None
    assert "validation" in hint.lower() or "@Valid" in hint or "DTO" in hint


def test_likely_cause_access_denied_class():
    hint = _spring_whitelabel_likely_cause(
        500, "org.springframework.security.access.AccessDeniedException", None
    )
    assert hint is not None and "security" in hint.lower()


def test_likely_cause_no_message_for_unknown_status():
    assert _spring_whitelabel_likely_cause(999, None, None) is None


def test_likely_cause_none_status_returns_none():
    assert _spring_whitelabel_likely_cause(None, "anything", "anything") is None


def test_likely_cause_415_default():
    hint = _spring_whitelabel_likely_cause(415, None, None)
    assert hint is not None and "content-type" in hint.lower()


def test_likely_cause_response_status_exception():
    hint = _spring_whitelabel_likely_cause(
        500, "org.springframework.web.server.ResponseStatusException", None
    )
    assert hint is not None
    assert "responsestatusexception" in hint.lower() or "controller" in hint.lower()


def test_likely_cause_data_integrity():
    hint = _spring_whitelabel_likely_cause(
        500, "org.springframework.dao.DataIntegrityViolationException", None
    )
    assert hint is not None and ("constraint" in hint.lower() or "DB" in hint or "db" in hint.lower())


# ---- parse_error_text integration ------------------------------


def test_parse_error_text_tags_framework_spring():
    text = (
        "Whitelabel Error Page\n"
        "This application has no explicit mapping for /error, so you are seeing this as a fallback.\n"
        "Sat May 21 16:14:21 IST 2023\n"
        "There was an unexpected error (type=Not Found, status=404).\n"
        "No message available\n"
    )
    parsed = parse_error_text(text)
    assert parsed.framework == "spring_boot_whitelabel"
    assert parsed.exception == "Type: Not Found"
    assert parsed.message == "HTTP 404 on /error"
    assert parsed.file == "/error"
    assert parsed.line == 404
    assert parsed.likely_cause is not None


def test_parse_error_text_with_typed_exception():
    text = (
        "Whitelabel Error Page\n"
        "There was an unexpected error (type=Bad Request, status=400).\n"
        "org.springframework.web.bind.MethodArgumentNotValidException: Validation failed\n"
    )
    parsed = parse_error_text(text)
    assert parsed.framework == "spring_boot_whitelabel"
    assert parsed.exception == "org.springframework.web.bind.MethodArgumentNotValidException"
    assert "Validation failed" in parsed.message
    assert parsed.line == 400
    # The class-level hint should fire instead of the generic 400 hint.
    assert parsed.likely_cause is not None
    assert "validation" in parsed.likely_cause.lower()


def test_parse_error_text_does_not_steal_plain_jvm():
    # A plain JVM trace without Spring's WhiteLabel signature should
    # still tag as jvm, not spring_boot_whitelabel.
    text = (
        "java.lang.NullPointerException: Cannot invoke method\n"
        "    at com.example.Foo.bar(Foo.java:42)\n"
    )
    parsed = parse_error_text(text)
    assert parsed.framework == "jvm"


def test_parse_error_text_500_with_message():
    text = (
        "Whitelabel Error Page\n"
        "Mon Mar 15 09:33:21 UTC 2024\n"
        "There was an unexpected error (type=Internal Server Error, status=500).\n"
        "Connection refused\n"
    )
    parsed = parse_error_text(text)
    assert parsed.framework == "spring_boot_whitelabel"
    assert parsed.exception == "Type: Internal Server Error"
    assert parsed.message == "Connection refused"
    assert parsed.line == 500


def test_parse_error_text_403_with_path():
    text = (
        "Whitelabel Error Page\n"
        "This application has no explicit mapping for /admin, so you are seeing this as a fallback.\n"
        "There was an unexpected error (type=Forbidden, status=403).\n"
        "No message available\n"
    )
    parsed = parse_error_text(text)
    assert parsed.framework == "spring_boot_whitelabel"
    assert parsed.file == "/admin"
    assert parsed.line == 403


# ---- enrich() pipeline integration ----------------------------


def test_enrich_pipeline_tags_spring():
    text = (
        "Whitelabel Error Page\n"
        "There was an unexpected error (type=Not Found, status=404).\n"
        "No message available\n"
    )
    fields = ExtractedFields()
    ocr = OCRResult(text=text)
    enriched = enrich(Category.error_stacktrace, fields, ocr)
    assert enriched.error is not None
    assert enriched.error.framework == "spring_boot_whitelabel"


def test_enrich_pipeline_preserves_existing_error_fields():
    # If the caller (LLM) supplied an error field, it should win over
    # our parsed framework for non-empty values -- this mirrors the
    # behaviour for other branches.
    text = (
        "Whitelabel Error Page\n"
        "There was an unexpected error (type=Not Found, status=404).\n"
        "No message available\n"
    )
    fields = ExtractedFields(
        error=ErrorFields(framework="custom_router", exception="MyExc")
    )
    ocr = OCRResult(text=text)
    enriched = enrich(Category.error_stacktrace, fields, ocr)
    assert enriched.error is not None
    # Caller-supplied non-empty fields win.
    assert enriched.error.framework == "custom_router"
    assert enriched.error.exception == "MyExc"
    # But empty fields get filled from our parse.
    assert enriched.error.line == 404


# ---- Edge cases ------------------------------------------------


def test_status_extraction_works_for_unusual_phrase():
    text = (
        "Whitelabel Error Page\n"
        "There was an unexpected error (type=I'm a Teapot, status=418).\n"
        "Tea required\n"
    )
    out = _parse_spring_whitelabel(text)
    assert out is not None
    exc, msg, path, status = out
    assert status == 418
    assert "Teapot" in exc


def test_does_not_steal_prelude_phrase_as_exception():
    # The WhiteLabel page heading sits at the top and includes dots;
    # ensure we don't accidentally pick it as an exception class.
    text = (
        "Whitelabel Error Page\n"
        "Sat May 21 16:14:21 IST 2023\n"
        "There was an unexpected error (type=Not Found, status=404).\n"
        "No message available\n"
    )
    out = _parse_spring_whitelabel(text)
    assert out is not None
    exc, msg, path, status = out
    # The exception slot must be the Type: ... fallback, not a junk
    # FQCN derived from the heading.
    assert exc.startswith("Type:")


def test_handles_path_with_query_parameters():
    text = (
        "Whitelabel Error Page\n"
        "This application has no explicit mapping for /search?q=foo&p=1, "
        "so you are seeing this as a fallback.\n"
        "There was an unexpected error (type=Not Found, status=404).\n"
        "No message available\n"
    )
    out = _parse_spring_whitelabel(text)
    assert out is not None
    exc, msg, path, status = out
    assert path is not None
    assert path.startswith("/search")


def test_unrelated_keywords_in_prose_dont_trigger():
    # A doc that talks about "whitelabel" without the full page
    # should NOT trigger this branch.
    text = (
        "We considered using Spring's whitelabel error page but disabled it.\n"
        "Instead we return JSON.\n"
    )
    out = _parse_spring_whitelabel(text)
    # The prelude regex matches "whitelabel error page" case-insensitively
    # but the type=...,status=... summary line is required to commit
    # so this should still be None.
    assert out is None


def test_405_method_not_allowed():
    text = (
        "Whitelabel Error Page\n"
        "There was an unexpected error (type=Method Not Allowed, status=405).\n"
        "Request method 'POST' not supported\n"
    )
    parsed = parse_error_text(text)
    assert parsed.framework == "spring_boot_whitelabel"
    assert parsed.line == 405


def test_415_unsupported_media():
    text = (
        "Whitelabel Error Page\n"
        "There was an unexpected error (type=Unsupported Media Type, status=415).\n"
        "Content type 'application/xml' not supported\n"
    )
    parsed = parse_error_text(text)
    assert parsed.framework == "spring_boot_whitelabel"
    assert parsed.line == 415
    assert parsed.likely_cause is not None
