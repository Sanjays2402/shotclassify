"""Developer-secret PII redaction modes.

Covers the four new modes added in feature/autoship tick 1: ``jwt``,
``aws_access_key``, ``github_token``, ``slack_token``. Each mode is
opt-in via the per-tenant privacy policy; the patterns are designed
to fire on the canonical format each vendor publishes so that an
unrelated alphanumeric run in a screenshot is never mistakenly
redacted.
"""
from __future__ import annotations

import pytest
from shotclassify_common.redact import redact_fields, redact_text

# -- AWS access key id ----------------------------------------------------


def test_aws_access_key_redacted_when_mode_active():
    text = "config: aws_access_key_id=AKIAIOSFODNN7EXAMPLE"
    out = redact_text(text, ["aws_access_key"])
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "[REDACTED:aws_access_key]" in out


def test_aws_session_key_also_matched():
    """ASIA-prefixed temporary session tokens follow the same shape."""
    text = "ASIAQQQQRRRSSSSTTTTU"  # 4-letter prefix + 16 chars
    out = redact_text(text, ["aws_access_key"])
    assert "[REDACTED:aws_access_key]" in out


def test_aws_key_not_redacted_when_mode_inactive():
    text = "AKIAIOSFODNN7EXAMPLE"
    out = redact_text(text, ["email"])
    assert "AKIAIOSFODNN7EXAMPLE" in out


def test_aws_key_short_run_is_not_matched():
    """Strictly 20 chars total: a shorter or longer run is not an AWS
    access key id."""
    short = "AKIAEXAMPLE"  # too short
    long_run = "AKIA" + "X" * 30  # too long
    out_short = redact_text(short, ["aws_access_key"])
    out_long = redact_text(long_run, ["aws_access_key"])
    assert "AKIAEXAMPLE" in out_short
    assert "AKIA" + "X" * 30 in out_long


# -- GitHub token ---------------------------------------------------------


@pytest.mark.parametrize(
    "prefix",
    ["ghp_", "gho_", "ghu_", "ghs_", "ghr_"],
)
def test_github_classic_token_redacted(prefix):
    token = prefix + "A" * 36
    text = f"export GH_TOKEN={token}"
    out = redact_text(text, ["github_token"])
    assert token not in out
    assert "[REDACTED:github_token]" in out


def test_github_fine_grained_pat_redacted():
    """github_pat_<11alnum>_<71alnum> — the suffix is 82 alphanumeric
    chars total (no underscore split, the regex matches the whole
    82-char run)."""
    token = "github_pat_" + "A" * 82
    text = f"GH_PAT={token}"
    out = redact_text(text, ["github_token"])
    assert "[REDACTED:github_token]" in out


def test_github_random_short_string_not_redacted():
    """A 5-character alphanumeric that happens to start with `ghp_` but
    is too short is left untouched."""
    text = "ghp_abc"  # only 3 chars after prefix
    out = redact_text(text, ["github_token"])
    assert "ghp_abc" in out


# -- Slack token ----------------------------------------------------------


@pytest.mark.parametrize(
    "prefix",
    ["xoxa", "xoxb", "xoxe", "xoxo", "xoxp", "xoxr", "xoxs"],
)
def test_slack_token_redacted_for_each_prefix(prefix):
    token = f"{prefix}-12345-67890-abcdefghijklmnopqr"
    text = f"SLACK={token}"
    out = redact_text(text, ["slack_token"])
    assert token not in out
    assert "[REDACTED:slack_token]" in out


def test_slack_random_text_not_redacted():
    text = "xox is not a token"
    out = redact_text(text, ["slack_token"])
    assert "xox is not a token" in out


# -- JWT ------------------------------------------------------------------


def test_jwt_redacted():
    # Real-looking three-part JWT: header.payload.signature, each at
    # least 8 base64url chars.
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0"
        ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    text = f"Authorization: Bearer {jwt}"
    out = redact_text(text, ["jwt"])
    assert jwt not in out
    assert "[REDACTED:jwt]" in out


def test_jwt_three_dotted_short_identifiers_not_redacted():
    """Three short dot-separated identifiers (a.b.c) are not a JWT and
    must not be eaten by the redactor."""
    text = "module.submodule.attr"
    out = redact_text(text, ["jwt"])
    assert "module.submodule.attr" in out


def test_jwt_requires_eyj_prefix():
    """A three-segment base64-looking string that does NOT start with
    ``eyJ`` is left alone (could be a hash or other identifier)."""
    text = "AAAAAAAAAA.BBBBBBBBBB.CCCCCCCCCC"
    out = redact_text(text, ["jwt"])
    assert text in out


# -- Mode independence + lockstep guard ----------------------------------


def test_modes_only_fire_when_listed():
    """Activating ``email`` must not redact a JWT, and vice versa."""
    jwt = "eyJabcdefgh.payload12.signature"
    out_email = redact_text(jwt, ["email"])
    out_jwt = redact_text(jwt, ["jwt"])
    assert jwt in out_email
    assert "[REDACTED:jwt]" in out_jwt


def test_multiple_secret_modes_combine():
    text = (
        "AWS=AKIAIOSFODNN7EXAMPLE GH=ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA "
        "SLACK=xoxb-1-2-abcdefghijklmnop "
        "JWT=eyJabcdefgh.payload12.signature"
    )
    out = redact_text(
        text, ["aws_access_key", "github_token", "slack_token", "jwt"]
    )
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" not in out
    assert "xoxb-1-2-abcdefghijklmnop" not in out
    assert "eyJabcdefgh.payload12.signature" not in out
    assert "[REDACTED:aws_access_key]" in out
    assert "[REDACTED:github_token]" in out
    assert "[REDACTED:slack_token]" in out
    assert "[REDACTED:jwt]" in out


def test_redact_fields_walks_into_nested_dict():
    payload = {
        "creds": {"aws": "AKIAIOSFODNN7EXAMPLE"},
        "tokens": ["ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"],
    }
    out = redact_fields(payload, ["aws_access_key", "github_token"])
    assert out["creds"]["aws"] == "[REDACTED:aws_access_key]"
    assert out["tokens"][0] == "[REDACTED:github_token]"


def test_redact_modes_listed_in_tenant_settings_lockstep():
    """The store-layer allow-list MUST stay in lockstep with the regex
    table here. A new mode added to redact._PATTERNS without being
    added to PII_REDACT_MODES would silently never be persisted by a
    workspace admin (because set_privacy_settings rejects it)."""
    from shotclassify_store.tenant_settings import PII_REDACT_MODES

    for new_mode in ("jwt", "aws_access_key", "github_token", "slack_token"):
        assert new_mode in PII_REDACT_MODES, (
            f"{new_mode} missing from PII_REDACT_MODES allow-list"
        )
