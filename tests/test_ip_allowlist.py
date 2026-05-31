"""Per-tenant IP allowlist enforcement.

These tests prove that:

* When a tenant has no allowlist configured, requests flow unchanged.
* When an allowlist is configured, requests from a non-matching IP get a
  403 ``ip_not_allowed`` and never reach the route handler.
* Admin-only management endpoints validate input and persist the list.
* The allowlist for one tenant does not leak into another tenant.
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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'ip.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("IP_ALLOWLIST_ENABLED", "true")
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def test_no_allowlist_allows_all(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # No allowlist configured -> request passes regardless of forwarded IP.
    r = c.get(
        "/v1/history",
        headers={"X-API-Key": "acme-admin-key", "X-Forwarded-For": "203.0.113.10"},
    )
    assert r.status_code == 200


def test_allowlist_blocks_unlisted_ip(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Admin configures an allowlist that covers only 10.0.0.0/24.
    put = c.put(
        "/v1/settings/security/ip-allowlist",
        headers={"X-API-Key": "acme-admin-key"},
        json={"cidrs": ["10.0.0.0/24", "192.168.1.5"]},
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["tenant_id"] == "acme"
    assert "10.0.0.0/24" in body["cidrs"]
    assert "192.168.1.5/32" in body["cidrs"]

    # Request from a non-matching IP is rejected with 403.
    blocked = c.get(
        "/v1/history",
        headers={"X-API-Key": "acme-admin-key", "X-Forwarded-For": "203.0.113.10"},
    )
    assert blocked.status_code == 403, blocked.text
    payload = blocked.json()
    assert payload["error"] == "ip_not_allowed"
    assert payload["tenant"] == "acme"

    # Request from a matching IP is allowed.
    allowed = c.get(
        "/v1/history",
        headers={"X-API-Key": "acme-admin-key", "X-Forwarded-For": "10.0.0.42"},
    )
    assert allowed.status_code == 200, allowed.text


def test_allowlist_is_per_tenant(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Acme locks itself to 10.0.0.0/24.
    c.put(
        "/v1/settings/security/ip-allowlist",
        headers={"X-API-Key": "acme-admin-key"},
        json={"cidrs": ["10.0.0.0/24"]},
    ).raise_for_status()

    # Globex has no allowlist -> still wide open even from arbitrary IPs.
    globex = c.get(
        "/v1/history",
        headers={
            "X-API-Key": "globex-admin-key",
            "X-Forwarded-For": "203.0.113.99",
        },
    )
    assert globex.status_code == 200, globex.text

    # And Acme reading their list back sees only their own configuration.
    g = c.get(
        "/v1/settings/security/ip-allowlist",
        headers={"X-API-Key": "acme-admin-key", "X-Forwarded-For": "10.0.0.1"},
    )
    assert g.status_code == 200
    assert g.json()["cidrs"] == ["10.0.0.0/24"]


def test_allowlist_management_is_admin_only(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/ip-allowlist",
        headers={"X-API-Key": "acme-op-key"},
        json={"cidrs": ["10.0.0.0/24"]},
    )
    assert r.status_code == 403


def test_allowlist_rejects_invalid_cidr(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/ip-allowlist",
        headers={"X-API-Key": "acme-admin-key"},
        json={"cidrs": ["not-an-ip"]},
    )
    assert r.status_code == 422
    assert "invalid" in r.json()["detail"].lower()
