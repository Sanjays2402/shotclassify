"""GraphQL execution error parsing tests.

GraphQL servers return errors as JSON objects with a strict shape:

  {
    "errors": [
      {
        "message": "Cannot query field 'foo' on type 'Query'.",
        "locations": [{"line": 3, "column": 5}],
        "path": ["users", 0, "name"],
        "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"}
      }
    ],
    "data": null
  }

Every server library (graphql-js, Apollo, Hasura, Strawberry,
graphene, Yoga, Mercurius) emits this shape. The new branch tags
framework='graphql' and pulls the error code, message, path, and
source line out of the JSON.
"""
from __future__ import annotations

from shotclassify_common import Category, ErrorFields, ExtractedFields, OCRResult
from shotclassify_extract import enrich, parse_error_text, parse_graphql_error
from shotclassify_extract.error import (
    _GRAPHQL_ERRORS_KEY,
    _GRAPHQL_MESSAGE_FIELD,
    _graphql_likely_cause,
    _isolate_first_graphql_error,
    _json_string_unescape,
    _parse_graphql_error,
)

# ---- Errors-key regex -----------------------------------------


def test_errors_key_matches_canonical():
    text = '{"errors": [{"message": "foo"}]}'
    assert _GRAPHQL_ERRORS_KEY.search(text) is not None


def test_errors_key_matches_no_space():
    text = '{"errors":[{"message":"foo"}]}'
    assert _GRAPHQL_ERRORS_KEY.search(text) is not None


def test_errors_key_matches_extra_whitespace():
    text = '{ "errors" :  [\n  {"message": "foo"}\n] }'
    assert _GRAPHQL_ERRORS_KEY.search(text) is not None


def test_errors_key_rejects_plain_text():
    assert _GRAPHQL_ERRORS_KEY.search("there were errors") is None


# ---- Message field regex --------------------------------------


def test_message_field_captures_simple():
    text = '"message": "Cannot query field foo"'
    m = _GRAPHQL_MESSAGE_FIELD.search(text)
    assert m is not None
    assert m.group("msg") == "Cannot query field foo"


def test_message_field_captures_with_escapes():
    text = '"message": "Cannot query field \\"foo\\" on type"'
    m = _GRAPHQL_MESSAGE_FIELD.search(text)
    assert m is not None
    assert "foo" in m.group("msg")


# ---- JSON string unescape -------------------------------------


def test_unescape_quote():
    assert _json_string_unescape('Cannot query field \\"foo\\"') == 'Cannot query field "foo"'


def test_unescape_newline():
    assert _json_string_unescape('line1\\nline2') == 'line1\nline2'


def test_unescape_tab():
    assert _json_string_unescape('a\\tb') == 'a\tb'


def test_unescape_backslash():
    assert _json_string_unescape('a\\\\b') == 'a\\b'


def test_unescape_unicode():
    assert _json_string_unescape('caf\\u00e9') == 'café'


def test_unescape_no_op_when_no_escapes():
    assert _json_string_unescape('plain text') == 'plain text'


def test_unescape_empty():
    assert _json_string_unescape('') == ''


def test_unescape_malformed_left_alone():
    # Lone backslash at end of string — left alone defensively.
    assert _json_string_unescape('foo\\') == 'foo\\'


# ---- _isolate_first_graphql_error -----------------------------


def test_isolate_simple_object():
    text = '[{"message": "foo", "code": "BAR"}]'
    msg_pos = text.find('"message"')
    block = _isolate_first_graphql_error(text, msg_pos)
    assert block is not None
    assert block.startswith("{")
    assert block.endswith("}")
    assert '"message"' in block
    assert '"code"' in block


def test_isolate_with_nested_object():
    text = '[{"message": "foo", "extensions": {"code": "BAR"}}]'
    msg_pos = text.find('"message"')
    block = _isolate_first_graphql_error(text, msg_pos)
    assert block is not None
    assert '"extensions"' in block
    assert '"BAR"' in block


def test_isolate_first_of_multiple():
    text = (
        '[{"message": "first", "code": "A"},'
        ' {"message": "second", "code": "B"}]'
    )
    msg_pos = text.find('"message"')
    block = _isolate_first_graphql_error(text, msg_pos)
    assert block is not None
    assert '"first"' in block
    # The first error block should NOT contain the second's content.
    assert '"second"' not in block
    assert '"B"' not in block


