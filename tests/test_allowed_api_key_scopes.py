"""Per-tenant allowed API key scopes policy.

Proves the enterprise gate: when a workspace owner restricts which
scopes may be granted, every entry path (create_key, rotate, REST
POST /v1/api-keys) refuses an out-of-policy scope. Also proves the
policy is strictly tenant-scoped: the policy on workspace A never
affects key issuance in workspace B.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps({"other-admin-key": "admin"}),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps(
            {
                "admin-key": "acme",
                "other-admin-key": "globex",
            }
        ),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "acme")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'mem.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("MFA_REQUIRED_FOR_ADMIN", "false")
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


ACME = {"X-API-Key": "admin-key"}
GLOBEX = {"X-API-Key": "other-admin-key"}


def test_get_api_key_scopes_policy_defaults_to_no_policy(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/v1/settings/security/api-key-scopes", headers=ACME)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "acme"
    assert body["allowed_scopes"] == []
    assert body["max_entries"] > 0
    assert "admin" in body["available_scopes"]


def test_set_api_key_scopes_normalizes_and_persists(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.put(
        "/v1/settings/security/api-key-scopes",
        headers=ACME,
        json={"allowed_scopes": ["READ:classifications", " read:classifications "]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Lowercased, whitespace stripped, duplicates dropped.
    assert body["allowed_scopes"] == ["read:classifications"]

    r = client.get("/v1/settings/security/api-key-scopes", headers=ACME)
    assert r.json()["allowed_scopes"] == ["read:classifications"]


def test_set_api_key_scopes_rejects_unknown_scope(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.put(
        "/v1/settings/security/api-key-scopes",
        headers=ACME,
        json={"allowed_scopes": ["bogus:scope"]},
    )
    assert r.status_code == 422, r.text


def test_create_key_rejected_when_outside_policy(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    # Lock acme to read-only.
    r = client.put(
        "/v1/settings/security/api-key-scopes",
        headers=ACME,
        json={"allowed_scopes": ["read:classifications"]},
    )
    assert r.status_code == 200, r.text

    # In-policy create succeeds.
    r = client.post(
        "/v1/api-keys",
        headers=ACME,
        json={
            "label": "reader",
            "scopes": ["read:classifications"],
            "owner_email": "ops@acme.example",
        },
    )
    assert r.status_code == 201, r.text
    assert "token" in r.json()

    # Out-of-policy admin-scoped create is refused.
    r = client.post(
        "/v1/api-keys",
        headers=ACME,
        json={
            "label": "powerful",
            "scopes": ["admin"],
            "owner_email": "ops@acme.example",
        },
    )
    assert r.status_code == 422, r.text
    assert "admin" in r.text


def test_policy_is_tenant_scoped(monkeypatch, tmp_path):
    """Acme's policy must not affect globex key issuance."""
    client = _client(monkeypatch, tmp_path)
    # Acme locks scopes to read-only.
    r = client.put(
        "/v1/settings/security/api-key-scopes",
        headers=ACME,
        json={"allowed_scopes": ["read:classifications"]},
    )
    assert r.status_code == 200, r.text

    # Globex has no policy; admin-scoped create still works.
    r = client.post(
        "/v1/api-keys",
        headers=GLOBEX,
        json={
            "label": "globex-admin",
            "scopes": ["admin"],
            "owner_email": "ops@globex.example",
        },
    )
    assert r.status_code == 201, r.text

    # And globex cannot read acme's policy through its own endpoint.
    r = client.get("/v1/settings/security/api-key-scopes", headers=GLOBEX)
    assert r.status_code == 200
    assert r.json()["allowed_scopes"] == []


def test_rotate_rejected_when_policy_tightens(monkeypatch, tmp_path):
    """Tightening the policy after issuance must block the next rotation."""
    client = _client(monkeypatch, tmp_path)
    # No policy yet; mint an admin-scoped key.
    r = client.post(
        "/v1/api-keys",
        headers=ACME,
        json={
            "label": "legacy-admin",
            "scopes": ["admin"],
            "owner_email": "ops@acme.example",
        },
    )
    assert r.status_code == 201, r.text
    key_id = r.json()["id"]

    # Now tighten the policy to read-only.
    r = client.put(
        "/v1/settings/security/api-key-scopes",
        headers=ACME,
        json={"allowed_scopes": ["read:classifications"]},
    )
    assert r.status_code == 200, r.text

    # Rotating the admin-scoped key must now fail (it would inherit
    # ``admin`` which is no longer permitted).
    r = client.post(
        f"/v1/api-keys/{key_id}/rotate",
        headers=ACME,
        json={"grace_minutes": 60},
    )
    assert r.status_code == 409, r.text
    assert "admin" in r.text
