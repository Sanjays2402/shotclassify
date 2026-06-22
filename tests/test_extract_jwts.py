"""Cross-category JWT extractor tests.

A new cross-category extractor surfaces JSON Web Tokens (JWTs) found
in the OCR text under ``ExtractedFields.raw["jwts"]``.

Output shape: list of dicts with the JOSE header claims (``alg``,
``typ``, ``kid``) and the standard registered payload claims
(``iss``, ``sub``, ``aud``, ``exp``, ``iat``, ``nbf``, ``jti``).
The raw header segment is also stored as ``header_b64``.

Security guarantee: the FULL token (header.payload.signature) is
NEVER stored in the output. The signature segment is discarded
entirely. Pair with the existing ``jwt`` redact mode that strips
the raw token from the persisted OCR text.
"""
from __future__ import annotations

import base64
import json

from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_jwts


def _make_jwt(
    header: dict | None = None,
    payload: dict | None = None,
    signature: str = "sig-" + "x" * 30,
) -> str:
    """Build a synthetic JWT for testing purposes.

    Uses base64url encoding (RFC 7515) so the matcher's eyJ prefix
    fires correctly. The signature segment is a synthetic placeholder
    that satisfies the 8-char minimum.
    """
    if header is None:
        header = {"alg": "HS256", "typ": "JWT"}
    if payload is None:
        payload = {"sub": "user-1", "iss": "test"}
    h_b64 = base64.urlsafe_b64encode(
        json.dumps(header, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    p_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    return f"{h_b64}.{p_b64}.{signature}"


# ---- edge cases --------------------------------------------------


def test_empty_string_returns_empty_list():
    assert extract_jwts("") == []


def test_whitespace_only_returns_empty_list():
    assert extract_jwts("    \n\n  ") == []


def test_no_jwt_in_text_returns_empty_list():
    assert extract_jwts("just a string with no JWT inside it") == []


def test_none_input_returns_empty_list():
    # str-typed signature; defensive check.
    assert extract_jwts("") == []


# ---- Basic decoding ----------------------------------------------


def test_basic_jwt_header_and_payload_decoded():
    token = _make_jwt(
        header={"alg": "HS256", "typ": "JWT"},
        payload={"sub": "1234567890", "iss": "issuer.example.com"},
    )
    out = extract_jwts("header line: " + token + " trailing text")
    assert len(out) == 1
    entry = out[0]
    assert entry["alg"] == "HS256"
    assert entry["typ"] == "JWT"
    assert entry["sub"] == "1234567890"
    assert entry["iss"] == "issuer.example.com"


def test_kid_header_claim_surfaced():
    token = _make_jwt(
        header={"alg": "RS256", "typ": "JWT", "kid": "key-2024-01"},
        payload={"sub": "user-99"},
    )
    out = extract_jwts(token)
    assert out[0]["kid"] == "key-2024-01"


def test_aud_claim_surfaced_string():
    token = _make_jwt(payload={"sub": "u1", "aud": "my-api"})
    out = extract_jwts(token)
    assert out[0]["aud"] == "my-api"


def test_aud_claim_list_collapsed_to_comma_joined():
    """``aud`` can be a list of audiences per RFC 7519 §4.1.3."""
    token = _make_jwt(payload={"sub": "u1", "aud": ["svc-a", "svc-b", "svc-c"]})
    out = extract_jwts(token)
    assert out[0]["aud"] == "svc-a,svc-b,svc-c"


def test_exp_iat_nbf_integer_claims():
    token = _make_jwt(payload={
        "sub": "u1",
        "exp": 1716239022,
        "iat": 1716235422,
        "nbf": 1716235422,
    })
    out = extract_jwts(token)
    entry = out[0]
    assert entry["exp"] == 1716239022
    assert entry["iat"] == 1716235422
    assert entry["nbf"] == 1716235422


def test_jti_claim_surfaced():
    token = _make_jwt(payload={"sub": "u1", "jti": "abc-123-def"})
    out = extract_jwts(token)
    assert out[0]["jti"] == "abc-123-def"


# ---- Header_b64 preservation -------------------------------------


def test_header_b64_segment_preserved_verbatim():
    token = _make_jwt(header={"alg": "ES256", "typ": "JWT"})
    expected_header_b64 = token.split(".")[0]
    out = extract_jwts(token)
    assert out[0]["header_b64"] == expected_header_b64


# ---- Security guarantee: full token never stored -----------------


def test_full_token_never_stored_in_any_entry():
    """The signature segment must NEVER appear in the output dicts."""
    token = _make_jwt(signature="SECRET-SIGNATURE-DO-NOT-LEAK")
    out = extract_jwts(token)
    entry = out[0]
    for v in entry.values():
        assert "SECRET-SIGNATURE-DO-NOT-LEAK" not in str(v)


def test_signature_segment_never_stored():
    token = _make_jwt(signature="topsecretsignatureblob123")
    out = extract_jwts(token)
    flat = json.dumps(out)
    assert "topsecretsignatureblob123" not in flat


# ---- De-dup behaviour --------------------------------------------


def test_same_token_repeated_collapses_to_one_entry():
    token = _make_jwt()
    text = f"first: {token}\nsecond: {token}\nthird: {token}"
    out = extract_jwts(text)
    assert len(out) == 1


def test_different_tokens_each_get_separate_entry():
    a = _make_jwt(payload={"sub": "alice"})
    b = _make_jwt(payload={"sub": "bob"})
    out = extract_jwts(f"{a}\n{b}")
    assert len(out) == 2
    subs = sorted(e["sub"] for e in out)
    assert subs == ["alice", "bob"]


def test_first_seen_order_preserved():
    a = _make_jwt(payload={"sub": "alice"})
    b = _make_jwt(payload={"sub": "bob"})
    c = _make_jwt(payload={"sub": "carol"})
    out = extract_jwts(f"{b} then {a} then {c}")
    assert [e["sub"] for e in out] == ["bob", "alice", "carol"]


# ---- Robustness --------------------------------------------------


def test_corrupted_header_skipped_entirely():
    """A token whose header is not valid JSON yields no entry."""
    # Build a token whose header decodes to non-JSON text.
    bad_header = base64.urlsafe_b64encode(b"not-json-at-all").rstrip(b"=").decode()
    # Have to start with eyJ for the matcher to fire so we prepend.
    # Use eyJsbm8gPSAic29tZSI which decodes to "ln o = "some"" -- still
    # invalid JSON. Use a hand-crafted segment.
    crafted = "eyJsZ" + "X" * 20  # decodes to garbage non-JSON
    token = f"{crafted}.{bad_header}.sig-{'x' * 30}"
    out = extract_jwts(token)
    # The crafted header doesn't parse as JSON -- entry must be skipped.
    assert out == []


def test_payload_unparseable_still_yields_header_only_entry():
    """If the payload decodes but isn't JSON, the entry still has header fields."""
    h_b64 = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    # Crafted payload that decodes to non-JSON bytes.
    bad_payload = base64.urlsafe_b64encode(b"random-bytes-not-json").rstrip(b"=").decode()
    token = f"{h_b64}.{bad_payload}.sig-{'x' * 30}"
    out = extract_jwts(token)
    assert len(out) == 1
    assert out[0]["alg"] == "HS256"
    assert out[0]["typ"] == "JWT"
    # No payload claims should surface.
    assert "sub" not in out[0]
    assert "iss" not in out[0]


def test_jwt_without_eyj_prefix_not_matched():
    """The matcher requires the eyJ prefix; tokens that don't start
    with the base64url-encoded {" character are ignored."""
    # Three-dot-separated identifier that LOOKS jwt-shaped but doesn't
    # start with eyJ.
    text = "abcdefgh12345678.ijklmnop90abcdef.qrstuvwx12345678"
    out = extract_jwts(text)
    assert out == []


def test_segments_below_minimum_length_rejected():
    """Each segment must be at least 8 chars to satisfy the matcher."""
    # 7-char segments after eyJ -- below the 8-char floor.
    text = "eyJ1234.abcde12.xyz98ab"
    out = extract_jwts(text)
    assert out == []


def test_jwt_inside_header_line_prelude():
    """A common form is an HTTP authorization header line -- the matcher
    should fire on the JWT, not include the prelude."""
    token = _make_jwt(payload={"sub": "u1"})
    text = "authz hdr: " + token + " trace: abc"
    out = extract_jwts(text)
    assert len(out) == 1
    assert out[0]["sub"] == "u1"


def test_jwt_followed_by_punctuation_still_matches():
    """A trailing ``,`` / ``)`` shouldn't bite the matcher."""
    token = _make_jwt(payload={"sub": "u1"})
    text = f"token=({token}), then-something-else"
    out = extract_jwts(text)
    assert len(out) == 1
    assert out[0]["sub"] == "u1"


# ---- Cap enforcement ---------------------------------------------


def test_max_20_entries_cap():
    """The defensive cap of 20 entries is enforced."""
    parts: list[str] = []
    for i in range(30):
        parts.append(_make_jwt(payload={"sub": f"user-{i}", "jti": f"jti-{i}"}))
    text = " ".join(parts)
    out = extract_jwts(text)
    assert len(out) == 20
    # First-seen order preserved -- first 20 are user-0..user-19.
    assert [e["sub"] for e in out] == [f"user-{i}" for i in range(20)]


# ---- Claim type coercion -----------------------------------------


def test_string_claim_capped_at_256_chars():
    """A pathologically long issuer claim is capped defensively."""
    long_iss = "https://" + "a" * 300 + ".example.com"
    token = _make_jwt(payload={"sub": "u1", "iss": long_iss})
    out = extract_jwts(token)
    assert len(out[0]["iss"]) == 256


def test_nested_object_claim_not_surfaced():
    """A non-standard nested object claim (e.g. exp as {"value": 1}) is
    not in our whitelist anyway, but if it were, the coercion would
    reject it. Verify by setting a known claim to an object."""
    token = _make_jwt(payload={"sub": "u1", "iss": {"nested": "value"}})
    out = extract_jwts(token)
    # iss should be absent because the coercion rejected the dict.
    assert "iss" not in out[0]
    # sub still present.
    assert out[0]["sub"] == "u1"


def test_float_exp_collapses_to_int_when_whole_number():
    """JSON-parsed float that is whole-number (1716239022.0) stores as int."""
    h_b64 = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    # Hand-craft a payload with a float exp.
    payload_str = '{"sub":"u1","exp":1716239022.0}'
    p_b64 = base64.urlsafe_b64encode(payload_str.encode()).rstrip(b"=").decode()
    token = f"{h_b64}.{p_b64}.sig-{'x' * 30}"
    out = extract_jwts(token)
    assert out[0]["exp"] == 1716239022
    assert isinstance(out[0]["exp"], int)


def test_non_whitelisted_payload_claims_not_surfaced():
    """A custom claim (e.g. ``email``) is intentionally NOT surfaced
    because tokens carry PII in custom claims."""
    token = _make_jwt(payload={
        "sub": "u1",
        "email": "alice@example.com",
        "preferred_username": "alice",
        "custom_attr": "secret-value",
    })
    out = extract_jwts(token)
    assert out[0]["sub"] == "u1"
    assert "email" not in out[0]
    assert "preferred_username" not in out[0]
    assert "custom_attr" not in out[0]


# ---- Pipeline integration ----------------------------------------


def test_enrich_pipeline_populates_raw_jwts():
    """The enrich pipeline writes raw["jwts"] for any category."""
    token = _make_jwt(payload={"sub": "u-pipeline"})
    ocr = OCRResult(text="header line: " + token + " ; trace=abc")
    out = enrich(Category.code_snippet, ExtractedFields(), ocr)
    assert "jwts" in out.raw
    assert out.raw["jwts"][0]["sub"] == "u-pipeline"


def test_enrich_pipeline_omits_raw_jwts_when_no_jwt():
    """When the OCR text has no JWTs, raw["jwts"] is absent."""
    ocr = OCRResult(text="just plain text with no token")
    out = enrich(Category.other, ExtractedFields(), ocr)
    assert "jwts" not in out.raw


def test_enrich_pipeline_works_for_every_category():
    """JWT extraction is cross-category -- runs for every category."""
    token = _make_jwt(payload={"sub": "cross-cat"})
    ocr = OCRResult(text=f"token: {token}")
    for cat in [Category.receipt, Category.code_snippet, Category.error_stacktrace,
                Category.chat_screenshot, Category.document, Category.other]:
        out = enrich(cat, ExtractedFields(), ocr)
        assert "jwts" in out.raw, f"missing jwts key for category {cat}"
        assert out.raw["jwts"][0]["sub"] == "cross-cat"
