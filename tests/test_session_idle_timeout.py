"""Per-tenant session idle (inactivity) timeout.

Verifies the end-to-end SOC2 CC6.1 path:

* Admin can read and write the per-tenant idle policy.
* Non-admins cannot mutate it.
* Out-of-range values 422 instead of persisting.
* An authenticated session that has been idle longer than the policy
  is revoked on the next request and the caller falls back to 401.
* Tenants are isolated: one tenant's idle policy does not bleed into
  another tenant's sessions.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps(
            {
                "acme-admin-key": "admin",
                "acme-op-key": "operator",
                "globex-admin-key": "admin",
            }
        ),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps(
            {
                "acme-admin-key": "acme",
                "acme-op-key": "acme",
                "globex-admin-key": "globex",
            }
        ),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "default")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'idle.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))
    monkeypatch.setenv("APP_SECRET_KEY", "x" * 32)

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def test_idle_policy_round_trip_and_isolation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    # MFA step-up required for the PUT. Enroll + confirm for the admin
    # principal exactly the way the existing session_policy test does:
    # API-key callers are exempt from MFA step-up because step-up only
    # gates cookie sessions; api-key admins satisfy the dependency.
    r = c.get(
        "/v1/settings/security/sessions",
        headers={"X-API-Key": "acme-admin-key"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_idle_minutes"] is None
    assert body["idle_min_minutes"] >= 1
    assert body["idle_max_minutes"] > body["idle_min_minutes"]

    # Set a 15-minute idle policy for acme.
    r = c.put(
        "/v1/settings/security/sessions/idle",
        json={"session_idle_minutes": 15},
        headers={"X-API-Key": "acme-admin-key"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["session_idle_minutes"] == 15

    # Non-admin cannot mutate.
    r = c.put(
        "/v1/settings/security/sessions/idle",
        json={"session_idle_minutes": 30},
        headers={"X-API-Key": "acme-op-key"},
    )
    assert r.status_code == 403, r.text

    # Out-of-range rejected.
    r = c.put(
        "/v1/settings/security/sessions/idle",
        json={"session_idle_minutes": 0},
        headers={"X-API-Key": "acme-admin-key"},
    )
    assert r.status_code == 422, r.text

    # Tenants are isolated.
    r = c.get(
        "/v1/settings/security/sessions",
        headers={"X-API-Key": "globex-admin-key"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["session_idle_minutes"] is None

    # Clear with null.
    r = c.put(
        "/v1/settings/security/sessions/idle",
        json={"session_idle_minutes": None},
        headers={"X-API-Key": "acme-admin-key"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["session_idle_minutes"] is None


def test_idle_timeout_revokes_stale_session(monkeypatch, tmp_path):
    """A cookie session that has been idle past the policy is revoked
    on the next request: the auth middleware treats it as if the cookie
    had been signed out."""
    c = _client(monkeypatch, tmp_path)

    # Configure 5-minute idle policy on acme.
    r = c.put(
        "/v1/settings/security/sessions/idle",
        json={"session_idle_minutes": 5},
        headers={"X-API-Key": "acme-admin-key"},
    )
    assert r.status_code == 200, r.text

    # Mint a session row for an acme cookie principal directly.
    from shotclassify_store import db, session_store
    from services.api.app.middleware.auth import _signer

    info = session_store.create(
        principal="alice@example.com",
        tenant_id="acme",
        client_ip="127.0.0.1",
        user_agent="pytest",
    )
    cookie = _signer().dumps({"sid": info.id})

    # Backdate last_seen_at well past the 5-minute idle window.
    with db.get_session() as s:
        row = s.get(db.SessionRow, info.id)
        row.last_seen_at = datetime.now(UTC) - timedelta(minutes=30)
        s.commit()

    # Next authenticated request must be rejected because the session
    # was idle past the policy. /v1/me requires auth; with the stale
    # cookie and no API key we expect 401.
    r = c.get("/v1/me", cookies={"sc_session": cookie})
    assert r.status_code == 401, r.text

    # And the row is now revoked.
    refreshed = session_store.get(info.id)
    assert refreshed is not None
    assert refreshed.revoked_at is not None


def test_idle_policy_does_not_affect_other_tenants(monkeypatch, tmp_path):
    """An acme idle policy must not revoke a globex session."""
    c = _client(monkeypatch, tmp_path)

    r = c.put(
        "/v1/settings/security/sessions/idle",
        json={"session_idle_minutes": 5},
        headers={"X-API-Key": "acme-admin-key"},
    )
    assert r.status_code == 200, r.text

    from shotclassify_store import db, session_store
    from services.api.app.middleware.auth import _signer

    info = session_store.create(
        principal="bob@globex.example.com",
        tenant_id="globex",
        client_ip="127.0.0.1",
        user_agent="pytest",
    )
    cookie = _signer().dumps({"sid": info.id})

    with db.get_session() as s:
        row = s.get(db.SessionRow, info.id)
        row.last_seen_at = datetime.now(UTC) - timedelta(minutes=30)
        s.commit()

    # globex has no idle policy, so the stale cookie still authenticates.
    r = c.get("/v1/me", cookies={"sc_session": cookie})
    # /v1/me may 200 or 404 depending on principal mapping; the point is
    # it must not be the 401 we get for the acme-idle case above.
    assert r.status_code != 401, r.text
    refreshed = session_store.get(info.id)
    assert refreshed is not None
    assert refreshed.revoked_at is None
