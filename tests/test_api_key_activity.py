"""Per-API-key activity timeline.

Workspace admins doing key forensics ("what did this credential do before
we rotated it?") need a fast, tenant-scoped view of every mutating call
recorded under that key in the tamper-evident audit log.

These tests exercise the full path: mint a key, drive a few mutating
calls through it, read the activity feed, and verify cross-tenant
isolation plus RBAC enforcement.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps({"other-admin-key": "admin"}),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps({"admin-key": "tenant-a", "other-admin-key": "tenant-b"}),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "tenant-a")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'act.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("RATE_LIMIT_PER_KEY_RPM", "10000")
    monkeypatch.setenv("RATE_LIMIT_PER_WORKSPACE_RPM", "10000")
    monkeypatch.setenv("RATE_LIMIT_PER_IP_RPM", "10000")
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db, init_db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    init_db()
    return TestClient(create_app())


def _mint(client: TestClient, admin_token: str, **body) -> dict:
    body.setdefault("label", "minted")
    body.setdefault("scopes", ["read:classifications", "admin"])
    body.setdefault("owner_email", "ci-bot@example.com")
    r = client.post(
        "/v1/api-keys", headers={"X-API-Key": admin_token}, json=body
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_activity_returns_calls_made_with_the_key(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    minted = _mint(c, "admin-key", label="worker", scopes=["read:classifications", "admin"])
    token = minted["token"]
    key_id = minted["id"]

    # Drive a few mutating calls under the minted key. The PATCH below is
    # authoritative state-change wired through the standard audit middleware.
    for _ in range(3):
        r = c.patch(
            f"/v1/api-keys/{key_id}/monthly-quota",
            headers={"X-API-Key": token},
            json={"quota": None},
        )
        assert r.status_code in (200, 204), r.text

    r = c.get(
        f"/v1/api-keys/{key_id}/activity",
        headers={"X-API-Key": "admin-key"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key_id"] == key_id
    assert body["tenant_id"] == "tenant-a"
    assert body["count"] >= 3
    for event in body["events"]:
        assert event["principal"] == f"api-key:{key_id}"
        assert event["tenant_id"] == "tenant-a"
        assert event["method"] in {"POST", "PUT", "PATCH", "DELETE"}


def test_activity_is_tenant_scoped(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Key minted inside tenant-b.
    other = _mint(c, "other-admin-key", label="other")
    other_id = other["id"]

    # Tenant-a admin must not be able to read tenant-b key activity, even by
    # guessing the id. The route must return 404, not the wrong payload.
    r = c.get(
        f"/v1/api-keys/{other_id}/activity",
        headers={"X-API-Key": "admin-key"},
    )
    assert r.status_code == 404, r.text

    # The legitimate owner sees it.
    r = c.get(
        f"/v1/api-keys/{other_id}/activity",
        headers={"X-API-Key": "other-admin-key"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["tenant_id"] == "tenant-b"


def test_activity_requires_admin_scope(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Key minted without admin / read:audit scopes is not allowed to view
    # the forensic feed, even for itself.
    minted = _mint(c, "admin-key", label="limited", scopes=["read:classifications"])
    token = minted["token"]
    key_id = minted["id"]
    r = c.get(
        f"/v1/api-keys/{key_id}/activity",
        headers={"X-API-Key": token},
    )
    assert r.status_code in (401, 403), r.text
