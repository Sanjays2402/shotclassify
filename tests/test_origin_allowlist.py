"""Per-tenant browser-origin (CORS) allowlist enforcement.

These tests prove that:

* When a tenant has no origin allowlist, requests pass regardless of the
  ``Origin`` header (or absence of one).
* When a tenant has configured an allowlist, requests carrying a non-
  matching ``Origin`` are rejected with HTTP 403 ``origin_not_allowed``.
* Server-to-server callers that omit ``Origin`` are never blocked by this
  control even when an allowlist is in force.
* One tenant's allowlist cannot leak into another tenant (no cross-tenant
  enforcement).
* Management endpoints are admin-only and validate input.
"""
from __future__ import annotations

import json

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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'origin.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    # The dev/test CORS allowlist is permissive in development; we want the
    # global CORSMiddleware to pass everything so the per-tenant layer is
    # what the assertions actually exercise.
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def test_no_origin_allowlist_allows_any_origin(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/history",
        headers={
            "X-API-Key": "acme-admin-key",
            "Origin": "https://random.example.com",
        },
    )
    assert r.status_code == 200, r.text


def test_origin_allowlist_blocks_unlisted_origin(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    put = c.put(
        "/v1/settings/security/cors-origins",
        headers={"X-API-Key": "acme-admin-key"},
        json={"origins": ["https://app.acme.example", "https://admin.acme.example:8443"]},
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["tenant_id"] == "acme"
    assert "https://app.acme.example" in body["origins"]
    assert "https://admin.acme.example:8443" in body["origins"]

    blocked = c.get(
        "/v1/history",
        headers={
            "X-API-Key": "acme-admin-key",
            "Origin": "https://evil.example.com",
        },
    )
    assert blocked.status_code == 403, blocked.text
    payload = blocked.json()
    assert payload["error"] == "origin_not_allowed"
    assert payload["tenant"] == "acme"

    allowed = c.get(
        "/v1/history",
        headers={
            "X-API-Key": "acme-admin-key",
            "Origin": "https://app.acme.example",
        },
    )
    assert allowed.status_code == 200, allowed.text


def test_origin_allowlist_does_not_block_server_to_server(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.put(
        "/v1/settings/security/cors-origins",
        headers={"X-API-Key": "acme-admin-key"},
        json={"origins": ["https://app.acme.example"]},
    ).raise_for_status()

    # No Origin header at all -> server-to-server SDK / curl. Must pass.
    r = c.get("/v1/history", headers={"X-API-Key": "acme-admin-key"})
    assert r.status_code == 200, r.text


def test_origin_allowlist_is_per_tenant(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.put(
        "/v1/settings/security/cors-origins",
        headers={"X-API-Key": "acme-admin-key"},
        json={"origins": ["https://app.acme.example"]},
    ).raise_for_status()

    # Globex has no policy -> any origin is accepted for them.
    globex = c.get(
        "/v1/history",
        headers={
            "X-API-Key": "globex-admin-key",
            "Origin": "https://app.globex.example",
        },
    )
    assert globex.status_code == 200, globex.text

    # Acme reads its own list back without leaking Globex's.
    g = c.get(
        "/v1/settings/security/cors-origins",
        headers={"X-API-Key": "acme-admin-key"},
    )
    assert g.status_code == 200
    assert g.json()["origins"] == ["https://app.acme.example"]


def test_origin_allowlist_management_is_admin_only(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/cors-origins",
        headers={"X-API-Key": "acme-op-key"},
        json={"origins": ["https://app.acme.example"]},
    )
    assert r.status_code == 403


def test_origin_allowlist_rejects_invalid_origin(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/cors-origins",
        headers={"X-API-Key": "acme-admin-key"},
        json={"origins": ["not a url"]},
    )
    assert r.status_code == 422

    r2 = c.put(
        "/v1/settings/security/cors-origins",
        headers={"X-API-Key": "acme-admin-key"},
        json={"origins": ["ftp://app.acme.example"]},
    )
    assert r2.status_code == 422

    r3 = c.put(
        "/v1/settings/security/cors-origins",
        headers={"X-API-Key": "acme-admin-key"},
        json={"origins": ["https://*.acme.example"]},
    )
    assert r3.status_code == 422


def test_origin_allowlist_normalizes_default_port(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    put = c.put(
        "/v1/settings/security/cors-origins",
        headers={"X-API-Key": "acme-admin-key"},
        json={"origins": ["HTTPS://App.Acme.Example:443/", "http://localhost:3000"]},
    )
    assert put.status_code == 200, put.text
    origins = put.json()["origins"]
    assert "https://app.acme.example" in origins
    assert "http://localhost:3000" in origins
