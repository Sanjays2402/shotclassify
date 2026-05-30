"""Multi-tenant scoping: tenant_id is resolved from the caller and enforced
on the repository layer so one tenant cannot read or mutate another tenant's
classifications or audit log.
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
        json.dumps({
            "acme-op-key": "operator",
            "globex-op-key": "operator",
            "acme-view-key": "viewer",
        }),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps({
            "acme-op-key": "acme",
            "acme-view-key": "acme",
            "globex-op-key": "globex",
        }),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "default")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'tenant.db'}")
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


def _seed(client, headers, tenant_id, principal):
    """Insert a classification row directly so we can assert scoping without
    needing the full vision pipeline."""
    from shotclassify_common import (
        Category,
        Classification,
        Confidence,
        ExtractedFields,
        OCRResult,
        ProcessResult,
        RouteDecision,
    )
    from shotclassify_common.utils import new_id, utcnow
    from shotclassify_store import Repository

    rec = ProcessResult(
        id=new_id(),
        filename=f"{tenant_id}-fixture.png",
        created_at=utcnow(),
        classification=Classification(
            primary=Category.other,
            confidences=[Confidence(category=Category.other, score=1.0)],
        ),
        ocr=OCRResult(text=f"seed for {tenant_id}", language="en"),
        extracted=ExtractedFields(),
        route=RouteDecision(action="none"),
        elapsed_ms=1,
        image_url=None,
    )
    Repository().save_result(rec, image_path=None, principal=principal, tenant_id=tenant_id)
    return rec.id


def test_tenant_resolution_from_api_key(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Admin key is not in the tenant map -> falls back to default tenant.
    r = c.get("/v1/history", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200


def test_tenant_isolation_on_history(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    acme_id = _seed(c, None, "acme", "acme-op-key")
    globex_id = _seed(c, None, "globex", "globex-op-key")

    acme_resp = c.get("/v1/history", headers={"X-API-Key": "acme-op-key"})
    assert acme_resp.status_code == 200
    acme_rows = acme_resp.json()
    acme_ids = {r["id"] for r in acme_rows}
    assert acme_id in acme_ids
    assert globex_id not in acme_ids

    globex_resp = c.get("/v1/history", headers={"X-API-Key": "globex-op-key"})
    globex_ids = {r["id"] for r in globex_resp.json()}
    assert globex_id in globex_ids
    assert acme_id not in globex_ids


def test_cross_tenant_get_returns_404(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    acme_id = _seed(c, None, "acme", "acme-op-key")
    r = c.get(f"/v1/history/{acme_id}", headers={"X-API-Key": "globex-op-key"})
    assert r.status_code == 404
    r2 = c.get(f"/v1/history/{acme_id}", headers={"X-API-Key": "acme-op-key"})
    assert r2.status_code == 200


def test_cross_tenant_delete_blocked(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    acme_id = _seed(c, None, "acme", "acme-op-key")
    r = c.delete(f"/v1/history/{acme_id}", headers={"X-API-Key": "globex-op-key"})
    assert r.status_code == 404
    # Row still readable to acme.
    assert c.get(
        f"/v1/history/{acme_id}", headers={"X-API-Key": "acme-op-key"}
    ).status_code == 200


def test_history_stats_is_tenant_scoped(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed(c, None, "acme", "acme-op-key")
    _seed(c, None, "acme", "acme-op-key")
    _seed(c, None, "globex", "globex-op-key")
    a = c.get("/v1/history/stats", headers={"X-API-Key": "acme-op-key"}).json()
    g = c.get("/v1/history/stats", headers={"X-API-Key": "globex-op-key"}).json()
    assert a["count"] == 2
    assert g["count"] == 1


def test_admin_cross_tenant_header(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed(c, None, "acme", "acme-op-key")
    _seed(c, None, "globex", "globex-op-key")
    # Admin with X-Tenant: * sees everything.
    r = c.get(
        "/v1/history/stats",
        headers={"X-API-Key": "admin-key", "X-Tenant": "*"},
    )
    assert r.status_code == 200
    assert r.json()["count"] >= 2
    # Non-admin cannot use X-Tenant to escape their tenant.
    g = c.get(
        "/v1/history/stats",
        headers={"X-API-Key": "acme-op-key", "X-Tenant": "globex"},
    ).json()
    assert g["count"] == 1  # still scoped to acme, header ignored


def test_me_data_export_is_tenant_scoped(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # API key callers always have principal="api-key"; seed under that
    # principal in two tenants and confirm only the caller's tenant rows
    # come back from the GDPR export.
    _seed(c, None, "acme", "api-key")
    _seed(c, None, "globex", "api-key")
    r = c.get("/v1/me/data", headers={"X-API-Key": "acme-op-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == "acme"
    filenames = [row["filename"] for row in body["classifications"]]
    assert "acme-fixture.png" in filenames
    assert "globex-fixture.png" not in filenames
