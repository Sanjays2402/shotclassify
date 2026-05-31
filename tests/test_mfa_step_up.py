"""MFA step-up: enrollment flow and admin-mutation enforcement.

Covers the enterprise procurement requirement that destructive admin
actions cannot be triggered by a session cookie alone. A cookie-auth
admin must present a current TOTP code (proof of possession of a second
factor) before mutating, e.g., the tenant IP allowlist or routing rules.

The test:

1. Issues a server-side admin session (no MFA).
2. Confirms a destructive admin endpoint returns 401 mfa_required.
3. Enrolls TOTP for the admin, confirms enrollment, retries the action.
4. Confirms the action succeeds once the session is MFA-stamped.
"""
from __future__ import annotations

import pyotp
from fastapi.testclient import TestClient


def _reset(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'mfa.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("AUTH_ALLOWED_GITHUB_LOGIN", "admin-user")
    monkeypatch.setenv("AUTH_ROLE_MAP", '{"admin-user":"admin"}')
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


def _issue_admin_session():
    from shotclassify_store import init_db
    from services.api.app.middleware.auth import issue_session

    init_db()
    return issue_session(
        "admin-user", client_ip="127.0.0.1", user_agent="pytest", tenant_id="acme"
    )


def test_admin_mutation_requires_mfa_step_up(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    cookie, _sid = _issue_admin_session()
    jar = {"sc_session": cookie}

    # 1) Read-only admin endpoint works without MFA.
    r = c.get("/v1/settings/security/ip-allowlist", cookies=jar)
    assert r.status_code == 200, r.text

    # 2) Mutating admin endpoint is blocked with mfa_required.
    r = c.put(
        "/v1/settings/security/ip-allowlist",
        cookies=jar,
        json={"cidrs": ["10.0.0.0/8"]},
    )
    assert r.status_code == 401, r.text
    body = r.json()
    detail = body.get("detail") if isinstance(body, dict) else None
    assert isinstance(detail, dict)
    # Before enrollment: enrollment_required.
    assert detail.get("error") == "mfa_enrollment_required"

    # 3) Enroll TOTP.
    r = c.post("/v1/mfa/setup", cookies=jar)
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    totp = pyotp.TOTP(secret)
    r = c.post("/v1/mfa/verify", cookies=jar, json={"code": totp.now()})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # 4) Mutation now succeeds (verify also stamped the session).
    r = c.put(
        "/v1/settings/security/ip-allowlist",
        cookies=jar,
        json={"cidrs": ["10.0.0.0/8"]},
    )
    assert r.status_code == 200, r.text


def test_api_key_caller_bypasses_mfa(monkeypatch, tmp_path):
    """API keys are machine-to-machine; MFA is a human control."""
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/ip-allowlist",
        headers={"x-api-key": "admin-key"},
        json={"cidrs": ["192.168.0.0/16"]},
    )
    assert r.status_code == 200, r.text


def test_step_up_window_expires(monkeypatch, tmp_path):
    """A short step-up window means the next mutation needs a new code."""
    monkeypatch.setenv("MFA_STEP_UP_WINDOW_SECONDS", "60")  # minimum is 60
    c = _client(monkeypatch, tmp_path)
    cookie, sid = _issue_admin_session()
    jar = {"sc_session": cookie}

    # Enroll and confirm.
    r = c.post("/v1/mfa/setup", cookies=jar)
    secret = r.json()["secret"]
    totp = pyotp.TOTP(secret)
    c.post("/v1/mfa/verify", cookies=jar, json={"code": totp.now()})

    # Force stamp into the distant past so the freshness check fails.
    from datetime import UTC, datetime, timedelta
    from shotclassify_store import db
    from sqlalchemy import update

    with db.get_session() as s:
        s.execute(
            update(db.SessionRow)
            .where(db.SessionRow.id == sid)
            .values(mfa_verified_at=datetime.now(UTC) - timedelta(hours=1))
        )
        s.commit()

    r = c.put(
        "/v1/settings/security/ip-allowlist",
        cookies=jar,
        json={"cidrs": ["10.0.0.0/8"]},
    )
    assert r.status_code == 401
    detail = r.json().get("detail")
    assert isinstance(detail, dict)
    assert detail.get("error") == "mfa_required"

    # Re-challenge with a fresh code restores access.
    r = c.post("/v1/mfa/challenge", cookies=jar, json={"code": totp.now()})
    assert r.status_code == 200, r.text
    r = c.put(
        "/v1/settings/security/ip-allowlist",
        cookies=jar,
        json={"cidrs": ["10.0.0.0/8"]},
    )
    assert r.status_code == 200
