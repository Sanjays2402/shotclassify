"""AWS Lambda / boto3 client error extraction tests.

boto3 / botocore errors are surfaced from Python tracebacks with a
distinctive message format:

  botocore.exceptions.ClientError: An error occurred (NoSuchBucket)
      when calling the HeadBucket operation: The specified bucket
      does not exist

The extractor pulls:
* exception class name (ClientError, NoSuchKey, BotoCoreError, ...)
* error_code (NoSuchBucket, AccessDenied, Throttling, ...)
* operation_name (HeadBucket, GetObject, PutItem, ...)
* file + line from the innermost Python frame

When a Python traceback ALSO carries a boto-specific exception class
or the canonical "An error occurred ..." message, the framework tag
is `boto3` (not generic `python`). The error_code and operation are
embedded in the message slot as `[code=X op=Y]` tags so dashboards
can group by AWS API + error pair without re-parsing.
"""
from __future__ import annotations

from shotclassify_common import Category, ErrorFields, ExtractedFields, OCRResult
from shotclassify_extract import enrich, parse_error_text
from shotclassify_extract.error import (
    _BOTO_CLIENT_ERROR,
    _BOTO_EXC_HEADER,
    _boto_likely_cause,
    _parse_boto_error,
)

# ---- Canonical ClientError message regex ----------------------


def test_client_error_message_basic():
    text = "An error occurred (NoSuchBucket) when calling the HeadBucket operation"
    m = _BOTO_CLIENT_ERROR.search(text)
    assert m is not None
    assert m.group("code") == "NoSuchBucket"
    assert m.group("op") == "HeadBucket"


def test_client_error_message_with_detail():
    text = (
        "An error occurred (NoSuchKey) when calling the GetObject "
        "operation: The specified key does not exist."
    )
    m = _BOTO_CLIENT_ERROR.search(text)
    assert m is not None
    assert m.group("code") == "NoSuchKey"
    assert m.group("op") == "GetObject"
    assert "does not exist" in m.group("detail")


def test_client_error_access_denied():
    text = (
        "An error occurred (AccessDenied) when calling the ListObjectsV2 "
        "operation: Access Denied"
    )
    m = _BOTO_CLIENT_ERROR.search(text)
    assert m is not None
    assert m.group("code") == "AccessDenied"
    assert m.group("op") == "ListObjectsV2"


def test_client_error_throttling():
    text = (
        "An error occurred (ThrottlingException) when calling the "
        "PutItem operation: Rate exceeded"
    )
    m = _BOTO_CLIENT_ERROR.search(text)
    assert m is not None
    assert "Throttling" in m.group("code")


def test_client_error_rejects_unrelated_text():
    text = "An error happened in some random way"
    assert _BOTO_CLIENT_ERROR.search(text) is None


# ---- Boto exception-header regex ------------------------------


def test_exc_header_botocore_exceptions():
    text = "botocore.exceptions.ClientError: stuff"
    m = _BOTO_EXC_HEADER.search(text)
    assert m is not None
    assert m.group("exc") == "ClientError"


def test_exc_header_botocore_errorfactory():
    text = "botocore.errorfactory.NoSuchKey: An error occurred..."
    m = _BOTO_EXC_HEADER.search(text)
    assert m is not None
    assert m.group("exc") == "NoSuchKey"


def test_exc_header_botocore_client_error():
    text = "botocore.exceptions.NoCredentialsError: Unable to locate credentials"
    m = _BOTO_EXC_HEADER.search(text)
    assert m is not None
    assert m.group("exc") == "NoCredentialsError"


def test_exc_header_boto3_exceptions():
    text = "boto3.exceptions.S3UploadFailedError: Failed to upload"
    m = _BOTO_EXC_HEADER.search(text)
    assert m is not None
    assert m.group("exc") == "S3UploadFailedError"


def test_exc_header_endpoint_connection():
    text = "botocore.exceptions.EndpointConnectionError: Could not connect"
    m = _BOTO_EXC_HEADER.search(text)
    assert m is not None
    assert m.group("exc") == "EndpointConnectionError"