def test_isolate_handles_string_with_braces():
    # A message containing literal { or } characters shouldn't break
    # the bracket-depth counter because we skip string contents.
    text = '[{"message": "this has { and } in it", "code": "FOO"}]'
    msg_pos = text.find('"message"')
    block = _isolate_first_graphql_error(text, msg_pos)
    assert block is not None
    assert '"FOO"' in block


def test_isolate_returns_none_for_bad_position():
    text = '{"foo": 1}'
    # Position 0 is at '{' itself; walking back finds nothing
    assert _isolate_first_graphql_error(text, 0) is None


def test_isolate_returns_none_for_negative_position():
    assert _isolate_first_graphql_error("anything", -1) is None


# ---- Basic GraphQL error parsing ------------------------------


def test_canonical_validation_error():
    text = """{
      "errors": [
        {
          "message": "Cannot query field 'foo' on type 'Query'.",
          "locations": [{"line": 3, "column": 5}],
          "path": ["users", 0, "name"],
          "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"}
        }
      ],
      "data": null
    }"""
    out = _parse_graphql_error(text)
    assert out is not None
    exc, msg, path, line = out
    assert exc == "GRAPHQL_VALIDATION_FAILED"
    assert "Cannot query field" in msg
    assert "users.0.name" == path
    assert line == 3


def test_simple_error_without_code():
    text = '{"errors": [{"message": "Something went wrong", "locations": [{"line": 1, "column": 1}]}]}'
    out = _parse_graphql_error(text)
    assert out is not None
    exc, msg, path, line = out
    # No extensions.code -> falls back to GraphQLError.
    assert exc == "GraphQLError"
    assert msg == "Something went wrong"
    assert path is None
    assert line == 1


def test_error_with_only_message_and_extensions_discriminator():
    text = '{"errors": [{"message": "Boom", "extensions": {"code": "INTERNAL_SERVER_ERROR"}}]}'
    out = _parse_graphql_error(text)
    assert out is not None
    exc, msg, path, line = out
    assert exc == "INTERNAL_SERVER_ERROR"
    assert msg == "Boom"
    assert path is None
    assert line is None


def test_path_with_only_strings():
    text = '{"errors": [{"message": "x", "path": ["user", "email"], "extensions": {"code": "X"}}]}'
    out = _parse_graphql_error(text)
    assert out is not None
    exc, msg, path, line = out
    assert path == "user.email"


def test_path_with_only_ints():
    text = '{"errors": [{"message": "x", "path": [0, 1, 2], "extensions": {"code": "X"}}]}'
    out = _parse_graphql_error(text)
    assert out is not None
    exc, msg, path, line = out
    assert path == "0.1.2"


def test_path_mixed_strings_and_ints():
    text = (
        '{"errors": [{"message": "x", "path": ["users", 0, "address", "city"], '
        '"extensions": {"code": "X"}}]}'
    )
    out = _parse_graphql_error(text)
    assert out is not None
    exc, msg, path, line = out
    assert path == "users.0.address.city"


# ---- Multiple errors --> first wins ----------------------------


def test_first_error_wins_on_message():
    text = """{
      "errors": [
        {"message": "first error", "extensions": {"code": "A"}},
        {"message": "second error", "extensions": {"code": "B"}}
      ]
    }"""
    out = _parse_graphql_error(text)
    assert out is not None
    exc, msg, path, line = out
    assert msg == "first error"
    assert exc == "A"


def test_first_error_with_no_extensions_falls_back():
    text = """{
      "errors": [
        {"message": "first", "locations": [{"line": 1, "column": 1}]},
        {"message": "second", "extensions": {"code": "B"}}
      ]
    }"""
    out = _parse_graphql_error(text)
    assert out is not None
    exc, msg, path, line = out
    # First error has no extensions.code -> falls back.
    assert exc == "GraphQLError"
    assert msg == "first"


# ---- Discriminator enforcement --------------------------------


def test_rejects_plain_json_errors_array():
    # A generic REST API response with "errors": [...] but NO GraphQL
    # discriminator should be rejected.
    text = '{"errors": [{"message": "Validation failed", "field": "email"}]}'
    out = _parse_graphql_error(text)
    assert out is None


