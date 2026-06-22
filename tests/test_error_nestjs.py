"""NestJS exception filter parsing tests.

NestJS prints exceptions through its built-in ExceptionsHandler / custom
filter classes (HttpExceptionFilter, RpcExceptionFilter,
WsExceptionFilter, custom *Filter / *Pipe / *Guard / *Exception
suffixed names). The framework log line carries a distinctive
``[Nest]`` PID prefix and an ``ERROR [<context>]`` tag.

Recognised shapes:
* ``[Nest] 12345  - 12/22/2026, 10:23:45 AM   ERROR [ExceptionsHandler] message``
* Followed by a JS-style stacktrace with ``at Foo.bar (file.ts:N:M)`` frames
* Typed exception classes: HttpException, NotFoundException,
  UnauthorizedException, ForbiddenException, BadRequestException,
  ConflictException, ValidationException, etc.

The branch sits BEFORE the generic Node branch in parse_error_text
because Nest runs on Node and the stacktrace frame shape is
identical; without this discriminator a Nest exception would tag as
``node`` and dashboards would lose the framework-specific signal.
"""
from __future__ import annotations

from shotclassify_common import Category, ErrorFields, ExtractedFields, OCRResult
from shotclassify_extract import enrich, parse_error_text
from shotclassify_extract.error import (
    _NEST_PRELUDE,
    _nest_likely_cause,
    _parse_nest_error,
)

# ---- Prelude regex --------------------------------------------


def test_nest_prelude_matches_exceptions_handler():
    text = "[Nest] 12345 - 12/22/2026, 10:23:45 AM   ERROR [ExceptionsHandler] User not found"
    m = _NEST_PRELUDE.search(text)
    assert m is not None
    assert m.group("context") == "ExceptionsHandler"
    assert "User not found" in m.group("msg")


def test_nest_prelude_matches_http_exception_filter():
    text = "[Nest] 100 - 01/15/2027, 11:22:33 AM   ERROR [HttpExceptionFilter] Bad request"
    m = _NEST_PRELUDE.search(text)
    assert m is not None
    assert m.group("context") == "HttpExceptionFilter"


def test_nest_prelude_matches_validation_pipe():
    text = "[Nest] 9876 - 03/04/2027, 9:00 AM   ERROR [ValidationPipe] Validation failed"
    m = _NEST_PRELUDE.search(text)
    assert m is not None
    assert m.group("context") == "ValidationPipe"


def test_nest_prelude_matches_auth_guard():
    text = "[Nest] 1 - 12:00 AM   ERROR [AuthGuard] Forbidden"
    m = _NEST_PRELUDE.search(text)
    assert m is not None
    assert m.group("context") == "AuthGuard"


def test_nest_prelude_rejects_non_nest_log():
    # A regular Node app log without [Nest] prefix.
    text = "ERROR [Application] Something failed"
    assert _NEST_PRELUDE.search(text) is None


def test_nest_prelude_rejects_python_log():
    text = "ERROR:root:Something failed"
    assert _NEST_PRELUDE.search(text) is None


def test_nest_prelude_works_with_minimal_formatting():
    # No timestamp / minimal spacing should still match.
    text = "[Nest] ERROR [ExceptionsHandler] minimal"
    m = _NEST_PRELUDE.search(text)
    assert m is not None


# ---- _parse_nest_error -----------------------------------------


def test_parse_nest_simple_message():
    text = "[Nest] 12345 - 12/22/2026, 10:23:45 AM   ERROR [ExceptionsHandler] User not found"
    out = _parse_nest_error(text)
    assert out is not None
    exc, msg, file_, line_ = out
    assert exc == "ExceptionsHandler"
    assert "User not found" in msg


def test_parse_nest_with_typed_exception():
    text = (
        "[Nest] 12345 - 12/22/2026   ERROR [ExceptionsHandler] User not found\n"
        "NotFoundException: User not found\n"
        "    at UserController.findOne (/app/src/users/users.controller.ts:42:11)\n"
    )
    out = _parse_nest_error(text)
    assert out is not None
    exc, msg, file_, line_ = out
    # Typed exception class wins over the bare ExceptionsHandler tag.
    assert exc == "NotFoundException"
    assert "User not found" in msg
    assert file_ == "/app/src/users/users.controller.ts"
    assert line_ == 42


