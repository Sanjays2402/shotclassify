"""Workspace-wide MFA enrolment policy.

Covers the enterprise procurement requirement that a workspace owner
can force every member to have a confirmed second factor before they
can use the API or dashboard, beyond the per-action step-up that
already gates admin mutations.

These tests prove four properties:

1. With the policy off, a member with no MFA can call any /v1 route
   they have role for (existing behaviour, unchanged).
2. With the policy on, the same member is rejected with HTTP 403 and
   ``error: mfa_enrollment_required`` on every protected route.
3. Even with the policy on, the MFA enrolment surface stays reachable
   (``/v1/mfa/*``, ``/v1/me``, ``/v1/sessions``) so the member can
   actually complete enrolment.
4. API-key callers (machine integrations) are unaffected.
"""
from __future__ import annotations

import pyotp
from fastapi.testclient import TestClient


def _reset(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'mfa_policy.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("AUTH_ALLOWED_GITHUB_LOGIN", "")
    monkeypatch.setenv(
        "AUTH_ROLE_MAP",
        '{"admin-user":"admin","member-user":"operator"}',
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


def _issue_session(principal: str, tenant_id: str = "acme"):
    from services.api.app.middleware.auth import issue_session
    from shotclassify_store import init_db

    init_db()
    return issue_session(
        principal, client_ip="127.0.0.1", user_agent="pytest", tenant_id=tenant_id
    )


def _enrol(c: TestClient, jar: dict) -> str:
    r = c.post("/v1/mfa/setup", cookies=jar)
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    totp = pyotp.TOTP(secret)
    r = c.post("/v1/mfa/verify", cookies=jar, json={"code": totp.now()})
    assert r.status_code == 200, r.text
    return secret


def _enable_policy(c: TestClient, admin_jar: dict, admin_secret: str):
    """Helper: turn the policy on as ``admin-user``.

    Requires admin to already have a confirmed credential and a fresh
    step-up, which mirrors the production failure mode (the API refuses
    to enable the policy from a non-MFA admin session).
    """
    totp = pyotp.TOTP(admin_secret)
    # Re-stamp the step-up window because the test runs fast enough that
    # the verify call above might be on the boundary.
    c.post("/v1/mfa/verify", cookies=admin_jar, json={"code": totp.now()})
    r = c.put(
        "/v1/settings/security/mfa-policy",
        cookies=admin_jar,
        json={"required": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["required"] is True


def test_policy_off_allows_member_without_mfa(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    cookie, _ = _issue_session("member-user")
    jar = {"sc_session": cookie}
    r = c.get("/v1/me/usage", cookies=jar)
    assert r.status_code == 200, r.text
    r = c.get("/v1/sessions", cookies=jar)
    assert r.status_code == 200, r.text


def test_policy_on_blocks_member_without_mfa(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    admin_cookie, _ = _issue_session("admin-user")
    admin_jar = {"sc_session": admin_cookie}
    admin_secret = _enrol(c, admin_jar)
    _enable_policy(c, admin_jar, admin_secret)

    member_cookie, _ = _issue_session("member-user")
    mjar = {"sc_session": member_cookie}

    # Protected route: rejected with structured error.
    r = c.get("/v1/history", cookies=mjar)
    assert r.status_code == 403, r.text
    body = r.json()
    # Body may be either the JSONResponse {"error": ..., "detail": ...}
    # or wrapped under "detail" depending on whether the middleware or a
    # route raised. Accept either shape.
    detail = body.get("detail") if isinstance(body, dict) else None
    err = body.get("error") if isinstance(body, dict) else None
    if not err and isinstance(detail, dict):
        err = detail.get("error")
    assert err == "mfa_enrollment_required", body


def test_policy_on_still_allows_enrolment_paths(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    admin_cookie, _ = _issue_session("admin-user")
    admin_jar = {"sc_session": admin_cookie}
    admin_secret = _enrol(c, admin_jar)
    _enable_policy(c, admin_jar, admin_secret)

    member_cookie, _ = _issue_session("member-user")
    mjar = {"sc_session": member_cookie}

    # /v1/me/*, /v1/sessions, /v1/mfa/* all stay reachable so the member
    # can see their own data, list devices, and complete enrolment.
    assert c.get("/v1/me/usage", cookies=mjar).status_code == 200
    assert c.get("/v1/sessions", cookies=mjar).status_code == 200
    r = c.post("/v1/mfa/setup", cookies=mjar)
    assert r.status_code == 200, r.text

    # After enrolment they regain access to the rest of the API.
    secret = r.json()["secret"]
    totp = pyotp.TOTP(secret)
    r = c.post("/v1/mfa/verify", cookies=mjar, json={"code": totp.now()})
    assert r.status_code == 200, r.text
    r = c.get("/v1/history", cookies=mjar)
    assert r.status_code == 200, r.text


def test_policy_on_does_not_affect_api_key_callers(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    admin_cookie, _ = _issue_session("admin-user")
    admin_jar = {"sc_session": admin_cookie}
    admin_secret = _enrol(c, admin_jar)
    _enable_policy(c, admin_jar, admin_secret)

    # Machine integration: scoped API key, no MFA possible.
    r = c.get("/v1/me/usage", headers={"x-api-key": "admin-key"})
    assert r.status_code == 200, r.text


def test_enable_policy_requires_admin_to_have_mfa(monkeypatch, tmp_path):
    """A non-MFA admin cannot enable the workspace requirement and
    lock themselves out."""
    c = _client(monkeypatch, tmp_path)
    admin_cookie, _ = _issue_session("admin-user")
    admin_jar = {"sc_session": admin_cookie}

    r = c.put(
        "/v1/settings/security/mfa-policy",
        cookies=admin_jar,
        json={"required": True},
    )
    # Step-up middleware rejects first because the admin has no
    # confirmed credential yet. This is the lockout guard.
    assert r.status_code == 401, r.text
    body = r.json()
    detail = body.get("detail") if isinstance(body, dict) else None
    err = (detail or {}).get("error") if isinstance(detail, dict) else None
    assert err == "mfa_enrollment_required", body
