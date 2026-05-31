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
    payload = _mint(c, scopes=["read:classifications", "write:classifications"])
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


def test_set_per_key_rate_limit_override_round_trip(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    payload = _mint(c, label="vip-integration", scopes=["admin"])
    key_id = payload["id"]
    # Default override is null.
    assert payload["rpm_override"] is None
    # Set a custom rpm. Tenant-scoped admin uses their own session credential.
    r = c.patch(
        f"/v1/api-keys/{key_id}/rate-limit",
        headers={"X-API-Key": "admin-key"},
        json={"rpm": 5000},
    )
    assert r.status_code == 200, r.text
    assert r.json()["key"]["rpm_override"] == 5000
    # List reflects the override.
    listing = c.get("/v1/api-keys", headers={"X-API-Key": "admin-key"}).json()
    row = next(k for k in listing["keys"] if k["id"] == key_id)
    assert row["rpm_override"] == 5000
    # Clearing works.
    r = c.patch(
        f"/v1/api-keys/{key_id}/rate-limit",
        headers={"X-API-Key": "admin-key"},
        json={"rpm": None},
    )
    assert r.status_code == 200
    assert r.json()["key"]["rpm_override"] is None


def test_rate_limit_override_isolated_across_tenants(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Create a key bound to a *different* tenant directly via the store, so
    # we can prove the tenant-a admin can't touch it via the API.
    from shotclassify_store import api_keys_store

    other, _tok = api_keys_store.create_key(
        label="foreign",
        tenant_id="tenant-b",
        scopes=["admin"],
        created_by="test",
    )
    r = c.patch(
        f"/v1/api-keys/{other.id}/rate-limit",
        headers={"X-API-Key": "admin-key"},
        json={"rpm": 99},
    )
    assert r.status_code == 404, r.text
    # The override was not applied.
    keys = api_keys_store.list_keys(tenant_id="tenant-b")
    assert next(k for k in keys if k.id == other.id).rpm_override is None


def test_read_only_key_blocked_from_history_writes(monkeypatch, tmp_path):
    """A key minted with only read:classifications cannot mutate history."""
    c = _client(monkeypatch, tmp_path)
    token = _mint(c, scopes=["read:classifications"])["token"]
    # Read works.
    assert c.get("/v1/history", headers={"X-API-Key": token}).status_code == 200
    # Delete is blocked with a clear scope error.
    r = c.delete("/v1/history/nonexistent", headers={"X-API-Key": token})
    assert r.status_code == 403, r.text
    # The role check trips first for viewers; either failure mode is fine.
    detail = r.json()["detail"]
    assert "write:classifications" in detail or "operator" in detail
    # Bulk delete is also blocked.
    r = c.post(
        "/v1/history/bulk",
        headers={"X-API-Key": token},
        json={"ids": ["abc"]},
    )
    assert r.status_code == 403


def test_write_key_cannot_read_audit_log(monkeypatch, tmp_path):
    """A write-scoped key cannot pull the audit log; needs read:audit."""
    c = _client(monkeypatch, tmp_path)
    token = _mint(c, scopes=["write:classifications"])["token"]
    r = c.get("/v1/audit", headers={"X-API-Key": token})
    assert r.status_code == 403, r.text
    detail = r.json()["detail"]
    assert "read:audit" in detail or "admin" in detail


def test_non_admin_scope_cannot_manage_api_keys(monkeypatch, tmp_path):
    """An admin-role *session* key with no scopes still works (fallback);
    a DB key without the 'admin' scope cannot mint or list keys."""
    c = _client(monkeypatch, tmp_path)
    # Mint a key with read+write but NOT admin.
    token = _mint(
        c, scopes=["read:classifications", "write:classifications"]
    )["token"]
    # Listing keys requires admin scope.
    r = c.get("/v1/api-keys", headers={"X-API-Key": token})
    assert r.status_code == 403, r.text
    # Minting another key also requires admin scope.
    r = c.post(
        "/v1/api-keys",
        headers={"X-API-Key": token},
        json={"label": "nope", "scopes": ["read:classifications"]},
    )
    assert r.status_code == 403


def test_read_only_key_blocked_from_webhook_create(monkeypatch, tmp_path):
    """Creating a webhook is an admin-scope action; a read key cannot do it."""
    c = _client(monkeypatch, tmp_path)
    token = _mint(c, scopes=["read:classifications"])["token"]
    r = c.post(
        "/v1/webhooks",
        headers={"X-API-Key": token},
        json={"url": "https://example.com/hook", "events": ["classify.completed"]},
    )
    assert r.status_code == 403, r.text


def test_rotate_key_issues_successor_and_grace_old(monkeypatch, tmp_path):
    """Rotating a key returns a new plaintext token, keeps the old one valid
    for a grace window, and after grace=0 the old key 401s immediately."""
    c = _client(monkeypatch, tmp_path)
    # Mint a working key with write scope.
    minted = _mint(c, scopes=["write:classifications", "admin"])
    old_token = minted["token"]
    old_id = minted["id"]
    # Sanity: the old token authenticates.
    r = c.get("/v1/api-keys", headers={"X-API-Key": old_token})
    assert r.status_code == 200, r.text

    # Rotate with a 24h grace.
    r = c.post(
        f"/v1/api-keys/{old_id}/rotate",
        headers={"X-API-Key": "admin-key"},
        json={"grace_minutes": 1440},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    new_token = body["new_key"]["token"]
    assert new_token.startswith("sk_live_")
    assert new_token != old_token
    assert body["new_key"]["scopes"] == body["old_key"]["scopes"]
    assert body["new_key"]["tenant_id"] == body["old_key"]["tenant_id"]
    assert body["old_key"]["expires_at"] is not None
    # Both keys work during grace.
    assert c.get("/v1/api-keys", headers={"X-API-Key": old_token}).status_code == 200
    assert c.get("/v1/api-keys", headers={"X-API-Key": new_token}).status_code == 200

    # Rotate the new key with grace=0 (immediate revoke of predecessor).
    new_id = body["new_key"]["id"]
    r = c.post(
        f"/v1/api-keys/{new_id}/rotate",
        headers={"X-API-Key": "admin-key"},
        json={"grace_minutes": 0},
    )
    assert r.status_code == 201, r.text
    # The previous "new_token" is now revoked and must 401.
    assert c.get("/v1/api-keys", headers={"X-API-Key": new_token}).status_code == 401


def test_rotate_cannot_cross_tenants(monkeypatch, tmp_path):
    """A tenant-scoped admin must not be able to rotate another tenant's key."""
    c = _client(monkeypatch, tmp_path)
    # Mint a key bound to tenant-a (the caller's tenant).
    minted_a = _mint(c, scopes=["admin"])
    key_id_a = minted_a["id"]
    # Directly create a key bound to tenant-b via the store, simulating a key
    # owned by another workspace.
    from shotclassify_store import api_keys_store
    rec_b, _tok_b = api_keys_store.create_key(
        label="tenant-b key",
        tenant_id="tenant-b",
        scopes=["admin"],
        created_by="seed",
    )
    # Tenant-a admin attempts to rotate tenant-b's key. Must be 404 (not 403)
    # so the caller cannot probe key ids across tenants.
    r = c.post(
        f"/v1/api-keys/{rec_b.id}/rotate",
        headers={"X-API-Key": "admin-key"},
        json={"grace_minutes": 60},
    )
    assert r.status_code == 404, r.text
    # Sanity: tenant-a admin CAN rotate its own key.
    r = c.post(
        f"/v1/api-keys/{key_id_a}/rotate",
        headers={"X-API-Key": "admin-key"},
        json={"grace_minutes": 60},
    )
    assert r.status_code == 201, r.text
