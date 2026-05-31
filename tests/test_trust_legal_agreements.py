"""Trust Center legal agreements: catalog, acceptance ledger, and gate.

Covers:
* Public, unauthenticated GET of the catalog (TOS / DPA / AUP).
* Admin status endpoint reports missing_required and all_required_accepted.
* POST records an acceptance, captures actor + IP, and audit-logs the call.
* A stale (no longer current) version is rejected with HTTP 409.
* Non-admin members cannot accept agreements.
* One tenant's acceptance does NOT satisfy a sibling tenant (cross-tenant
  isolation at the query layer).
* Enabling the enforcement gate while required agreements are unaccepted
  is refused (409); the gate cannot be used to lock the workspace out.
* Once enforcement is enabled, mutating /v1 requests from a non-accepted
  tenant are blocked with HTTP 451 and a structured remediation payload.
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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'legal.db'}")
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


def _accept_all(c, key, tenant_id):
    """Helper: have the admin key accept every required agreement."""
    catalog = c.get("/v1/trust/legal").json()
    for a in catalog["agreements"]:
        if not a["required"]:
            continue
        r = c.post(
            "/v1/trust/legal/accept",
            json={"agreement_id": a["id"], "version": a["version"]},
            headers={"X-API-Key": key},
        )
        assert r.status_code == 200, r.text


def test_public_catalog_requires_no_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/trust/legal")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [a["id"] for a in body["agreements"]]
    assert {"tos", "dpa", "aup"} <= set(ids)
    for a in body["agreements"]:
        assert a["body"]  # plaintext review-ready
        assert len(a["version"]) == 16  # short sha


def test_member_cannot_accept(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    catalog = c.get("/v1/trust/legal").json()
    tos = next(a for a in catalog["agreements"] if a["id"] == "tos")
    r = c.post(
        "/v1/trust/legal/accept",
        json={"agreement_id": "tos", "version": tos["version"]},
        headers={"X-API-Key": "acme-op"},
    )
    assert r.status_code == 403


def test_stale_version_is_rejected(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/trust/legal/accept",
        json={"agreement_id": "tos", "version": "deadbeefdeadbeef"},
        headers={"X-API-Key": "acme-admin"},
    )
    assert r.status_code == 409, r.text
    assert "current" in r.json()["detail"].lower()


def test_accept_flow_audit_and_cross_tenant_isolation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    catalog = c.get("/v1/trust/legal").json()
    tos = next(a for a in catalog["agreements"] if a["id"] == "tos")

    # Acme admin accepts the TOS.
    r = c.post(
        "/v1/trust/legal/accept",
        json={"agreement_id": "tos", "version": tos["version"]},
        headers={"X-API-Key": "acme-admin"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "acme"
    assert body["acceptance"]["agreement_id"] == "tos"
    assert body["acceptance"]["accepted_by"]
    # Status shows TOS accepted but DPA/AUP still missing.
    status = body["status"]
    by_id = {a["id"]: a for a in status["agreements"]}
    assert by_id["tos"]["accepted"] is True
    assert by_id["dpa"]["accepted"] is False
    assert "dpa" in status["missing_required"]

    # Globex must still see TOS unaccepted: cross-tenant isolation.
    r = c.get("/v1/trust/legal/status", headers={"X-API-Key": "globex-admin"})
    assert r.status_code == 200
    g_status = r.json()
    g_by_id = {a["id"]: a for a in g_status["agreements"]}
    assert g_by_id["tos"]["accepted"] is False
    assert g_status["all_required_accepted"] is False

    # Ledger reads are tenant-scoped: Acme sees one entry, Globex sees zero.
    a_ledger = c.get(
        "/v1/trust/legal/ledger", headers={"X-API-Key": "acme-admin"}
    ).json()
    g_ledger = c.get(
        "/v1/trust/legal/ledger", headers={"X-API-Key": "globex-admin"}
    ).json()
    assert a_ledger["count"] == 1
    assert all(e["tenant_id"] == "acme" for e in a_ledger["entries"])
    assert g_ledger["count"] == 0

    # The POST landed in Acme's audit chain but not Globex's.
    from shotclassify_store import AuditRepository

    audit = AuditRepository()
    a_paths = [
        e["path"]
        for e in audit.list(tenant_id="acme", limit=50)
        if e.get("tenant_id") == "acme"
    ]
    assert "/v1/trust/legal/accept" in a_paths
    g_paths = [
        e["path"]
        for e in audit.list(tenant_id="globex", limit=50)
        if e.get("tenant_id") == "globex"
    ]
    assert "/v1/trust/legal/accept" not in g_paths


def test_cannot_enable_enforcement_while_missing(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/trust/legal/enforcement",
        json={"enforce": True},
        headers={"X-API-Key": "acme-admin"},
    )
    assert r.status_code == 409, r.text
    assert "unaccepted" in r.json()["detail"].lower()


def test_enforcement_blocks_mutating_v1_routes(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Accept everything, then enable enforcement.
    _accept_all(c, "acme-admin", "acme")
    r = c.put(
        "/v1/trust/legal/enforcement",
        json={"enforce": True},
        headers={"X-API-Key": "acme-admin"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["enforcement"]["enforce"] is True

    # Acme is accepted: a mutating call (saved views POST) is NOT blocked
    # by the legal gate; we just confirm we don't see a 451.
    r = c.post(
        "/v1/saved-views",
        json={"name": "test", "filters": {}},
        headers={"X-API-Key": "acme-admin"},
    )
    assert r.status_code != 451, r.text

    # Globex has NOT accepted but also has enforce=off, so its writes pass
    # the legal gate (other validation may still 4xx, that is fine).
    r = c.post(
        "/v1/saved-views",
        json={"name": "g", "filters": {}},
        headers={"X-API-Key": "globex-admin"},
    )
    assert r.status_code != 451

    # Now arm Globex's gate too WITHOUT accepting -> the PUT itself is
    # refused 409. To get a 451 we need an accepted tenant whose acceptance
    # then goes stale. Simulate by enabling enforcement on Acme, then
    # bumping the catalog version via monkeypatching one agreement body.
    from shotclassify_store import legal_agreements_store as L

    original = L.CATALOG
    bumped = tuple(
        L.Agreement(
            id=a.id,
            title=a.title,
            summary=a.summary,
            body=(a.body + "\nv2-amendment") if a.id == "tos" else a.body,
            required=a.required,
        )
        for a in original
    )
    monkeypatch.setattr(L, "CATALOG", bumped)

    # Acme's TOS acceptance is now stale -> mutating /v1 calls are blocked.
    r = c.post(
        "/v1/saved-views",
        json={"name": "after-bump", "filters": {}},
        headers={"X-API-Key": "acme-admin"},
    )
    assert r.status_code == 451, r.text
    payload = r.json()
    assert payload["missing_required"] == ["tos"]
    assert "tos" in r.headers.get("x-legal-gate", "")

    # The accept endpoint itself remains reachable so the operator can
    # un-stick the workspace.
    new_tos_version = bumped[0].version()
    r = c.post(
        "/v1/trust/legal/accept",
        json={"agreement_id": "tos", "version": new_tos_version},
        headers={"X-API-Key": "acme-admin"},
    )
    assert r.status_code == 200, r.text

    # And once re-accepted, mutating routes are no longer 451.
    r = c.post(
        "/v1/saved-views",
        json={"name": "after-reaccept", "filters": {}},
        headers={"X-API-Key": "acme-admin"},
    )
    assert r.status_code != 451