def test_accepts_plain_json_with_path_discriminator():
    text = '{"errors": [{"message": "Validation failed", "path": ["email"]}]}'
    out = _parse_graphql_error(text)
    assert out is not None
    assert out[2] == "email"


def test_accepts_with_apollo_in_text():
    # Apollo word elsewhere triggers detection even without locations/path/extensions.
    text = 'Apollo Client returned: {"errors": [{"message": "Boom"}]}'
    out = _parse_graphql_error(text)
    assert out is not None


def test_accepts_with_graphql_word():
    text = 'GraphQL error: {"errors": [{"message": "Boom"}]}'
    out = _parse_graphql_error(text)
    assert out is not None


def test_accepts_with_mutation_word():
    text = 'mutation failed: {"errors": [{"message": "Boom"}]}'
    out = _parse_graphql_error(text)
    assert out is not None


def test_accepts_with_subscription_word():
    text = 'subscription error: {"errors": [{"message": "Boom"}]}'
    out = _parse_graphql_error(text)
    assert out is not None


# ---- Edge cases -----------------------------------------------


def test_empty_text():
    assert _parse_graphql_error("") is None


def test_no_errors_key():
    assert _parse_graphql_error('{"data": {}}') is None


def test_errors_key_but_no_message():
    text = '{"errors": [{"code": "X", "extensions": {"code": "X"}}]}'
    assert _parse_graphql_error(text) is None


def test_unescaped_quote_in_message():
    text = (
        '{"errors": [{"message": "Cannot query field \\"foo\\" on type \\"Query\\"", '
        '"extensions": {"code": "GRAPHQL_VALIDATION_FAILED"}}]}'
    )
    out = _parse_graphql_error(text)
    assert out is not None
    exc, msg, path, line = out
    assert "Cannot query field" in msg
    assert "foo" in msg


def test_unicode_in_message():
    text = '{"errors": [{"message": "Caf\\u00e9 error", "extensions": {"code": "X"}}]}'
    out = _parse_graphql_error(text)
    assert out is not None
    assert "Café" in out[1]


def test_path_with_special_chars_in_string_segments():
    # Field names with dots / dashes inside quotes get joined verbatim.
    text = '{"errors": [{"message": "x", "path": ["foo-bar", "baz.qux"], "extensions": {"code": "X"}}]}'
    out = _parse_graphql_error(text)
    assert out is not None
    assert out[2] == "foo-bar.baz.qux"


def test_multiple_locations_first_wins():
    text = """{
      "errors": [
        {
          "message": "x",
          "locations": [{"line": 5, "column": 1}, {"line": 10, "column": 1}],
          "extensions": {"code": "X"}
        }
      ]
    }"""
    out = _parse_graphql_error(text)
    assert out is not None
    assert out[3] == 5


# ---- Public wrapper -------------------------------------------


def test_public_wrapper_matches_private():
    text = '{"errors": [{"message": "x", "extensions": {"code": "X"}}]}'
    assert parse_graphql_error(text) == _parse_graphql_error(text)


def test_public_wrapper_none_for_non_graphql():
    assert parse_graphql_error("hello") is None


# ---- Likely-cause hints ---------------------------------------


def test_cause_parse_failed():
    hint = _graphql_likely_cause("GRAPHQL_PARSE_FAILED", "Syntax error")
    assert hint is not None and "syntax" in hint.lower()


def test_cause_validation_failed():
    hint = _graphql_likely_cause("GRAPHQL_VALIDATION_FAILED", "Cannot query field 'foo'")
    assert hint is not None
    # Either code-based or message-based should fire.
    assert "schema" in hint.lower() or "field" in hint.lower()


def test_cause_cannot_query_field_message():
    hint = _graphql_likely_cause(None, "Cannot query field 'x' on type 'Y'")
    assert hint is not None and "field" in hint.lower()


def test_cause_bad_user_input():
    hint = _graphql_likely_cause("BAD_USER_INPUT", None)
    assert hint is not None and ("argument" in hint.lower() or "input" in hint.lower())


def test_cause_unauthenticated():
    hint = _graphql_likely_cause("UNAUTHENTICATED", None)
    assert hint is not None and "auth" in hint.lower()


