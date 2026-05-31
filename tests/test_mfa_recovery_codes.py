"""MFA recovery (backup) codes lifecycle.

Procurement requirement: users with mandatory MFA must have a documented
self-service recovery path if their authenticator is lost. The test
proves the full round trip plus the key isolation rules:

* generation requires a confirmed second factor and a fresh step-up,
* the plaintext is shown once and never stored,
* each code works exactly once,
* consuming a code stamps the session as MFA-verified,
* one user cannot redeem another user's codes (cross-principal),
* disabling MFA wipes the entire recovery batch.
"""
from __future__ import annotations

import pyotp
from fastapi.testclient import TestClient


def _reset(monkeypatch, tmp_path, db_name="mfa-rec.db"):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/db_name}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("AUTH_ALLOWED_GITHUB_LOGIN", "")
    monkeypatch.setenv(
        "AUTH_ROLE_MAP", '{"admin-user":"admin","other-user":"admin"}'
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "acme")

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()


def _client(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    from services.api.app.main import create_app

    return TestClient(create_app())


def _enroll(client, principal):
    """Issue a session, enroll TOTP, return (cookie_jar, totp)."""
    from shotclassify_store import init_db
    from services.api.app.middleware.auth import issue_session

    init_db()
    cookie, _sid = issue_session(
        principal, client_ip="127.0.0.1", user_agent="pytest", tenant_id="acme"
    )
    jar = {"sc_session": cookie}
    r = client.post("/v1/mfa/setup", cookies=jar)
    assert r.status_code == 200, r.text
    totp = pyotp.TOTP(r.json()["secret"])
    r = client.post("/v1/mfa/verify", cookies=jar, json={"code": totp.now()})
    assert r.status_code == 200, r.text
    return jar, totp


def test_recovery_code_lifecycle(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    jar, _totp = _enroll(c, "admin-user")

    # Status starts empty.
    r = c.get("/v1/mfa/recovery-codes", cookies=jar)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "total": 0,
        "remaining": 0,
        "generated_at": None,
        "last_used_at": None,
    }

    # Generate a fresh batch (verify() already stamped the session).
    r = c.post("/v1/mfa/recovery-codes", cookies=jar)
    assert r.status_code == 200, r.text
    body = r.json()
    codes = body["codes"]
    assert len(codes) == 10
    assert len(set(codes)) == 10, "codes must be unique"
    for code in codes:
        assert "-" in code and len(code) >= 9

    # /status now reflects the batch.
    r = c.get("/v1/mfa/status", cookies=jar)
    assert r.status_code == 200
    rec = r.json()["recovery_codes"]
    assert rec["total"] == 10
    assert rec["remaining"] == 10

    # Plaintext is not stored anywhere we can read it back.
    r = c.get("/v1/mfa/recovery-codes", cookies=jar)
    assert "codes" not in r.json()

    # Force the session's MFA-verified stamp into the past so the next
    # consume_recovery_code call has to do real work to refresh it.
    from datetime import UTC, datetime, timedelta
    from shotclassify_store import db
    from sqlalchemy import update

    with db.get_session() as s:
        s.execute(
            update(db.SessionRow).values(
                mfa_verified_at=datetime.now(UTC) - timedelta(hours=2)
            )
        )
        s.commit()

    first = codes[0]
    r = c.post("/v1/mfa/recovery", cookies=jar, json={"code": first})
    assert r.status_code == 200, r.text
    assert r.json()["remaining"] == 9

    # Session is freshly stamped again.
    with db.get_session() as s:
        sess = s.query(db.SessionRow).first()
        assert sess is not None
        assert sess.mfa_verified_at is not None
        verified_at = sess.mfa_verified_at
        if verified_at.tzinfo is None:
            verified_at = verified_at.replace(tzinfo=UTC)
        assert (datetime.now(UTC) - verified_at) < timedelta(minutes=2)

    # Same code cannot be reused.
    r = c.post("/v1/mfa/recovery", cookies=jar, json={"code": first})
    assert r.status_code == 400

    # Random garbage rejected.
    r = c.post("/v1/mfa/recovery", cookies=jar, json={"code": "zzzz-zzzz"})
    assert r.status_code == 400

    # Regenerate burns the old batch.
    r = c.post("/v1/mfa/recovery-codes", cookies=jar)
    assert r.status_code == 200
    new_codes = r.json()["codes"]
    assert set(new_codes).isdisjoint(set(codes))
    # An unused code from the prior batch no longer works.
    leftover = codes[1]
    r = c.post("/v1/mfa/recovery", cookies=jar, json={"code": leftover})
    assert r.status_code == 400


def test_recovery_codes_isolated_across_principals(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    jar_a, _ = _enroll(c, "admin-user")
    jar_b, _ = _enroll(c, "other-user")

    r = c.post("/v1/mfa/recovery-codes", cookies=jar_a)
    assert r.status_code == 200
    a_code = r.json()["codes"][0]

    # User B has zero codes.
    r = c.get("/v1/mfa/recovery-codes", cookies=jar_b)
    assert r.json() == {
        "total": 0,
        "remaining": 0,
        "generated_at": None,
        "last_used_at": None,
    }

    # User B cannot redeem User A's code.
    r = c.post("/v1/mfa/recovery", cookies=jar_b, json={"code": a_code})
    assert r.status_code == 400

    # And User A's batch is untouched.
    r = c.get("/v1/mfa/recovery-codes", cookies=jar_a)
    assert r.json()["remaining"] == 10


def test_disable_mfa_wipes_recovery_codes(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    jar, totp = _enroll(c, "admin-user")

    r = c.post("/v1/mfa/recovery-codes", cookies=jar)
    assert r.status_code == 200
    leftover = r.json()["codes"][0]

    # Disable MFA (requires a current code; verify() already stamped
    # the step-up window, but disable always re-verifies the factor).
    r = c.request(
        "DELETE", "/v1/mfa", cookies=jar, json={"code": totp.now()}
    )
    assert r.status_code == 200, r.text

    # Recovery codes are gone.
    from shotclassify_store import db

    with db.get_session() as s:
        rows = (
            s.query(db.MfaRecoveryCodeRow)
            .filter(db.MfaRecoveryCodeRow.principal == "admin-user")
            .all()
        )
        assert rows == []


def test_recovery_generation_requires_step_up(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    jar, _ = _enroll(c, "admin-user")

    # Expire the session step-up stamp.
    from datetime import UTC, datetime, timedelta
    from shotclassify_store import db
    from sqlalchemy import update

    with db.get_session() as s:
        s.execute(
            update(db.SessionRow).values(
                mfa_verified_at=datetime.now(UTC) - timedelta(days=1)
            )
        )
        s.commit()

    # The middleware freshness window blocks the mutation before the
    # route even runs; either way the result is 401 mfa_required.
    r = c.post("/v1/mfa/recovery-codes", cookies=jar)
    assert r.status_code == 401, r.text


def test_api_key_caller_cannot_use_recovery_codes(monkeypatch, tmp_path):
    """Recovery is a human-only flow; API keys must not bypass MFA via it."""
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/mfa/recovery-codes", headers={"x-api-key": "admin-key"})
    assert r.status_code == 400
    r = c.post(
        "/v1/mfa/recovery",
        headers={"x-api-key": "admin-key"},
        json={"code": "abcd-efgh"},
    )
    assert r.status_code == 400