def test_exc_header_rejects_random_exception():
    text = "ValueError: not a boto error"
    assert _BOTO_EXC_HEADER.search(text) is None


# ---- _parse_boto_error ----------------------------------------


def test_parse_boto_classic_client_error():
    text = (
        "botocore.exceptions.ClientError: An error occurred (NoSuchBucket) "
        "when calling the HeadBucket operation: The specified bucket "
        "does not exist"
    )
    out = _parse_boto_error(text)
    assert out is not None
    exc, msg, code, op = out
    assert exc == "ClientError"
    assert code == "NoSuchBucket"
    assert op == "HeadBucket"
    assert "does not exist" in msg
    assert "code=NoSuchBucket" in msg
    assert "op=HeadBucket" in msg


def test_parse_boto_error_factory_nosuchkey():
    text = (
        "botocore.errorfactory.NoSuchKey: An error occurred (NoSuchKey) "
        "when calling the GetObject operation: The specified key does not exist."
    )
    out = _parse_boto_error(text)
    assert out is not None
    exc, msg, code, op = out
    assert exc == "NoSuchKey"
    assert code == "NoSuchKey"
    assert op == "GetObject"


def test_parse_boto_no_credentials():
    text = "botocore.exceptions.NoCredentialsError: Unable to locate credentials"
    out = _parse_boto_error(text)
    assert out is not None
    exc, msg, code, op = out
    assert exc == "NoCredentialsError"
    assert "Unable to locate" in msg
    # No client error -> code and op stay None.
    assert code is None
    assert op is None


def test_parse_boto_endpoint_connection_error():
    text = (
        "botocore.exceptions.EndpointConnectionError: "
        "Could not connect to the endpoint URL"
    )
    out = _parse_boto_error(text)
    assert out is not None
    exc, _, _, _ = out
    assert exc == "EndpointConnectionError"


def test_parse_boto_param_validation():
    text = (
        "botocore.exceptions.ParamValidationError: Parameter validation failed:\n"
        "  Missing required parameter in input: \"Bucket\""
    )
    out = _parse_boto_error(text)
    assert out is not None
    exc, _, _, _ = out
    assert exc == "ParamValidationError"


def test_parse_boto_waiter_error():
    text = "botocore.exceptions.WaiterError: Waiter ObjectExists failed"
    out = _parse_boto_error(text)
    assert out is not None
    exc, _, _, _ = out
    assert exc == "WaiterError"


def test_parse_boto_bare_client_error_message():
    # When ONLY the canonical message is present (no exception header
    # in the text), the matcher still fires and uses ``ClientError``
    # as the exception slot.
    text = (
        "An error occurred (Throttling) when calling the "
        "PutMetricData operation: Rate exceeded"
    )
    out = _parse_boto_error(text)
    assert out is not None
    exc, msg, code, op = out
    assert exc == "ClientError"
    assert code == "Throttling"
    assert op == "PutMetricData"


def test_parse_boto_dotted_error_code():
    # Some hypothetical AWS services *could* prefix the error code
    # with a service ID (#-separated). Our matcher's `[\w.]` char
    # class doesn't include `#` so a `com.amazonaws.s3#NoSuchKey`
    # code does NOT parse. This is documented as a known limitation
    # -- real customer captures of typed boto exceptions use the
    # bare ``NoSuchKey`` form. The matcher gracefully returns None
    # for the hash-prefixed form rather than mis-parsing.
    text = (
        "An error occurred (com.amazonaws.s3#NoSuchKey) when calling the "
        "GetObject operation"
    )
    out = _parse_boto_error(text)
    # Documented behavior: the # delimiter prevents the matcher
    # from firing on this rare prefix form. Falls through to None.
    assert out is None


def test_parse_boto_returns_none_for_non_boto():
    text = (
        "Traceback (most recent call last):\n"
        '  File "foo.py", line 10\n'
        "ValueError: bad value\n"
    )
    assert _parse_boto_error(text) is None


def test_parse_boto_returns_none_for_empty():
    assert _parse_boto_error("") is None


