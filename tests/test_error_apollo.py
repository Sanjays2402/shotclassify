"""Apollo Client / Apollo Server error parsing tests.

Apollo's error shapes are distinct from the generic GraphQL
``errors: []`` JSON wrapper (already handled by the graphql framework
branch). Apollo emits:

* ``ApolloError: Network error: ...``     (Apollo Client wrapping fetch)
* ``ApolloError: GraphQL error: ...``     (Apollo Client wrapping server)
* ``[GraphQLError: ...]``                  (stringified array entry)
* ``AuthenticationError: ...``,
  ``ForbiddenError: ...``,
  ``UserInputError: ...``,
  ``ValidationError: ...``,
  ``PersistedQueryNotFoundError: ...``,
  ``MissingFieldError: ...``               (Apollo Server typed
                                            exception classes -- only
                                            tag as Apollo with anchor)
"""
from __future__ import annotations

from shotclassify_extract import parse_apollo_error, parse_error_text

# ---- 1) ApolloError: Network error: -------------------------


def test_apollo_network_error_failed_to_fetch():
    text = "ApolloError: Network error: Failed to fetch"
    result = parse_apollo_error(text)
    assert result is not None
    exc, msg, file_, line_ = result
    assert exc == "ApolloError"
    assert msg == "Network error: Failed to fetch"
    assert file_ is None
    assert line_ is None


def test_apollo_network_error_via_parse_error_text():
    text = "Error: ApolloError: Network error: Failed to fetch"
    fields = parse_error_text(text)
    assert fields.framework == "apollo"
    assert fields.exception == "ApolloError"
    assert "Network error" in (fields.message or "")
    assert "fetch" in (fields.likely_cause or "").lower()


def test_apollo_network_error_timeout():
    text = "ApolloError: Network error: Request timed out after 30s"
    result = parse_apollo_error(text)
    assert result is not None
    fields = parse_error_text(text)
    assert fields.framework == "apollo"
    assert "timeout" in (fields.likely_cause or "").lower()


def test_apollo_network_error_aborted():
    text = "ApolloError: Network error: The user aborted a request."
    fields = parse_error_text(text)
    assert fields.framework == "apollo"
    assert "abort" in (fields.likely_cause or "").lower()


def test_apollo_network_error_generic():
    text = "ApolloError: Network error: Connection reset"
    fields = parse_error_text(text)
    assert fields.framework == "apollo"
    assert fields.likely_cause is not None
    assert "transport" in fields.likely_cause.lower()


# ---- 2) ApolloError: GraphQL error: -------------------------


def test_apollo_graphql_error_cannot_query_field():
    text = 'ApolloError: GraphQL error: Cannot query field "foo" on type "Bar"'
    fields = parse_error_text(text)
    assert fields.framework == "apollo"
    assert fields.exception == "ApolloError"
    assert "Cannot query field" in (fields.message or "")
    assert "schema" in (fields.likely_cause or "").lower()


def test_apollo_graphql_error_syntax():
    text = "ApolloError: GraphQL error: Syntax Error: Expected Name"
    fields = parse_error_text(text)
    assert fields.framework == "apollo"
    assert "syntax" in (fields.likely_cause or "").lower()


def test_apollo_graphql_error_generic():
    text = "ApolloError: GraphQL error: Could not resolve user"
    fields = parse_error_text(text)
    assert fields.framework == "apollo"
    assert "resolver" in (fields.likely_cause or "").lower()


# ---- 3) Bracketed [GraphQLError: ...] shape -----------------


def test_bracketed_graphql_error():
    text = '[GraphQLError: Cannot query field "x" on type "Y"]'
    result = parse_apollo_error(text)
    assert result is not None
    exc, msg, _, _ = result
    assert exc == "GraphQLError"
    assert "Cannot query field" in msg


def test_bracketed_in_stack_tail():
    text = (
        "GraphQL errors: [\n"
        '  [GraphQLError: Field "users" must be of type [User]],\n'
        '  [GraphQLError: Variable "$id" of required type "ID!" was not provided]\n'
        "]"
    )
    result = parse_apollo_error(text)
    assert result is not None
    exc, msg, _, _ = result
    assert exc == "GraphQLError"
    # Should pick the FIRST bracketed match.
    assert "users" in msg.lower()


def test_bracketed_apollo_error():
    text = "[ApolloError: Network error: timeout]"
    result = parse_apollo_error(text)
    assert result is not None
    exc, msg, _, _ = result
    assert exc == "ApolloError"
    assert "Network error" in msg