def test_parse_nest_http_exception():
    text = (
        "[Nest] 100 - 01/15/2027   ERROR [HttpExceptionFilter] Unauthorized\n"
        "UnauthorizedException: Unauthorized\n"
        "    at JwtAuthGuard.canActivate (/app/src/auth/jwt.guard.ts:25:11)\n"
    )
    out = _parse_nest_error(text)
    assert out is not None
    exc, msg, file_, line_ = out
    assert exc == "UnauthorizedException"
    assert file_ is not None
    assert "jwt.guard.ts" in file_
    assert line_ == 25


def test_parse_nest_forbidden_exception():
    text = (
        "[Nest] 1 - ERROR [RolesGuard] Forbidden resource\n"
        "ForbiddenException: Forbidden resource\n"
    )
    out = _parse_nest_error(text)
    assert out is not None
    exc, msg, _, _ = out
    assert exc == "ForbiddenException"
    assert "Forbidden" in msg


def test_parse_nest_bad_request_exception():
    text = (
        "[Nest] 1 ERROR [ValidationPipe] Bad Request Exception\n"
        "BadRequestException: Validation failed (numeric string is expected)\n"
    )
    out = _parse_nest_error(text)
    assert out is not None
    exc, msg, _, _ = out
    assert exc == "BadRequestException"


def test_parse_nest_validation_exception():
    text = (
        "[Nest] 1 ERROR [ValidationPipe] Bad payload\n"
        "ValidationException: name must be a string\n"
    )
    out = _parse_nest_error(text)
    assert out is not None
    exc, _, _, _ = out
    assert exc == "ValidationException"


def test_parse_nest_internal_server_error():
    text = (
        "[Nest] 1 ERROR [ExceptionsHandler] Internal server error\n"
        "InternalServerErrorException: Database connection failed\n"
    )
    out = _parse_nest_error(text)
    assert out is not None
    exc, msg, _, _ = out
    assert exc == "InternalServerErrorException"
    assert "Database connection failed" in msg


def test_parse_nest_rpc_exception():
    text = (
        "[Nest] 1 ERROR [RpcExceptionFilter] RPC error\n"
        "RpcException: Microservice unavailable\n"
    )
    out = _parse_nest_error(text)
    assert out is not None
    exc, _, _, _ = out
    assert exc == "RpcException"


def test_parse_nest_ws_exception():
    text = (
        "[Nest] 1 ERROR [WsExceptionFilter] WebSocket error\n"
        "WsException: Connection rejected\n"
    )
    out = _parse_nest_error(text)
    assert out is not None
    exc, _, _, _ = out
    assert exc == "WsException"


def test_parse_nest_without_typed_exc_uses_context():
    # When no typed *Exception class is printed, we use the
    # bracketed context name as the exception slot.
    text = "[Nest] 100 ERROR [HttpExceptionFilter] some message"
    out = _parse_nest_error(text)
    assert out is not None
    exc, msg, _, _ = out
    assert exc == "HttpExceptionFilter"
    assert "some message" in msg


def test_parse_nest_returns_none_without_prelude():
    text = "Some random error log"
    assert _parse_nest_error(text) is None


def test_parse_nest_returns_none_for_empty():
    assert _parse_nest_error("") is None


def test_parse_nest_innermost_frame_wins():
    # Multiple JS frames -> the LAST one wins (matching the
    # existing python / dotnet / kotlin conventions).
    text = (
        "[Nest] 1 ERROR [ExceptionsHandler] Boom\n"
        "InternalServerErrorException: Boom\n"
        "    at outer (/app/src/outer.ts:10:5)\n"
        "    at inner (/app/src/inner.ts:42:11)\n"
    )
    out = _parse_nest_error(text)
    assert out is not None
    _, _, file_, line_ = out
    assert file_ == "/app/src/inner.ts"
    assert line_ == 42


# ---- Likely cause hints --------------------------------------


def test_cause_not_found():
    assert "missing" in (_nest_likely_cause("NotFoundException", "") or "").lower()


def test_cause_unauthorized():
    assert "auth" in (_nest_likely_cause("UnauthorizedException", "") or "").lower()


def test_cause_forbidden():
    assert "rbac" in (_nest_likely_cause("ForbiddenException", "") or "").lower()