def test_parse_boto_full_traceback():
    text = (
        "Traceback (most recent call last):\n"
        '  File "/var/task/handler.py", line 42, in lambda_handler\n'
        "    s3.head_bucket(Bucket=bucket_name)\n"
        '  File "/var/runtime/botocore/client.py", line 553, in _api_call\n'
        "    return self._make_api_call(operation_name, kwargs)\n"
        '  File "/var/runtime/botocore/client.py", line 1009, in _make_api_call\n'
        "    raise error_class(parsed_response, operation_name)\n"
        "botocore.exceptions.ClientError: An error occurred (NoSuchBucket) "
        "when calling the HeadBucket operation: The specified bucket "
        "does not exist"
    )
    out = _parse_boto_error(text)
    assert out is not None
    exc, msg, code, op = out
    assert exc == "ClientError"
    assert code == "NoSuchBucket"
    assert op == "HeadBucket"


# ---- Likely cause hints --------------------------------------


def test_cause_no_credentials():
    cause = _boto_likely_cause("NoCredentialsError", None, "")
    assert cause is not None
    assert "credentials" in cause.lower()


def test_cause_partial_credentials():
    cause = _boto_likely_cause("PartialCredentialsError", None, "")
    assert cause is not None
    assert "access_key" in cause.lower() or "secret" in cause.lower()


def test_cause_profile_not_found():
    cause = _boto_likely_cause("ProfileNotFound", None, "")
    assert cause is not None
    assert "profile" in cause.lower()


def test_cause_endpoint_connection_error():
    cause = _boto_likely_cause("EndpointConnectionError", None, "")
    assert cause is not None
    assert "network" in cause.lower() or "endpoint" in cause.lower()


def test_cause_read_timeout():
    cause = _boto_likely_cause("ReadTimeoutError", None, "")
    assert cause is not None
    assert "timeout" in cause.lower()


def test_cause_ssl_error():
    cause = _boto_likely_cause("SSLError", None, "")
    assert cause is not None
    assert "tls" in cause.lower() or "ssl" in cause.lower()


def test_cause_param_validation():
    cause = _boto_likely_cause("ParamValidationError", None, "")
    assert cause is not None
    assert "param" in cause.lower() or "validation" in cause.lower()


def test_cause_nosuch_bucket():
    cause = _boto_likely_cause("ClientError", "NoSuchBucket", "")
    assert cause is not None
    assert "bucket" in cause.lower()


def test_cause_nosuch_key():
    cause = _boto_likely_cause("ClientError", "NoSuchKey", "")
    assert cause is not None
    assert "key" in cause.lower()


def test_cause_access_denied():
    cause = _boto_likely_cause("ClientError", "AccessDenied", "")
    assert cause is not None
    assert "iam" in cause.lower() or "permission" in cause.lower()


def test_cause_throttling():
    cause = _boto_likely_cause("ClientError", "Throttling", "")
    assert cause is not None
    assert "rate" in cause.lower() or "backoff" in cause.lower()


def test_cause_throttling_exception():
    cause = _boto_likely_cause("ClientError", "ThrottlingException", "")
    assert cause is not None
    assert "rate" in cause.lower()


def test_cause_resource_not_found():
    cause = _boto_likely_cause("ClientError", "ResourceNotFoundException", "")
    assert cause is not None
    assert "arn" in cause.lower() or "doesn't exist" in cause.lower() or "exist" in cause.lower()


def test_cause_token_expired():
    cause = _boto_likely_cause("ClientError", "ExpiredTokenException", "")
    assert cause is not None
    assert "sts" in cause.lower() or "token" in cause.lower()


def test_cause_internal_failure():
    cause = _boto_likely_cause("ClientError", "InternalFailure", "")
    assert cause is not None
    assert "internal" in cause.lower() or "retry" in cause.lower()


def test_cause_message_based_access_denied():
    # The matcher inspects the MESSAGE too when the error_code is
    # absent.
    cause = _boto_likely_cause("ClientError", None, "Access Denied for this resource")
    assert cause is not None
    assert "iam" in cause.lower() or "permission" in cause.lower()


