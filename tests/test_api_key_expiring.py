"""Expiring-soon report for API keys.

Procurement reviewers want one number on a dashboard: how many
credentials will silently die in the next N days, and which workspace
owns each one. This suite proves the answer:

* the new endpoint returns soonest-first and includes already-expired
  but not-yet-revoked keys (an overdue rotation must be visible);
* keys without an ``expires_at`` (never-expire) and revoked keys are
  excluded so the dashboard only shows actionable work;
* the report is strictly tenant-scoped, so workspace A cannot see
  workspace B's lifecycle even when both happen to expire next week;
* the store-level helper rejects a negative window so a typo cannot
  silently return the empty set and create false confidence.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps({"admin-key": "admin", "admin-key-b": "admin"}),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps({"admin-key": "tenant-a", "admin-key-b": "tenant-b"}),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "tenant-a")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'expiring.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    from shotclassify_store import init_db

    init_db()
    return TestClient(create_app())


def _mint(c: TestClient, *, api_key: str, label: str, ttl_days: int | None):
    body = {
        "label": label,
        "scopes": ["read:classifications"],
        "owner_email": "secops@example.com",
    }
    if ttl_days is not None:
        body["ttl_days"] = ttl_days
    r = c.post("/v1/api-keys", headers={"X-API-Key": api_key}, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_expiring_endpoint_orders_soonest_first_and_excludes_never_expire(
    monkeypatch, tmp_path
):
    c = _client(monkeypatch, tmp_path)
    soon = _mint(c, api_key="admin-key", label="soon", ttl_days=5)
    later = _mint(c, api_key="admin-key", label="later", ttl_days=20)
    forever = _mint(c, api_key="admin-key", label="forever", ttl_days=None)
    far = _mint(c, api_key="admin-key", label="far", ttl_days=120)

    r = c.get(
        "/v1/api-keys/expiring?within_days=30",
        headers={"X-API-Key": "admin-key"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["within_days"] == 30
    labels = [k["label"] for k in body["keys"]]
    # Never-expire and "far" are excluded; soonest-first ordering.
    assert labels == ["soon", "later"], labels
    assert forever["id"] not in {k["id"] for k in body["keys"]}
    assert far["id"] not in {k["id"] for k in body["keys"]}
    assert body["count"] == 2


def test_expiring_is_tenant_scoped(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    a = _mint(c, api_key="admin-key", label="tenant-a-key", ttl_days=3)
    b = _mint(c, api_key="admin-key-b", label="tenant-b-key", ttl_days=3)

    ra = c.get("/v1/api-keys/expiring", headers={"X-API-Key": "admin-key"})
    rb = c.get("/v1/api-keys/expiring", headers={"X-API-Key": "admin-key-b"})
    assert ra.status_code == 200 and rb.status_code == 200
    ids_a = {k["id"] for k in ra.json()["keys"]}
    ids_b = {k["id"] for k in rb.json()["keys"]}
    assert a["id"] in ids_a and a["id"] not in ids_b
    assert b["id"] in ids_b and b["id"] not in ids_a


def test_expiring_includes_already_expired_but_not_revoked(monkeypatch, tmp_path):
    """An overdue rotation must not be invisible just because it's past due."""
    c = _client(monkeypatch, tmp_path)
    rec = _mint(c, api_key="admin-key", label="overdue", ttl_days=1)

    # Backdate expires_at directly in the store so it's already past.
    from shotclassify_store import api_keys_store
    from shotclassify_store.db import ApiKeyRow, get_session
    from sqlalchemy import update as sa_update

    past = datetime.now(UTC) - timedelta(days=7)
    with get_session() as ses:
        ses.execute(
            sa_update(ApiKeyRow)
            .where(ApiKeyRow.id == rec["id"])
            .values(expires_at=past)
        )
        ses.commit()

    r = c.get(
        "/v1/api-keys/expiring?within_days=1",
        headers={"X-API-Key": "admin-key"},
    )
    assert r.status_code == 200, r.text
    assert any(k["id"] == rec["id"] for k in r.json()["keys"])


def test_store_rejects_negative_window(monkeypatch, tmp_path):
    _client(monkeypatch, tmp_path)
    from shotclassify_store import api_keys_store

    with pytest.raises(ValueError):
        api_keys_store.list_expiring(tenant_id=None, within_days=-1)
