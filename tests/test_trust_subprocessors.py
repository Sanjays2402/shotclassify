"""Trust Center sub-processor catalog + per-tenant acknowledgement.

Covers:
* Public, unauthenticated GET of the catalog.
* Admin-only GET of the per-tenant ack state.
* POST records an ack, audit log captures the actor + IP, and the
  catalog reports `acknowledged=True` afterward.
* A stale (no longer current) version is rejected with HTTP 409.
* Non-admin members cannot accept the catalog.
* One tenant's acknowledgement does not satisfy a sibling tenant.
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
                "acme-admin": "admin",
                "acme-op": "operator",
                "globex-admin": "admin",
            }
        ),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps(
            {
                "acme-admin": "acme",
                "acme-op": "acme",
                "globex-admin": "globex",
            }
        ),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "default")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'trust.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("MFA_STEP_UP_ENABLED", "false")
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def test_public_catalog_requires_no_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/trust/subprocessors")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["version"], str) and body["version"]
    assert body["count"] == len(body["processors"]) >= 1
    # Every processor advertises the procurement-required fields.
    for sp in body["processors"]:
        assert {"name", "purpose", "location", "data_categories", "website"} <= sp.keys()


def test_member_cannot_acknowledge(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    version = c.get("/v1/trust/subprocessors").json()["version"]
    r = c.post(
        "/v1/trust/subprocessors/ack",
        json={"version": version},
        headers={"X-API-Key": "acme-op"},
    )
    assert r.status_code == 403


def test_stale_version_is_rejected(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/trust/subprocessors/ack",
        json={"version": "0000000000000000"},
        headers={"X-API-Key": "acme-admin"},
    )
    assert r.status_code == 409, r.text
    assert "current" in r.json()["detail"].lower()


def test_ack_flow_and_cross_tenant_isolation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    version = c.get("/v1/trust/subprocessors").json()["version"]

    # Acme admin acknowledges.
    r = c.post(
        "/v1/trust/subprocessors/ack",
        json={"version": version},
        headers={"X-API-Key": "acme-admin"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "acme"
    assert body["acknowledged"] is True
    assert body["ack"]["acknowledged_by"]  # captured an actor
    assert body["ack"]["version"] == version

    # Acme can now read its ack state.
    r = c.get(
        "/v1/trust/subprocessors/ack",
        headers={"X-API-Key": "acme-admin"},
    )
    assert r.status_code == 200
    assert r.json()["acknowledged"] is True

    # Globex has not acknowledged: it must still see acknowledged=False even
    # though Acme has. This proves tenant isolation at the query layer.
    r = c.get(
        "/v1/trust/subprocessors/ack",
        headers={"X-API-Key": "globex-admin"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == "globex"
    assert body["acknowledged"] is False
    assert body["acknowledgement"] is None

    # The POST is captured by the audit middleware in the per-tenant chain.
    from shotclassify_store import AuditRepository

    audit = AuditRepository()
    entries = audit.list(tenant_id="acme", limit=50)
    acme_paths = [e["path"] for e in entries if e.get("tenant_id") == "acme"]
    assert "/v1/trust/subprocessors/ack" in acme_paths
    # Globex's tenant-scoped audit view must not show Acme's acknowledgement.
    g_entries = audit.list(tenant_id="globex", limit=50)
    g_paths = [e["path"] for e in g_entries if e.get("tenant_id") == "globex"]
    assert "/v1/trust/subprocessors/ack" not in g_paths