def test_cause_returns_none_for_unknown():
    assert _boto_likely_cause("MysteryError", "UnknownCode", "") is None


# ---- parse_error_text integration ----------------------------


def test_parse_error_text_boto3_framework():
    text = (
        "Traceback (most recent call last):\n"
        '  File "/var/task/handler.py", line 42, in lambda_handler\n'
        "    s3.head_bucket(Bucket=bucket_name)\n"
        "botocore.exceptions.ClientError: An error occurred (NoSuchBucket) "
        "when calling the HeadBucket operation: The specified bucket "
        "does not exist"
    )
    err = parse_error_text(text)
    assert err.framework == "boto3"
    assert err.exception == "ClientError"
    assert err.file is not None
    assert "handler.py" in err.file
    assert err.line == 42


def test_parse_error_text_boto3_message_carries_code_and_op():
    text = (
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1, in main\n'
        "    raise\n"
        "botocore.exceptions.ClientError: An error occurred (AccessDenied) "
        "when calling the GetObject operation: Access Denied"
    )
    err = parse_error_text(text)
    assert err.framework == "boto3"
    assert err.message is not None
    assert "code=AccessDenied" in err.message
    assert "op=GetObject" in err.message


def test_parse_error_text_boto3_no_credentials():
    text = (
        "Traceback (most recent call last):\n"
        '  File "/app/main.py", line 5, in <module>\n'
        "    boto3.client('s3').list_buckets()\n"
        "botocore.exceptions.NoCredentialsError: Unable to locate credentials"
    )
    err = parse_error_text(text)
    assert err.framework == "boto3"
    assert err.exception == "NoCredentialsError"
    assert err.likely_cause is not None
    assert "credentials" in err.likely_cause.lower()


def test_parse_error_text_python_still_python_without_boto():
    # A plain Python traceback (no botocore signal) should still
    # tag as ``python`` not ``boto3``.
    text = (
        "Traceback (most recent call last):\n"
        '  File "foo.py", line 10\n'
        "ValueError: bad value\n"
    )
    err = parse_error_text(text)
    assert err.framework == "python"


def test_parse_error_text_boto3_throttling_has_likely_cause():
    text = (
        "Traceback (most recent call last):\n"
        '  File "/app/handler.py", line 1\n'
        "    raise\n"
        "botocore.exceptions.ClientError: An error occurred "
        "(ThrottlingException) when calling the PutMetricData "
        "operation: Rate exceeded"
    )
    err = parse_error_text(text)
    assert err.framework == "boto3"
    assert err.likely_cause is not None
    assert "rate" in err.likely_cause.lower() or "backoff" in err.likely_cause.lower()


def test_parse_error_text_boto3_endpoint_connection():
    text = (
        "Traceback (most recent call last):\n"
        '  File "/app/main.py", line 1\n'
        "    raise\n"
        "botocore.exceptions.EndpointConnectionError: "
        "Could not connect to the endpoint URL: \"https://s3.us-east-1.amazonaws.com/\""
    )
    err = parse_error_text(text)
    assert err.framework == "boto3"
    assert err.exception == "EndpointConnectionError"


def test_parse_error_text_boto3_param_validation():
    text = (
        "Traceback (most recent call last):\n"
        '  File "/app/main.py", line 1\n'
        "    raise\n"
        "botocore.exceptions.ParamValidationError: Parameter validation failed:\n"
        "  Missing required parameter in input: \"Bucket\""
    )
    err = parse_error_text(text)
    assert err.framework == "boto3"
    assert err.exception == "ParamValidationError"


def test_parse_error_text_lambda_invoke_error():
    # Lambda runtime captures: client invocation errors that surface
    # in CloudWatch logs.
    text = (
        "Traceback (most recent call last):\n"
        '  File "/var/task/handler.py", line 12, in lambda_handler\n'
        "    response = client.invoke(FunctionName=name)\n"
        '  File "/var/runtime/botocore/client.py", line 553, in _api_call\n'
        "    return self._make_api_call(operation_name, kwargs)\n"
        "botocore.exceptions.ClientError: An error occurred "
        "(ResourceNotFoundException) when calling the Invoke operation: "
        "Function not found"
    )
    err = parse_error_text(text)
    assert err.framework == "boto3"
    assert err.likely_cause is not None
    assert "arn" in err.likely_cause.lower() or "exist" in err.likely_cause.lower()


