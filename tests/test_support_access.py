"""Tenant-consented support access grants.

Asserts the rule that closes the silent cross-tenant back door: a
vendor-side admin cannot scope into another workspace via ``X-Tenant``
unless that workspace has issued an active, unexpired grant for that
admin login. With a grant, the audit log records the grant id.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    # Intentionally do NOT set AUTH_API_KEY (the legacy single-admin key)
    # because that key is treated as the deployment owner and bypasses
    # the support-access gate by design.
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps({
            "vendor-admin-key": "admin",
            "acme-admin-key": "admin",
        }),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps({"acme-admin-key": "acme"}),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "vendor")
    # Disable MFA step-up so the test exercises the grant gate only.
    monkeypatch.setenv("AUTH_MFA_REQUIRED", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'sa.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def test_admin_cross_tenant_denied_without_grant(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Vendor admin (no tenant binding) tries to scope into acme. No grant
    # exists. The middleware must refuse with 403 and a structured code.
    r = c.get(
        "/v1/history",
        headers={"X-API-Key": "vendor-admin-key", "X-Tenant": "acme"},
    )
    assert r.status_code == 403
    body = r.json()
    assert body.get("code") == "support_access_required"
    assert body.get("tenant_id") == "acme"


def test_admin_cross_tenant_allowed_with_active_grant(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Acme admin creates a grant for vendor-admin-key (which authenticates
    # as the literal principal "api-key"). Leaving allowed_admin null
    # means any vendor admin may use it.
    create = c.post(
        "/v1/support-access",
        headers={"X-API-Key": "acme-admin-key", "content-type": "application/json"},
        json={"reason": "ZD-9001 investigate failed run", "duration_minutes": 60},
    )
    assert create.status_code == 200, create.text
    grant_id = create.json()["grant"]["id"]
    assert grant_id.startswith("sag_")

    # Now the vendor admin scopes in: should succeed.
    r = c.get(
        "/v1/history",
        headers={"X-API-Key": "vendor-admin-key", "X-Tenant": "acme"},
    )
    assert r.status_code == 200, r.text

    # Revoking the grant immediately re-closes the door.
    rev = c.delete(
        f"/v1/support-access/{grant_id}",
        headers={"X-API-Key": "acme-admin-key"},
    )
    assert rev.status_code == 200, rev.text
    blocked = c.get(
        "/v1/history",
        headers={"X-API-Key": "vendor-admin-key", "X-Tenant": "acme"},
    )
    assert blocked.status_code == 403


def test_cross_tenant_use_is_audit_logged_with_grant_id(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    grant_id = c.post(
        "/v1/support-access",
        headers={"X-API-Key": "acme-admin-key", "content-type": "application/json"},
        json={"reason": "ZD-1 follow-up", "duration_minutes": 30},
    ).json()["grant"]["id"]

    # Hit a mutating cross-tenant endpoint so the audit middleware writes a
    # row. ``settings`` is admin-only and mutating; we POST a no-op-ish body
    # but only need the request to reach the audit layer (status is irrelevant
    # to the chain, only that a row is recorded with extra fields).
    c.post(
        "/v1/saved-views",
        headers={
            "X-API-Key": "vendor-admin-key",
            "X-Tenant": "acme",
            "content-type": "application/json",
        },
        json={"name": "sa-test", "filters": {}},
    )

    from shotclassify_store import AuditRepository

    rows = AuditRepository().list(tenant_id="acme", limit=20)
    tagged = [
        r
        for r in rows
        if r.get("extra") and r["extra"].get("support_access_grant_id") == grant_id
    ]
    assert tagged, f"expected an audit row tagged with grant {grant_id}, got {rows!r}"
    # The grant's use_count must have been incremented.
    from shotclassify_store import support_access_store

    g = support_access_store.get_grant(grant_id, tenant_id="acme")
    assert g is not None
    assert g.use_count >= 1
    assert g.last_used_at is not None


def test_pinned_grant_rejects_other_admin(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Pin the grant to a fictitious admin login that nobody in this test
    # presents. The vendor-admin-key principal is "api-key", which does
    # not match, so the gate must still close.
    c.post(
        "/v1/support-access",
        headers={"X-API-Key": "acme-admin-key", "content-type": "application/json"},
        json={
            "reason": "scoped to one engineer",
            "duration_minutes": 60,
            "allowed_admin": "only.this.person@vendor.example",
        },
    )
    r = c.get(
        "/v1/history",
        headers={"X-API-Key": "vendor-admin-key", "X-Tenant": "acme"},
    )
    assert r.status_code == 403
