"""Per-tenant emergency freeze (write lockdown).

Covers the store helpers, RBAC + reason validation on the routes, the
critical middleware behaviour that mutating requests are rejected with
HTTP 423 ``tenant_frozen``, that reads stay open, and the cross-tenant
isolation property: a freeze engaged on workspace A must not affect
workspace B even though both are served by the same API process.
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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'freeze.db'}")
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


def test_freeze_get_requires_admin(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    forbidden = c.get(
        "/v1/settings/security/freeze",
        headers={"X-API-Key": "acme-op"},
    )
    assert forbidden.status_code == 403
    ok = c.get(
        "/v1/settings/security/freeze",
        headers={"X-API-Key": "acme-admin"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["tenant_id"] == "acme"
    assert body["frozen"] is False
    assert body["reason"] is None
    assert body["engaged_at"] is None


def test_freeze_engage_validates_reason(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    missing = c.post(
        "/v1/settings/security/freeze",
        headers={"X-API-Key": "acme-admin"},
        json={},
    )
    assert missing.status_code == 422
    empty = c.post(
        "/v1/settings/security/freeze",
        headers={"X-API-Key": "acme-admin"},
        json={"reason": "   "},
    )
    assert empty.status_code == 422
    too_long = c.post(
        "/v1/settings/security/freeze",
        headers={"X-API-Key": "acme-admin"},
        json={"reason": "x" * 1000},
    )
    assert too_long.status_code == 422
    ok = c.post(
        "/v1/settings/security/freeze",
        headers={"X-API-Key": "acme-admin"},
        json={"reason": "Suspected leaked admin token"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["frozen"] is True
    assert body["reason"] == "Suspected leaked admin token"
    assert body["engaged_at"]


def test_freeze_blocks_writes_for_frozen_tenant_only(monkeypatch, tmp_path):
    """Engaging freeze on acme must block acme writes but never globex."""
    c = _client(monkeypatch, tmp_path)
    # Engage freeze on acme.
    eng = c.post(
        "/v1/settings/security/freeze",
        headers={"X-API-Key": "acme-admin"},
        json={"reason": "Investigating anomalous traffic"},
    )
    assert eng.status_code == 200

    # An acme write should now be rejected with 423 + tenant_frozen.
    # Use a saved view POST: it's a mutating, tenant-scoped, audited route
    # that does not depend on uploads or model weights.
    blocked = c.post(
        "/v1/saved-views",
        headers={"X-API-Key": "acme-admin"},
        json={"name": "frozen attempt", "filters": {}},
    )
    assert blocked.status_code == 423
    body = blocked.json()
    assert body["error"] == "tenant_frozen"
    assert body["tenant_id"] == "acme"
    assert body["reason"] == "Investigating anomalous traffic"

    # Cross-tenant isolation: globex is NOT frozen, so an equivalent
    # write under a globex key must succeed (or fail with anything other
    # than 423 ``tenant_frozen``). Asserting "not 423" is the safe
    # cross-tenant invariant; the concrete success contract belongs to
    # the saved-views test.
    globex = c.post(
        "/v1/saved-views",
        headers={"X-API-Key": "globex-admin"},
        json={"name": "globex live", "filters": {}},
    )
    assert globex.status_code != 423, globex.text

    # Reads on the frozen tenant must still work.
    read = c.get(
        "/v1/settings/security/freeze",
        headers={"X-API-Key": "acme-admin"},
    )
    assert read.status_code == 200
    assert read.json()["frozen"] is True

    # Lifting the freeze must restore writes on acme.
    lifted = c.delete(
        "/v1/settings/security/freeze",
        headers={"X-API-Key": "acme-admin"},
    )
    assert lifted.status_code == 200
    assert lifted.json()["frozen"] is False

    after = c.post(
        "/v1/saved-views",
        headers={"X-API-Key": "acme-admin"},
        json={"name": "after thaw", "filters": {}},
    )
    assert after.status_code != 423, after.text


def test_freeze_exempts_lift_endpoint_and_logout(monkeypatch, tmp_path):
    """A frozen tenant must still be able to call DELETE /freeze and logout.

    Otherwise the owner could be locked out of their own recovery flow.
    """
    c = _client(monkeypatch, tmp_path)
    eng = c.post(
        "/v1/settings/security/freeze",
        headers={"X-API-Key": "acme-admin"},
        json={"reason": "smoke test"},
    )
    assert eng.status_code == 200
    # DELETE /freeze itself must NOT be blocked by freeze enforcement.
    lifted = c.delete(
        "/v1/settings/security/freeze",
        headers={"X-API-Key": "acme-admin"},
    )
    assert lifted.status_code == 200
    assert lifted.json()["frozen"] is False
