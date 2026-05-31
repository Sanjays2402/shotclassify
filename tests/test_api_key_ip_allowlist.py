"""Per-API-key source-IP allowlist enforcement.

Workspace admins can lock individual API keys to one or more CIDR ranges
so a leaked credential cannot be replayed from outside the deployment's
intended source IPs. These tests exercise the full path: mint a key with
an allowlist, verify the auth middleware rejects calls from outside the
allowlist with 403, accepts calls from inside, and accepts everything
once the allowlist is cleared.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv("AUTH_TENANT_MAP", json.dumps({"admin-key": "tenant-a"}))
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "tenant-a")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'keys.db'}")
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
    body.setdefault("scopes", ["read:classifications"])
    r = client.post("/v1/api-keys", headers={"X-API-Key": "admin-key"}, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_key_allowlist_blocks_outside_ip(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    payload = _mint(c, allowed_cidrs=["198.51.100.0/24"])
    token = payload["token"]
    assert payload["allowed_cidrs"] == ["198.51.100.0/24"]
    # From within the allowed range: accepted.
    r = c.get(
        "/v1/history",
        headers={"X-API-Key": token, "X-Forwarded-For": "198.51.100.42"},
    )
    assert r.status_code == 200, r.text
    # From outside the range: 403 with the structured error code so an
    # operator can distinguish 'wrong IP' from 'wrong scope' / 'revoked'.
    r = c.get(
        "/v1/history",
        headers={"X-API-Key": token, "X-Forwarded-For": "203.0.113.5"},
    )
    assert r.status_code == 403, r.text
    body = r.json()
    assert body.get("error") == "api_key_ip_not_allowed"
    assert body.get("client_ip") == "203.0.113.5"


def test_key_allowlist_empty_allows_any_ip(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    payload = _mint(c)  # no allowed_cidrs
    token = payload["token"]
    assert payload["allowed_cidrs"] == []
    # Arbitrary spoofed source IPs are all accepted because the key has
    # no allowlist configured (preserves existing behaviour).
    for ip in ("8.8.8.8", "203.0.113.99", "192.0.2.1"):
        r = c.get(
            "/v1/history",
            headers={"X-API-Key": token, "X-Forwarded-For": ip},
        )
        assert r.status_code == 200, (ip, r.text)


def test_patch_allowed_cidrs_replaces_and_clears(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    payload = _mint(c, allowed_cidrs=["10.0.0.0/8"])
    token = payload["token"]
    kid = payload["id"]
    # Replace with a different range.
    r = c.patch(
        f"/v1/api-keys/{kid}/allowed-cidrs",
        headers={"X-API-Key": "admin-key"},
        json={"allowed_cidrs": ["172.16.0.0/12", "192.168.1.7"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["key"]["allowed_cidrs"] == [
        "172.16.0.0/12",
        "192.168.1.7/32",
    ]
    # Old allowed IP no longer matches.
    r = c.get(
        "/v1/history",
        headers={"X-API-Key": token, "X-Forwarded-For": "10.1.2.3"},
    )
    assert r.status_code == 403
    # New range matches.
    r = c.get(
        "/v1/history",
        headers={"X-API-Key": token, "X-Forwarded-For": "172.16.5.5"},
    )
    assert r.status_code == 200, r.text
    # Clear: empty list means no restriction.
    r = c.patch(
        f"/v1/api-keys/{kid}/allowed-cidrs",
        headers={"X-API-Key": "admin-key"},
        json={"allowed_cidrs": []},
    )
    assert r.status_code == 200, r.text
    assert r.json()["key"]["allowed_cidrs"] == []
    r = c.get(
        "/v1/history",
        headers={"X-API-Key": token, "X-Forwarded-For": "8.8.8.8"},
    )
    assert r.status_code == 200


def test_patch_allowed_cidrs_rejects_garbage(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    payload = _mint(c)
    kid = payload["id"]
    r = c.patch(
        f"/v1/api-keys/{kid}/allowed-cidrs",
        headers={"X-API-Key": "admin-key"},
        json={"allowed_cidrs": ["not-an-ip"]},
    )
    assert r.status_code == 422, r.text


def test_create_rejects_garbage_cidr(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/api-keys",
        headers={"X-API-Key": "admin-key"},
        json={
            "label": "bad",
            "scopes": ["read:classifications"],
            "allowed_cidrs": ["999.0.0.1"],
        },
    )
    assert r.status_code == 422, r.text


def test_cross_tenant_admin_cannot_set_allowlist(monkeypatch, tmp_path):
    """A key minted under tenant-a cannot be patched by tenant-b's admin."""
    c = _client(monkeypatch, tmp_path)
    payload = _mint(c)
    kid = payload["id"]
    # Create a second tenant by writing an admin key bound to tenant-b
    # directly through the store, then attempt to patch tenant-a's key.
    from shotclassify_store import api_keys_store

    other, other_token = api_keys_store.create_key(
        label="other-admin",
        tenant_id="tenant-b",
        scopes=["admin"],
        created_by="test",
    )
    r = c.patch(
        f"/v1/api-keys/{kid}/allowed-cidrs",
        headers={"X-API-Key": other_token, "X-Tenant": "tenant-b"},
        json={"allowed_cidrs": ["10.0.0.0/8"]},
    )
    # Tenant-scoped lookup returns None, surfaced as 404 (not 403) so
    # an attacker cannot enumerate which ids exist in other tenants.
    assert r.status_code == 404, r.text