def test_cause_bad_request():
    assert "validation" in (_nest_likely_cause("BadRequestException", "") or "").lower()


def test_cause_validation():
    cause = _nest_likely_cause("ValidationException", "validation failed")
    assert cause is not None
    assert "validator" in cause.lower() or "dto" in cause.lower()


def test_cause_conflict():
    assert "exists" in (_nest_likely_cause("ConflictException", "") or "").lower()


def test_cause_too_many_requests():
    assert "rate" in (_nest_likely_cause("TooManyRequestsException", "") or "").lower()


def test_cause_internal_server_error():
    assert "stack" in (_nest_likely_cause("InternalServerErrorException", "") or "").lower()


def test_cause_bad_gateway():
    cause = _nest_likely_cause("BadGatewayException", "")
    assert cause is not None
    assert "upstream" in cause.lower()


def test_cause_service_unavailable():
    cause = _nest_likely_cause("ServiceUnavailableException", "")
    assert cause is not None
    assert "down" in cause.lower() or "unhealthy" in cause.lower()


def test_cause_gateway_timeout():
    cause = _nest_likely_cause("GatewayTimeoutException", "")
    assert cause is not None
    assert "timeout" in cause.lower() or "deadline" in cause.lower()


def test_cause_rpc():
    cause = _nest_likely_cause("RpcException", "")
    assert cause is not None
    assert "microservice" in cause.lower()


def test_cause_ws():
    cause = _nest_likely_cause("WsException", "")
    assert cause is not None
    assert "websocket" in cause.lower()


def test_cause_http_exception_generic():
    cause = _nest_likely_cause("HttpException", "")
    assert cause is not None
    assert "http" in cause.lower()


def test_cause_message_based_not_found():
    # The cause inspects the MESSAGE too, not only the exception
    # class name.
    cause = _nest_likely_cause("CustomException", "User not found")
    assert cause is not None


def test_cause_returns_none_for_unknown():
    assert _nest_likely_cause("MysteryException", "weird thing happened") is None


# ---- parse_error_text integration ---------------------------


def test_parse_error_text_returns_nestjs_framework():
    text = (
        "[Nest] 12345 - 12/22/2026   ERROR [ExceptionsHandler] User not found\n"
        "NotFoundException: User not found\n"
        "    at UserController.findOne (/app/src/users/users.controller.ts:42:11)\n"
    )
    err = parse_error_text(text)
    assert err.framework == "nestjs"
    assert err.exception == "NotFoundException"
    assert err.message and "User not found" in err.message
    assert err.file is not None and "users.controller.ts" in err.file
    assert err.line == 42


def test_parse_error_text_nest_with_typed_exception_uses_typed():
    text = (
        "[Nest] 1 ERROR [HttpExceptionFilter] some message\n"
        "UnauthorizedException: jwt expired\n"
    )
    err = parse_error_text(text)
    assert err.framework == "nestjs"
    assert err.exception == "UnauthorizedException"


def test_parse_error_text_nest_preempts_node_branch():
    # A NestJS log also contains JS-style frames; without the
    # Nest discriminator, the Node branch would steal it. The
    # framework tag must be ``nestjs``, not ``node``.
    text = (
        "[Nest] 1 ERROR [ExceptionsHandler] err\n"
        "Error: boom\n"
        "    at foo (/x.ts:1:1)\n"
    )
    err = parse_error_text(text)
    assert err.framework == "nestjs"


def test_parse_error_text_node_unchanged_without_nest_prelude():
    # Without the [Nest] prefix, a pure Node trace still tags as
    # "node". Regression-check: our new branch must not steal
    # vanilla Node traces.
    text = (
        "Error: boom\n"
        "    at foo (/x.js:1:1)\n"
        "    at Object.<anonymous> (/y.js:2:2)\n"
    )
    err = parse_error_text(text)
    assert err.framework == "node"


def test_parse_error_text_nest_with_likely_cause():
    text = (
        "[Nest] 1 ERROR [ExceptionsHandler] User not found\n"
        "NotFoundException: User not found\n"
    )
    err = parse_error_text(text)
    assert err.likely_cause is not None
    assert "missing" in err.likely_cause.lower()