def test_bracketed_in_parse_error_text():
    text = '[GraphQLError: Cannot query field "missing"]'
    fields = parse_error_text(text)
    assert fields.framework == "apollo"
    assert fields.exception == "GraphQLError"


# ---- 4) Apollo Server typed exception classes ---------------


def test_authentication_error_with_anchor():
    text = (
        "AuthenticationError: You must be logged in\n"
        "    at authMiddleware (apollo-server-express.js:42:11)"
    )
    result = parse_apollo_error(text)
    assert result is not None
    exc, msg, file_, line_ = result
    assert exc == "AuthenticationError"
    assert "logged in" in msg
    assert file_ is not None and "apollo-server-express.js" in file_
    assert line_ == 42


def test_authentication_error_without_anchor_returns_none():
    # Bare AuthenticationError without any Apollo/GraphQL anchor
    # should NOT tag as Apollo -- the class name is generic enough
    # to appear in non-Apollo codebases.
    text = "AuthenticationError: invalid token"
    result = parse_apollo_error(text)
    assert result is None


def test_forbidden_error_with_anchor():
    text = (
        "ForbiddenError: You do not have permission\n"
        "  at apolloServer.execute (/app/index.js:88:5)"
    )
    fields = parse_error_text(text)
    assert fields.framework == "apollo"
    assert fields.exception == "ForbiddenError"
    assert "permission" in (fields.likely_cause or "").lower()


def test_user_input_error_with_anchor():
    text = (
        "UserInputError: Invalid email format\n"
        "    at resolveType (graphql-resolver.ts:12:9)"
    )
    fields = parse_error_text(text)
    assert fields.framework == "apollo"
    assert fields.exception == "UserInputError"
    assert "validation" in (fields.likely_cause or "").lower()


def test_validation_error_with_apollo_anchor():
    text = (
        "ValidationError: Argument \"id\" of type ID! is required\n"
        "  at apolloServer.validate (apollo-server.js:50:1)"
    )
    fields = parse_error_text(text)
    assert fields.framework == "apollo"


def test_validation_error_without_anchor_returns_none():
    # Bare ValidationError without anchor is typically a form-library
    # error -- should NOT tag as Apollo.
    text = "ValidationError: Field is required"
    result = parse_apollo_error(text)
    assert result is None


def test_persisted_query_not_found_with_anchor():
    text = (
        "PersistedQueryNotFoundError: Could not find persisted query\n"
        "    at apollo-server.js:100:5"
    )
    fields = parse_error_text(text)
    assert fields.framework == "apollo"
    assert fields.exception == "PersistedQueryNotFoundError"
    assert "persisted" in (fields.likely_cause or "").lower()


def test_persisted_query_not_supported_with_anchor():
    text = (
        "PersistedQueryNotSupportedError: server has no APQ\n"
        "    at apolloClient.query (/app/q.js:1:1)"
    )
    fields = parse_error_text(text)
    assert fields.framework == "apollo"
    assert fields.exception == "PersistedQueryNotSupportedError"


def test_missing_field_error_with_anchor():
    text = (
        "MissingFieldError: Can't find field user\n"
        "  at apolloClient.readQuery (/app/cache.js:30:7)"
    )
    fields = parse_error_text(text)
    assert fields.framework == "apollo"
    assert "writequery" in (fields.likely_cause or "").lower()


def test_typed_error_with_usequery_anchor():
    # useQuery / useMutation hook usage anchors apollo even when the
    # error class doesn't carry the Apollo prefix.
    text = (
        "UserInputError: Email must be valid\n"
        "  at useQuery (react-app.tsx:42:11)"
    )
    fields = parse_error_text(text)
    assert fields.framework == "apollo"


def test_typed_error_with_gql_backtick_anchor():
    text = (
        "ForbiddenError: not allowed\n"
        "  const QUERY = gql`query { user { id } }`;"
    )
    fields = parse_error_text(text)
    assert fields.framework == "apollo"


# ---- 5) Cross-priority / interaction with other branches ----


def test_apollo_does_not_steal_graphql_json_response():
    # When the OCR shows the full GraphQL JSON shape, the existing
    # GraphQL JSON branch should win because it carries more
    # structure (code, locations, path).
    text = (
        '{"errors": [{"message": "Cannot query field foo",'
        '"locations": [{"line": 1, "column": 7}],'
        '"extensions": {"code": "GRAPHQL_VALIDATION_FAILED"}}]}'
    )
    fields = parse_error_text(text)
    assert fields.framework == "graphql"
    assert fields.exception == "GRAPHQL_VALIDATION_FAILED"


