"""Per-API-key accountable owner email (migration 0036).

Procurement reviewers consistently ask "who owns this credential and
who do we call when it leaks". This suite proves the answer:

* the public mint route refuses a body with no ``owner_email``;
* the store rejects syntactically bogus mailboxes (no @, whitespace,
  multiple @);
* a tenant-scoped admin can only see and PATCH owners on keys in
  their own tenant (cross-tenant probes return 404, not 200);
* grandfathered NULL rows surface via ``GET /v1/api-keys/unowned``
  for the admin console's access-review widget.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv("AUTH_TENANT_MAP", json.dumps({"admin-key": "tenant-a"}))
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "tenant-a")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'owners.db'}")
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


def test_mint_rejects_missing_owner_email(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/api-keys",
        headers={"X-API-Key": "admin-key"},
        json={"label": "no-owner", "scopes": ["read:classifications"]},
    )
    # FastAPI / pydantic surfaces missing required body fields as 422.
    assert r.status_code == 422, r.text


def test_mint_rejects_bogus_owner_email(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    for bad in ["not-an-email", "two@@signs.com", "spaces in@host.com", "noatsign.com"]:
        r = c.post(
            "/v1/api-keys",
            headers={"X-API-Key": "admin-key"},
            json={
                "label": "bad",
                "scopes": ["read:classifications"],
                "owner_email": bad,
            },
        )
        assert r.status_code == 422, (bad, r.text)


def test_mint_normalises_owner_email_domain_to_lowercase(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/api-keys",
        headers={"X-API-Key": "admin-key"},
        json={
            "label": "ok",
            "scopes": ["read:classifications"],
            "owner_email": "Alice@ACME.com",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["owner_email"] == "Alice@acme.com"


def test_patch_owner_round_trip_and_clear(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/api-keys",
        headers={"X-API-Key": "admin-key"},
        json={
            "label": "ok",
            "scopes": ["read:classifications"],
            "owner_email": "first@example.com",
        },
    )
    assert r.status_code == 201
    kid = r.json()["id"]

    r = c.patch(
        f"/v1/api-keys/{kid}/owner",
        headers={"X-API-Key": "admin-key"},
        json={"owner_email": "second@example.com"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["key"]["owner_email"] == "second@example.com"

    # Clearing sends the key back to the unowned bucket.
    r = c.patch(
        f"/v1/api-keys/{kid}/owner",
        headers={"X-API-Key": "admin-key"},
        json={"owner_email": None},
    )
    assert r.status_code == 200
    assert r.json()["key"]["owner_email"] is None
    unowned = c.get("/v1/api-keys/unowned", headers={"X-API-Key": "admin-key"}).json()
    assert any(k["id"] == kid for k in unowned["keys"])


def test_tenant_isolation_for_owner_patch_and_unowned_list(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    from shotclassify_store import api_keys_store

    # Seed a tenant-b key with no owner. Direct store call lets us simulate
    # the grandfathered state that motivated the migration.
    other, _ = api_keys_store.create_key(
        label="legacy",
        tenant_id="tenant-b",
        scopes=["read:classifications"],
        created_by="seed",
        owner_email=None,
    )

    # tenant-a admin must not see tenant-b's unowned keys.
    listing = c.get("/v1/api-keys/unowned", headers={"X-API-Key": "admin-key"}).json()
    assert all(k["id"] != other.id for k in listing["keys"])

    # tenant-a admin must not be able to PATCH tenant-b's key owner. 404,
    # not 200 and not 403, so the response cannot be used to probe ids.
    r = c.patch(
        f"/v1/api-keys/{other.id}/owner",
        headers={"X-API-Key": "admin-key"},
        json={"owner_email": "attacker@evil.com"},
    )
    assert r.status_code == 404, r.text


def test_rotate_carries_owner_email_to_successor(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/api-keys",
        headers={"X-API-Key": "admin-key"},
        json={
            "label": "rotate-me",
            "scopes": ["read:classifications"],
            "owner_email": "owner@example.com",
        },
    )
    assert r.status_code == 201
    kid = r.json()["id"]
    r = c.post(
        f"/v1/api-keys/{kid}/rotate",
        headers={"X-API-Key": "admin-key"},
        json={"grace_minutes": 60},
    )
    assert r.status_code == 201, r.text
    assert r.json()["new_key"]["owner_email"] == "owner@example.com"
