"""Per-tenant session TTL policy.

Verifies that:

* The admin endpoints read and write the per-tenant override.
* A non-admin role cannot change the policy (RBAC).
* Setting a policy actually clips active sessions whose remaining
  lifetime exceeds the new ceiling.
* The override is per-tenant: one tenant's setting does not leak into
  another tenant.
* Invalid values return 422 instead of silently persisting.
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
                "globex-admin-key": "admin",
                "acme-op-key": "operator",
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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'sp.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def test_get_returns_global_default_when_unset(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/settings/security/sessions",
        headers={"X-API-Key": "acme-admin-key"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "acme"
    assert body["session_ttl_minutes"] is None
    assert body["default_minutes"] == body["effective_minutes"]
    assert body["min_minutes"] >= 1
    assert body["max_minutes"] > body["min_minutes"]


def test_set_and_clear_session_policy(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/sessions",
        headers={"X-API-Key": "acme-admin-key"},
        json={"session_ttl_minutes": 60},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_ttl_minutes"] == 60
    assert body["effective_minutes"] == 60
    assert body["tenant_id"] == "acme"

    g = c.get(
        "/v1/settings/security/sessions",
        headers={"X-API-Key": "acme-admin-key"},
    )
    assert g.status_code == 200
    assert g.json()["session_ttl_minutes"] == 60

    # Clearing returns to the global default.
    r2 = c.put(
        "/v1/settings/security/sessions",
        headers={"X-API-Key": "acme-admin-key"},
        json={"session_ttl_minutes": None},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["session_ttl_minutes"] is None


def test_non_admin_cannot_change_policy(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/sessions",
        headers={"X-API-Key": "acme-op-key"},
        json={"session_ttl_minutes": 60},
    )
    assert r.status_code == 403


def test_invalid_values_rejected(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Missing field.
    r = c.put(
        "/v1/settings/security/sessions",
        headers={"X-API-Key": "acme-admin-key"},
        json={},
    )
    assert r.status_code == 422

    # Below floor.
    r2 = c.put(
        "/v1/settings/security/sessions",
        headers={"X-API-Key": "acme-admin-key"},
        json={"session_ttl_minutes": 0},
    )
    assert r2.status_code == 422

    # Wrong type.
    r3 = c.put(
        "/v1/settings/security/sessions",
        headers={"X-API-Key": "acme-admin-key"},
        json={"session_ttl_minutes": "ten"},
    )
    assert r3.status_code == 422


def test_policy_is_per_tenant(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.put(
        "/v1/settings/security/sessions",
        headers={"X-API-Key": "acme-admin-key"},
        json={"session_ttl_minutes": 90},
    ).raise_for_status()

    g = c.get(
        "/v1/settings/security/sessions",
        headers={"X-API-Key": "globex-admin-key"},
    )
    assert g.status_code == 200
    body = g.json()
    assert body["tenant_id"] == "globex"
    assert body["session_ttl_minutes"] is None


def test_setting_policy_clips_active_sessions(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    # Seed an active session for tenant "acme" with a far-future expiry.
    from shotclassify_store import session_store
    from shotclassify_store.db import SessionRow, get_session, init_db

    init_db()
    info = session_store.create(
        principal="user@acme.test",
        tenant_id="acme",
        client_ip="10.0.0.1",
        user_agent="pytest",
        ttl=timedelta(days=30),
        auth_method="oauth",
    )
    original_exp = info.expires_at
    if original_exp.tzinfo is None:
        original_exp = original_exp.replace(tzinfo=UTC)

    r = c.put(
        "/v1/settings/security/sessions",
        headers={"X-API-Key": "acme-admin-key"},
        json={"session_ttl_minutes": 30},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["clipped"] >= 1

    with get_session() as s:
        row = s.get(SessionRow, info.id)
        assert row is not None
        exp = row.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        # New expiry must be at most now + 30 min + small slack.
        assert exp <= datetime.now(UTC) + timedelta(minutes=31)
        assert exp < original_exp

    # An unrelated tenant's session is not touched.
    other = session_store.create(
        principal="user@globex.test",
        tenant_id="globex",
        client_ip="10.0.0.2",
        user_agent="pytest",
        ttl=timedelta(days=30),
        auth_method="oauth",
    )
    with get_session() as s:
        row = s.get(SessionRow, other.id)
        assert row is not None
        exp = row.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        assert exp > datetime.now(UTC) + timedelta(days=29)