def test_parse_error_text_nest_minimal_form():
    # Just the prelude, no exception class, no frames.
    text = "[Nest] 1 ERROR [ExceptionsHandler] something broke"
    err = parse_error_text(text)
    assert err.framework == "nestjs"
    assert err.exception == "ExceptionsHandler"
    assert err.message and "something broke" in err.message


# ---- enrich integration -------------------------------------


def test_enrich_writes_nest_framework():
    text = (
        "[Nest] 1 ERROR [ExceptionsHandler] User not found\n"
        "NotFoundException: User not found\n"
        "    at UserController.findOne (/app/src/users/users.controller.ts:42:11)\n"
    )
    ocr = OCRResult(text=text)
    out = enrich(Category.error_stacktrace, ExtractedFields(), ocr)
    assert out.error is not None
    assert out.error.framework == "nestjs"
    assert out.error.exception == "NotFoundException"


def test_enrich_preserves_caller_framework_when_set():
    # Caller (LLM) already supplied framework; we don't override.
    text = (
        "[Nest] 1 ERROR [ExceptionsHandler] err\n"
        "NotFoundException: missing\n"
    )
    ocr = OCRResult(text=text)
    caller = ErrorFields(framework="custom-llm-tag", exception="MysteryException")
    fields = ExtractedFields(error=caller)
    out = enrich(Category.error_stacktrace, fields, ocr)
    assert out.error is not None
    # enrich_error keeps caller-set values; OCR parse fills in blanks
    # only.
    assert out.error.framework == "custom-llm-tag"


# ---- Branch placement defence -------------------------------


def test_nest_after_php_branch():
    # A PHP fatal-error log with a Nest-looking message in the body
    # should still tag as PHP, not nestjs. The [Nest] prefix is the
    # discriminator.
    text = (
        "PHP Fatal error: Uncaught NotFoundException: Resource not found "
        "in /app/foo.php:42\n"
    )
    err = parse_error_text(text)
    assert err.framework == "php"


def test_nest_does_not_steal_dotnet_trace():
    # A .NET trace shouldn't fall into the nest branch.
    text = (
        "System.NullReferenceException: Object reference not set\n"
        "   at Foo.Bar() in /src/Foo.cs:line 12\n"
    )
    err = parse_error_text(text)
    assert err.framework == "dotnet"


def test_nest_does_not_steal_python_traceback():
    text = (
        "Traceback (most recent call last):\n"
        '  File "foo.py", line 10, in main\n'
        "    bar()\n"
        "ValueError: bad value\n"
    )
    err = parse_error_text(text)
    assert err.framework == "python"


def test_nest_prefix_in_payload_does_not_misfire():
    # A document that mentions "[Nest]" in prose without the
    # ERROR tag should NOT trigger the nest branch.
    text = "The [Nest] framework is great. ValueError: oops"
    err = parse_error_text(text)
    # Falls through to generic Error/Exception regex; framework
    # ends up either "unknown" or whatever matches downstream.
    # The key invariant is: NOT "nestjs".
    assert err.framework != "nestjs"


# ---- Comprehensive exception catalogue ---------------------


def test_conflict_exception():
    text = (
        "[Nest] 1 ERROR [ExceptionsHandler] Email already in use\n"
        "ConflictException: Email already in use\n"
    )
    err = parse_error_text(text)
    assert err.framework == "nestjs"
    assert err.exception == "ConflictException"


def test_too_many_requests_exception():
    text = (
        "[Nest] 1 ERROR [ThrottlerGuard] Too many requests\n"
        "TooManyRequestsException: Rate limit exceeded\n"
    )
    err = parse_error_text(text)
    assert err.framework == "nestjs"
    assert err.exception == "TooManyRequestsException"


def test_unprocessable_entity_exception():
    text = (
        "[Nest] 1 ERROR [ExceptionsHandler] Payload unprocessable\n"
        "UnprocessableEntityException: Cannot process this\n"
    )
    err = parse_error_text(text)
    assert err.framework == "nestjs"
    assert err.exception == "UnprocessableEntityException"


def test_im_a_teapot_exception():
    text = (
        "[Nest] 1 ERROR [ExceptionsHandler] I'm a teapot\n"
        "ImATeapotException: 418\n"
    )
    err = parse_error_text(text)
    assert err.framework == "nestjs"
    assert err.exception == "ImATeapotException"
