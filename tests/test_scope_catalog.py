"""Scope catalog and credential introspection.

Covers:

* ``GET /v1/scopes`` returns the canonical catalog, is auth-gated, and
  every scope referenced by the API key store has a catalog entry (so a
  new scope cannot ship with no documentation for auditors).
* ``GET /v1/auth/introspect`` echoes the calling credential's tenant,
  scopes, role, and credential lifecycle metadata.
* Introspection is tenant-honest: a key issued to tenant A reports
  tenant A and the cross-tenant ``X-Tenant: B`` header cannot upgrade
  it.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv("AUTH_TENANT_MAP", json.dumps({"admin-key": "tenant-a"}))
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "tenant-a")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'scopes.db'}")
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


def test_scopes_catalog_requires_auth_and_lists_every_known_scope(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/scopes")
    assert r.status_code == 401

    r = c.get("/v1/scopes", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == 1
    ids = {s["id"] for s in body["scopes"]}
    from shotclassify_store import api_keys_store

    # The store's validation allowlist and the public catalog must agree.
    assert ids == set(api_keys_store.VALID_SCOPES)
    # Each entry carries the fields the procurement review demands.
    for entry in body["scopes"]:
        assert isinstance(entry["title"], str) and entry["title"]
        assert isinstance(entry["description"], str) and entry["description"]
        assert isinstance(entry["mutating"], bool)
        assert isinstance(entry["roles"], list)


def test_introspect_reports_credential_tenant_and_scopes(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    minted = c.post(
        "/v1/api-keys",
        headers={"X-API-Key": "admin-key"},
        json={"label": "introspect-test", "scopes": ["read:classifications"], "owner_email": "ci-bot@example.com"},
    )
    assert minted.status_code == 201, minted.text
    token = minted.json()["token"]
    kid = minted.json()["id"]

    r = c.get("/v1/auth/introspect", headers={"X-API-Key": token})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active"] is True
    assert body["tenant_id"] == "tenant-a"
    assert body["scopes"] == ["read:classifications"]
    assert body["role"] == "viewer"
    assert body["credential"]["type"] == "api_key"
    assert body["credential"]["id"] == kid
    assert body["credential"]["label"] == "introspect-test"
    # scope_details hydrates against the catalog: known scope, not flagged.
    details = body["scope_details"]
    assert len(details) == 1
    assert details[0]["id"] == "read:classifications"
    assert details[0]["unknown"] is False
    assert details[0]["mutating"] is False


def test_introspect_does_not_leak_other_tenants(monkeypatch, tmp_path):
    """A key bound to tenant-a cannot be coaxed into reporting tenant-b."""
    c = _client(monkeypatch, tmp_path)
    minted = c.post(
        "/v1/api-keys",
        headers={"X-API-Key": "admin-key"},
        json={"label": "k", "scopes": ["read:classifications"], "owner_email": "ci-bot@example.com"},
    )
    token = minted.json()["token"]
    # The cross-tenant header is admin-only; for a scoped key it is
    # either ignored or rejected. Either way, the resolved tenant must
    # remain the key's bound tenant.
    r = c.get(
        "/v1/auth/introspect",
        headers={"X-API-Key": token, "X-Tenant": "tenant-b"},
    )
    # Tenant middleware may 403 the cross-tenant attempt; that is also a
    # valid "no leakage" outcome. If it does succeed, the tenant_id must
    # not have flipped.
    if r.status_code == 200:
        assert r.json()["tenant_id"] == "tenant-a"
    else:
        assert r.status_code in (400, 403)
