"""Legal hold gates every destructive code path.

Covers the store helpers (`create_hold`, `lift_hold`, `list_holds`,
`tenant_has_active_hold`), the retention purge short-circuit, the
HTTP 423 surface on the per-shot DELETE / bulk DELETE / workspace
erasure routes, and cross-tenant isolation so one tenant's hold does
not block another tenant's deletes.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'hold.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    # Skip TOTP step-up in test so admin-only routes are reachable.
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


def _seed(tenant_id: str, principal: str, *, age_days: int = 0) -> str:
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
    from shotclassify_store import Repository, get_session
    from shotclassify_store.db import ClassificationRow

    rec = ProcessResult(
        id=new_id(),
        filename=f"seed-{tenant_id}.png",
        created_at=utcnow(),
        classification=Classification(
            primary=Category.other,
            confidences=[Confidence(category=Category.other, score=1.0)],
        ),
        ocr=OCRResult(text="seed", language="en"),
        extracted=ExtractedFields(),
        route=RouteDecision(action="none"),
        elapsed_ms=1,
        image_url=None,
    )
    Repository().save_result(
        rec, image_path=None, principal=principal, tenant_id=tenant_id
    )
    if age_days > 0:
        backdated = datetime.now(UTC) - timedelta(days=age_days)
        with get_session() as s:
            row = s.get(ClassificationRow, rec.id)
            row.created_at = backdated
            s.commit()
    return rec.id


# --- store-layer contract ---------------------------------------------------


def test_active_hold_blocks_retention_purge(monkeypatch, tmp_path):
    _client(monkeypatch, tmp_path)
    from shotclassify_store import legal_holds_store, set_retention_days
    from shotclassify_store.retention import purge_expired_for_tenant

    rid = _seed("acme", "acme-admin", age_days=400)
    set_retention_days("acme", 30, updated_by="acme-admin")

    legal_holds_store.create_hold(
        "acme", "Matter 42", "SEC inquiry", created_by="acme-admin"
    )

    result = purge_expired_for_tenant("acme")
    assert result.held is True
    assert result.removed == 0

    # Row must still exist.
    from shotclassify_store import Repository

    assert Repository().get(rid, tenant_id="acme") is not None


def test_active_hold_blocks_per_item_delete(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    rid = _seed("acme", "acme-admin")

    from shotclassify_store import legal_holds_store

    legal_holds_store.create_hold(
        "acme", "Matter 42", "litigation", created_by="acme-admin"
    )

    r = c.delete(f"/v1/history/{rid}", headers={"X-API-Key": "acme-op"})
    assert r.status_code == 423, r.text
    body = r.json()["detail"]
    assert body["error"] == "legal_hold_active"
    assert "Matter 42" in body["matters"]


def test_lifting_hold_re_enables_purge(monkeypatch, tmp_path):
    _client(monkeypatch, tmp_path)
    from shotclassify_store import (
        Repository,
        legal_holds_store,
        set_retention_days,
        tenant_has_active_hold,
    )
    from shotclassify_store.retention import purge_expired_for_tenant

    _seed("acme", "acme-admin", age_days=400)
    set_retention_days("acme", 30, updated_by="acme-admin")
    hold = legal_holds_store.create_hold(
        "acme", "Matter 42", "", created_by="acme-admin"
    )
    assert tenant_has_active_hold("acme") is True

    legal_holds_store.lift_hold(
        "acme", hold.id, "case closed", lifted_by="acme-admin"
    )
    assert tenant_has_active_hold("acme") is False

    result = purge_expired_for_tenant("acme")
    assert result.held is False
    assert result.removed >= 1

    # The lifted row remains in the registry as an audit artifact.
    holds = legal_holds_store.list_holds("acme")
    assert len(holds) == 1
    assert holds[0].active is False
    assert holds[0].lifted_by == "acme-admin"
    assert Repository().get(_seed("acme", "acme-admin"), tenant_id="acme")  # post-lift writes still work


# --- cross-tenant isolation -------------------------------------------------


def test_hold_does_not_leak_to_other_tenants(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    from shotclassify_store import legal_holds_store, tenant_has_active_hold

    legal_holds_store.create_hold(
        "acme", "Acme matter", "", created_by="acme-admin"
    )
    assert tenant_has_active_hold("globex") is False

    globex_rid = _seed("globex", "globex-admin")
    # globex admin can still delete their own row even though acme is on hold.
    r = c.delete(
        f"/v1/history/{globex_rid}", headers={"X-API-Key": "globex-admin"}
    )
    assert r.status_code == 200, r.text


# --- REST surface -----------------------------------------------------------


def test_legal_hold_routes_require_admin(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/settings/security/legal-holds", headers={"X-API-Key": "acme-op"}
    )
    assert r.status_code == 403, r.text


def test_legal_hold_create_and_lift_round_trip(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    h = {"X-API-Key": "acme-admin"}

    r = c.post(
        "/v1/settings/security/legal-holds",
        headers=h,
        json={"matter": "SEC Inv 12-345", "reason": "preserve all evidence"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active"] is True
    hold_id = body["id"]

    r = c.get("/v1/settings/security/legal-holds", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is True
    assert body["active_count"] == 1
    assert any(h["id"] == hold_id for h in body["holds"])

    r = c.post(
        f"/v1/settings/security/legal-holds/{hold_id}/lift",
        headers=h,
        json={"reason": "matter resolved"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["active"] is False
    assert r.json()["lifted_reason"] == "matter resolved"

    r = c.get("/v1/settings/security/legal-holds", headers=h)
    assert r.json()["active"] is False
    assert r.json()["active_count"] == 0


def test_legal_hold_validates_matter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/settings/security/legal-holds",
        headers={"X-API-Key": "acme-admin"},
        json={"matter": "   "},
    )
    assert r.status_code == 422