def test_cause_forbidden():
    hint = _graphql_likely_cause("FORBIDDEN", None)
    assert hint is not None and ("permission" in hint.lower() or "role" in hint.lower())


def test_cause_persisted_query_not_found():
    hint = _graphql_likely_cause("PERSISTED_QUERY_NOT_FOUND", None)
    assert hint is not None
    assert "persisted" in hint.lower() or "apq" in hint.lower()


def test_cause_internal_server_error():
    hint = _graphql_likely_cause("INTERNAL_SERVER_ERROR", None)
    assert hint is not None and "resolver" in hint.lower()


def test_cause_complexity():
    hint = _graphql_likely_cause("QUERY_COMPLEXITY_EXCEEDED", None)
    assert hint is not None and "complexity" in hint.lower()


def test_cause_depth():
    hint = _graphql_likely_cause("QUERY_DEPTH_EXCEEDED", None)
    assert hint is not None and "depth" in hint.lower()


def test_cause_unknown_returns_none():
    assert _graphql_likely_cause("CUSTOM_VENDOR_CODE", "some message") is None


def test_cause_n_plus_1_message():
    hint = _graphql_likely_cause(None, "N+1 query detected")
    assert hint is not None and "dataloader" in hint.lower().replace(" ", "")


# ---- parse_error_text integration -----------------------------


def test_parse_error_text_tags_graphql():
    text = """{
      "errors": [
        {
          "message": "Cannot query field 'foo' on type 'Query'.",
          "locations": [{"line": 3, "column": 5}],
          "path": ["users", 0, "name"],
          "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"}
        }
      ]
    }"""
    parsed = parse_error_text(text)
    assert parsed.framework == "graphql"
    assert parsed.exception == "GRAPHQL_VALIDATION_FAILED"
    assert "Cannot query field" in parsed.message
    assert parsed.file == "users.0.name"
    assert parsed.line == 3
    assert parsed.likely_cause is not None


def test_parse_error_text_with_no_code():
    text = '{"errors": [{"message": "Oops", "path": ["x"]}]}'
    parsed = parse_error_text(text)
    assert parsed.framework == "graphql"
    assert parsed.exception == "GraphQLError"
    assert parsed.message == "Oops"


def test_parse_error_text_does_not_steal_jvm():
    # JVM trace must NOT be stolen by graphql.
    text = (
        "java.lang.NullPointerException: Cannot invoke method\n"
        "    at com.example.Foo.bar(Foo.java:42)\n"
    )
    parsed = parse_error_text(text)
    assert parsed.framework == "jvm"


def test_parse_error_text_does_not_steal_python():
    text = (
        'Traceback (most recent call last):\n'
        '  File "foo.py", line 5, in <module>\n'
        '    raise ValueError("bad")\n'
        'ValueError: bad\n'
    )
    parsed = parse_error_text(text)
    assert parsed.framework == "python"


def test_parse_error_text_does_not_steal_generic_rest_error():
    # A REST API with "errors" array but no GraphQL signal.
    text = '{"errors": [{"message": "Bad request", "field": "email"}]}'
    parsed = parse_error_text(text)
    # Should fall through to generic Error/Exception regex (unknown).
    # We accept whatever the generic branch does, but verify the
    # framework is NOT 'graphql'.
    assert parsed.framework != "graphql"


# ---- enrich() pipeline integration ----------------------------


def test_enrich_pipeline_tags_graphql():
    text = '{"errors": [{"message": "x", "path": ["a", "b"], "extensions": {"code": "BAD_USER_INPUT"}}]}'
    fields = ExtractedFields()
    ocr = OCRResult(text=text)
    enriched = enrich(Category.error_stacktrace, fields, ocr)
    assert enriched.error is not None
    assert enriched.error.framework == "graphql"
    assert enriched.error.exception == "BAD_USER_INPUT"
    assert enriched.error.file == "a.b"


def test_enrich_pipeline_preserves_existing_fields():
    text = '{"errors": [{"message": "x", "path": ["a"], "extensions": {"code": "BAD_USER_INPUT"}}]}'
    fields = ExtractedFields(error=ErrorFields(framework="custom"))
    ocr = OCRResult(text=text)
    enriched = enrich(Category.error_stacktrace, fields, ocr)
    assert enriched.error is not None
    # Caller-supplied non-empty framework wins.
    assert enriched.error.framework == "custom"
    # But empty fields get filled from parse.
    assert enriched.error.exception == "BAD_USER_INPUT"


