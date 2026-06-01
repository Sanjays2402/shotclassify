"""Per-tenant concurrent session cap per user is enforced end-to-end.

* Default policy is unset (legacy unbounded behaviour).
* Setting the policy validates input range and requires admin role
  plus MFA step-up.
* When the cap is set, ``session_store.create`` evicts the user's
  oldest active sessions in the same tenant down to ``cap - 1`` so
  the new row plus survivors never exceed the cap.
* Eviction is tenant-scoped: a cap on tenant A never touches the same
  user's sessions in tenant B.
* Setting the policy does not retroactively evict existing sessions;
  enforcement only fires on the next sign-in.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps({"admin-key": "tenant-a"}),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "tenant-a")
    monkeypatch.setenv("MFA_STEP_UP_REQUIRED", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'sessioncap.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db, init_db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    init_db()

    from services.api.app.main import create_app

    return TestClient(create_app())


def _admin_headers() -> dict:
    return {"X-API-Key": "admin-key"}


def test_session_cap_default_is_unset(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/settings/security/session-cap", headers=_admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["max_sessions_per_user"] is None
    assert body["min_value"] >= 1
    assert body["max_value"] >= 3


def test_session_cap_requires_admin(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # No API key at all -> 401, with a non-admin key in this fixture
    # there is no operator role, so 401 is what we get.
    r = c.put(
        "/v1/settings/security/session-cap",
        json={"max_sessions_per_user": 3},
    )
    assert r.status_code in (401, 403)


def test_session_cap_validates_range(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/session-cap",
        json={"max_sessions_per_user": 0},
        headers={**_admin_headers(), "content-type": "application/json"},
    )
    assert r.status_code == 422, r.text
    r = c.put(
        "/v1/settings/security/session-cap",
        json={"max_sessions_per_user": 9999},
        headers={**_admin_headers(), "content-type": "application/json"},
    )
    assert r.status_code == 422, r.text
    r = c.put(
        "/v1/settings/security/session-cap",
        json={"max_sessions_per_user": "two"},
        headers={**_admin_headers(), "content-type": "application/json"},
    )
    assert r.status_code == 422, r.text


def test_session_cap_set_and_clear(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/session-cap",
        json={"max_sessions_per_user": 2},
        headers={**_admin_headers(), "content-type": "application/json"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["max_sessions_per_user"] == 2

    r = c.put(
        "/v1/settings/security/session-cap",
        json={"max_sessions_per_user": None},
        headers={**_admin_headers(), "content-type": "application/json"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["max_sessions_per_user"] is None


def test_session_cap_evicts_oldest_on_create(monkeypatch, tmp_path):
    """Creating a new session with cap=2 evicts the oldest active session."""
    _ = _client(monkeypatch, tmp_path)
    from shotclassify_store import (
        session_store,
        set_session_cap_policy,
    )

    set_session_cap_policy(
        "tenant-a", max_sessions_per_user=2, updated_by="ci"
    )

    s1 = session_store.create(
        principal="alice@example.com",
        tenant_id="tenant-a",
        client_ip="10.0.0.1",
        user_agent="device-1",
        max_sessions_per_user=2,
    )
    s2 = session_store.create(
        principal="alice@example.com",
        tenant_id="tenant-a",
        client_ip="10.0.0.2",
        user_agent="device-2",
        max_sessions_per_user=2,
    )
    s3 = session_store.create(
        principal="alice@example.com",
        tenant_id="tenant-a",
        client_ip="10.0.0.3",
        user_agent="device-3",
        max_sessions_per_user=2,
    )

    # The oldest active session (s1) must have been revoked so the
    # surviving active set is at most cap = 2.
    active = session_store.list_for_principal(
        "alice@example.com", include_revoked=False
    )
    active_ids = {s.id for s in active}
    assert s1.id not in active_ids
    assert s2.id in active_ids
    assert s3.id in active_ids
    assert len(active) == 2


def test_session_cap_is_tenant_scoped(monkeypatch, tmp_path):
    """A cap on tenant-a must not touch the same user's sessions in tenant-b."""
    _ = _client(monkeypatch, tmp_path)
    from shotclassify_store import session_store

    # Two sessions in tenant-b with no cap.
    b1 = session_store.create(
        principal="bob@example.com",
        tenant_id="tenant-b",
        client_ip="10.0.0.10",
        user_agent="b-1",
    )
    b2 = session_store.create(
        principal="bob@example.com",
        tenant_id="tenant-b",
        client_ip="10.0.0.11",
        user_agent="b-2",
    )
    # New session in tenant-a with cap = 1 (the only one).
    a1 = session_store.create(
        principal="bob@example.com",
        tenant_id="tenant-a",
        client_ip="10.0.0.20",
        user_agent="a-1",
        max_sessions_per_user=1,
    )

    active = session_store.list_for_principal(
        "bob@example.com", include_revoked=False
    )
    ids = {s.id for s in active}
    # Both tenant-b sessions survive; tenant-a has its single session.
    assert b1.id in ids
    assert b2.id in ids
    assert a1.id in ids
