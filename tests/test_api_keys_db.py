"""DB-backed API keys: creation, scope enforcement, tenant isolation, revoke.

Exercises the full path: a workspace admin mints a key via /v1/api-keys,
that key is then accepted by the auth middleware, gated by its scopes,
hard-bound to its tenant, and can be revoked so subsequent requests with
the same plaintext token 401.
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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'keys.db'}")
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


def _mint(client: TestClient, **body) -> dict:
    body.setdefault("label", "ci")
    body.setdefault("scopes", ["write:classifications"])
    r = client.post("/v1/api-keys", headers={"X-API-Key": "admin-key"}, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_minted_key_authenticates_and_is_scoped(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    payload = _mint(c, scopes=["read:classifications"])
    token = payload["token"]
    assert token.startswith("sk_live_")
    # Read-only scope: list history works...
    r = c.get("/v1/history", headers={"X-API-Key": token})
    assert r.status_code == 200, r.text
    # ...but a write to /v1/classify is rejected for missing write scope.
    r = c.post(
        "/v1/classify",
        headers={"X-API-Key": token},
        files={"file": ("x.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert r.status_code == 403, r.text


def test_revoked_key_is_unauthorized(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    payload = _mint(c)
    token = payload["token"]
    kid = payload["id"]
    # Sanity: key works.
    assert c.get("/v1/history", headers={"X-API-Key": token}).status_code == 200
    # Revoke.
    r = c.delete(f"/v1/api-keys/{kid}", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200, r.text
    # Re-presenting the same plaintext token now 401s.
    r = c.get("/v1/history", headers={"X-API-Key": token})
    assert r.status_code == 401


def test_key_is_hard_bound_to_tenant_even_with_x_tenant_override(
    monkeypatch, tmp_path
):
    c = _client(monkeypatch, tmp_path)
    payload = _mint(c, scopes=["read:classifications"])
    token = payload["token"]
    # Even if the key's role were admin-equivalent, the DB binding pins it
    # to tenant-a; X-Tenant: tenant-b must not let it read another workspace.
    # The history listing should always be scoped to tenant-a; we assert no
    # 200 with a foreign tenant body shape leak. The simplest invariant:
    # the call still succeeds (no 500) and the resolved tenant on the
    # request state was NOT overridden. We check via the /v1/usage echo.
    r = c.get(
        "/v1/me/usage",
        headers={"X-API-Key": token, "X-Tenant": "tenant-b"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # The usage endpoint reports the resolved tenant.
    assert body.get("tenant_id") == "tenant-a", body


def test_cannot_revoke_another_tenants_key(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Mint a key for tenant-a (caller's tenant).
    payload = _mint(c)
    kid = payload["id"]
    # Force-create a row in tenant-b directly through the store, then try to
    # revoke it as a tenant-a admin. Should 404, not silently succeed.
    from shotclassify_store import api_keys_store

    other, _other_token = api_keys_store.create_key(
        label="other",
        tenant_id="tenant-b",
        scopes=["read:classifications"],
        created_by="seed",
    )
    r = c.delete(f"/v1/api-keys/{other.id}", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 404, r.text
    # Our own key still works.
    r = c.delete(f"/v1/api-keys/{kid}", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200