# ---- enrich integration --------------------------------------


def test_enrich_writes_boto3_framework():
    text = (
        "Traceback (most recent call last):\n"
        '  File "/app/h.py", line 1, in handler\n'
        "    raise\n"
        "botocore.exceptions.ClientError: An error occurred (NoSuchBucket) "
        "when calling the HeadBucket operation: The specified bucket does not exist"
    )
    ocr = OCRResult(text=text)
    out = enrich(Category.error_stacktrace, ExtractedFields(), ocr)
    assert out.error is not None
    assert out.error.framework == "boto3"
    assert out.error.exception == "ClientError"


def test_enrich_preserves_caller_framework():
    text = "botocore.exceptions.NoCredentialsError: Unable to locate credentials"
    ocr = OCRResult(text=text)
    # Without the traceback prelude, parse_boto_error fires from
    # the bare exception header. But enrich_error keeps the caller's
    # framework when set.
    caller = ErrorFields(framework="my-tag", exception="MysteryException")
    fields = ExtractedFields(error=caller)
    out = enrich(Category.error_stacktrace, fields, ocr)
    assert out.error is not None
    assert out.error.framework == "my-tag"


# ---- Regression guards ---------------------------------------


def test_boto_does_not_steal_pytest_failure():
    # pytest traces should still tag as pytest, not boto3, even
    # when the test function happens to mention "boto3" in its name.
    text = (
        "FAILED tests/test_boto.py::test_uploads\n"
        ">       assert response['Status'] == 'OK'\n"
        "E       AssertionError: assert 'FAIL' == 'OK'\n"
        "tests/test_boto.py:42: AssertionError\n"
    )
    err = parse_error_text(text)
    # pytest branch runs first; framework should be pytest.
    assert err.framework == "pytest"


def test_boto_does_not_misfire_on_prose():
    # A document that mentions botocore but isn't a traceback
    # should not trigger the boto3 branch.
    text = (
        "Our codebase uses botocore.exceptions.ClientError in many places. "
        "Migration is planned for next quarter."
    )
    err = parse_error_text(text)
    # No traceback prelude, no AWS error code/op pair. The
    # _BOTO_EXC_HEADER matches the line, so SOMETHING fires, but
    # without a Python traceback context the python branch never
    # entered. The bare boto match isn't called outside the python
    # branch, so the framework drops through to the generic
    # fallback.
    assert err.framework != "boto3"


def test_boto_does_not_overlap_with_nestjs():
    # A NestJS log should still tag as nestjs, not boto3.
    text = (
        "[Nest] 1 ERROR [ExceptionsHandler] AWS call failed\n"
        "Error: An error occurred (NoSuchBucket) when calling HeadBucket\n"
    )
    err = parse_error_text(text)
    # Nest prelude wins; framework is nestjs.
    assert err.framework == "nestjs"


# ---- File / line extraction ----------------------------------


def test_boto_innermost_frame_wins():
    text = (
        "Traceback (most recent call last):\n"
        '  File "/var/task/outer.py", line 10, in outer\n'
        '  File "/var/task/inner.py", line 42, in inner\n'
        "botocore.exceptions.ClientError: An error occurred (NoSuchBucket) "
        "when calling the HeadBucket operation: nope"
    )
    err = parse_error_text(text)
    assert err.framework == "boto3"
    assert err.file == "/var/task/inner.py"
    assert err.line == 42


def test_boto_no_frame_returns_none_file_line():
    text = (
        "Traceback (most recent call last):\n"
        "botocore.exceptions.NoCredentialsError: Unable to locate credentials"
    )
    err = parse_error_text(text)
    assert err.framework == "boto3"
    assert err.file is None
    assert err.line is None