def test_apollo_wins_over_node_branch():
    # An ApolloError with a JS stack tail should tag as apollo, not
    # node, even though the stack tail would match _JS_AT.
    text = (
        "ApolloError: Network error: Failed to fetch\n"
        "    at QueryManager.fetchQueryByPolicy "
        "(@apollo/client.cjs.js:1234:11)"
    )
    fields = parse_error_text(text)
    assert fields.framework == "apollo"
    assert fields.file is not None
    assert fields.line == 1234


def test_bracketed_form_does_not_fire_on_jsdoc():
    # ``[some text]`` style annotations in JSDoc comments shouldn't
    # match because the bracket form requires the colon + typed name.
    text = "[NOTE]: TODO finish this resolver. See @link in docs."
    result = parse_apollo_error(text)
    assert result is None


def test_empty_text_returns_none():
    assert parse_apollo_error("") is None
    assert parse_apollo_error(None) is None  # type: ignore[arg-type]


def test_no_apollo_signature_returns_none():
    text = "Some random log line\nwithout any Apollo signals"
    assert parse_apollo_error(text) is None


def test_apollo_with_unknown_exception_still_returns_cause_none():
    # ApolloError with unrecognised inner classifier -> fall back to
    # generic transport-error hint (no inner classifier).
    text = "ApolloError: Some weird unknown error"
    fields = parse_error_text(text)
    assert fields.framework == "apollo"
    assert fields.exception == "ApolloError"
    # Generic ApolloError fallback message
    assert fields.likely_cause is not None
    assert "apollo" in fields.likely_cause.lower() or "server" in fields.likely_cause.lower()


# ---- 6) File + line extraction ------------------------------


def test_apollo_pulls_innermost_frame():
    text = (
        "ApolloError: Network error: timeout\n"
        "    at outerFn (/app/outer.ts:10:5)\n"
        "    at innerFn (/app/inner.ts:42:11)\n"
    )
    result = parse_apollo_error(text)
    assert result is not None
    _, _, file_, line_ = result
    assert file_ is not None
    assert "inner.ts" in file_
    assert line_ == 42


def test_apollo_no_frame_yields_none_file_and_line():
    text = "ApolloError: Network error: timeout"
    result = parse_apollo_error(text)
    assert result is not None
    _, _, file_, line_ = result
    assert file_ is None
    assert line_ is None


# ---- 7) Apollo with chained Apollo/GraphQL anchors ----------


def test_typed_with_apollo_dash_client_anchor():
    text = (
        "ValidationError: oops\n"
        "  at /node_modules/apollo-client/index.js:99:1"
    )
    fields = parse_error_text(text)
    assert fields.framework == "apollo"


def test_typed_with_at_apollo_scope_anchor():
    text = (
        "UserInputError: bad\n"
        "  at /node_modules/@apollo/server/dist/index.js:99:1"
    )
    fields = parse_error_text(text)
    assert fields.framework == "apollo"


def test_typed_with_apollo_server_anchor():
    text = (
        "ForbiddenError: nope\n"
        "  at ApolloServer.execute (server.ts:1:1)"
    )
    fields = parse_error_text(text)
    assert fields.framework == "apollo"


# ---- 8) Apollo cause-hint catalogue smoke ------------------


def test_apollo_authentication_error_cause():
    text = (
        "AuthenticationError: bad token\n"
        "  at apolloServer.context"
    )
    fields = parse_error_text(text)
    assert fields.likely_cause is not None
    assert "authentication" in fields.likely_cause.lower()


def test_apollo_forbidden_error_cause():
    text = (
        "ForbiddenError: blocked\n"
        "  at apolloServer.guard"
    )
    fields = parse_error_text(text)
    assert fields.likely_cause is not None
    assert "permission" in fields.likely_cause.lower()


def test_apollo_user_input_error_cause():
    text = (
        "UserInputError: invalid input\n"
        "  at apolloServer.resolve"
    )
    fields = parse_error_text(text)
    assert fields.likely_cause is not None
    assert "input validation" in fields.likely_cause.lower() or "validation" in fields.likely_cause.lower()


def test_apollo_persisted_query_cause():
    text = (
        "PersistedQueryNotFoundError: cache miss\n"
        "  at apolloClient.query"
    )
    fields = parse_error_text(text)
    assert fields.likely_cause is not None
    assert "persisted" in fields.likely_cause.lower()


def test_apollo_validation_error_cause_with_anchor():
    text = (
        "ValidationError: wrong\n"
        "  at apolloServer.validate"
    )
    fields = parse_error_text(text)
    assert fields.likely_cause is not None
    assert "schema" in fields.likely_cause.lower() or "validation" in fields.likely_cause.lower()