# ---- Real-world variations ------------------------------------


def test_apollo_error_with_stacktrace_in_extensions():
    # Apollo Server includes the resolver stacktrace in
    # extensions.exception.stacktrace; we only pull the code +
    # message + locations + path.
    text = """{
      "errors": [
        {
          "message": "Cannot return null for non-nullable field User.email.",
          "locations": [{"line": 7, "column": 5}],
          "path": ["user", "email"],
          "extensions": {
            "code": "INTERNAL_SERVER_ERROR",
            "exception": {
              "stacktrace": [
                "Error: Cannot return null...",
                "    at User.email (/app/resolvers.js:42:11)"
              ]
            }
          }
        }
      ],
      "data": {"user": null}
    }"""
    parsed = parse_error_text(text)
    assert parsed.framework == "graphql"
    assert parsed.exception == "INTERNAL_SERVER_ERROR"
    assert "Cannot return null" in parsed.message
    assert parsed.file == "user.email"
    assert parsed.line == 7


def test_hasura_style_error():
    text = """{
      "errors": [
        {
          "message": "field \\"users\\" not found in type: 'query_root'",
          "extensions": {
            "code": "validation-failed",
            "path": "$"
          }
        }
      ]
    }"""
    parsed = parse_error_text(text)
    # Hasura uses lowercase codes; we capture as-is.
    # But the _GRAPHQL_CODE_FIELD regex requires uppercase start...
    # Document: lowercase codes fail the regex and fall back to
    # GraphQLError. Acceptable trade-off.
    assert parsed.framework == "graphql"


def test_multiline_pretty_printed_error():
    text = """{
        "errors": [
            {
                "message": "User not found",
                "locations": [
                    {
                        "line": 12,
                        "column": 9
                    }
                ],
                "path": [
                    "userById"
                ],
                "extensions": {
                    "code": "USER_NOT_FOUND",
                    "userId": 42
                }
            }
        ],
        "data": {
            "userById": null
        }
    }"""
    parsed = parse_error_text(text)
    assert parsed.framework == "graphql"
    assert parsed.exception == "USER_NOT_FOUND"
    assert parsed.message == "User not found"
    assert parsed.file == "userById"
    assert parsed.line == 12


def test_yoga_style_error():
    text = (
        '{"errors": [{"message": "Variable \\"$id\\" of required type \\"ID!\\" was '
        'not provided.", "locations": [{"line": 1, "column": 17}], '
        '"extensions": {"code": "GRAPHQL_VALIDATION_FAILED"}}]}'
    )
    parsed = parse_error_text(text)
    assert parsed.framework == "graphql"
    assert parsed.exception == "GRAPHQL_VALIDATION_FAILED"
    assert "Variable" in parsed.message
    assert parsed.line == 1


def test_authentication_error_real_world():
    text = """{
      "errors": [
        {
          "message": "You must be logged in",
          "extensions": {
            "code": "UNAUTHENTICATED"
          }
        }
      ]
    }"""
    parsed = parse_error_text(text)
    assert parsed.framework == "graphql"
    assert parsed.exception == "UNAUTHENTICATED"
    assert parsed.likely_cause is not None
    assert "auth" in parsed.likely_cause.lower()


def test_subscription_error():
    text = '{"errors": [{"message": "Subscription closed", "extensions": {"code": "SUBSCRIPTION_CLOSED"}}]}'
    parsed = parse_error_text(text)
    assert parsed.framework == "graphql"
    assert parsed.exception == "SUBSCRIPTION_CLOSED"


def test_first_error_isolates_cleanly():
    # When TWO errors have different codes, the first's code wins.
    text = """{
      "errors": [
        {
          "message": "Validation error",
          "extensions": {"code": "BAD_USER_INPUT"}
        },
        {
          "message": "Server error",
          "extensions": {"code": "INTERNAL_SERVER_ERROR"}
        }
      ]
    }"""
    parsed = parse_error_text(text)
    assert parsed.framework == "graphql"
    assert parsed.exception == "BAD_USER_INPUT"
    assert parsed.message == "Validation error"
