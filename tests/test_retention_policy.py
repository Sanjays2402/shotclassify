"""Per-tenant data retention policy.

Covers the store helpers, cross-tenant isolation of purge, the API
routes (read, write, manual-run) including RBAC, and that the policy
cannot touch rows belonging to a different tenant even when the
caller has admin role.
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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'ret.db'}")
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


def _seed_old(tenant_id: str, principal: str, age_days: int, filename: str) -> str:
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
        filename=filename,
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
    Repository().save_result(rec, image_path=None, principal=principal, tenant_id=tenant_id)
    # Backdate the row so it falls outside the retention window.
    if age_days > 0:
        backdated = datetime.now(UTC) - timedelta(days=age_days)
        with get_session() as s:
            row = s.get(ClassificationRow, rec.id)
            row.created_at = backdated
            s.commit()
    return rec.id


def test_retention_get_requires_admin(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/settings/security/retention", headers={"X-API-Key": "acme-op"}
    )
    assert r.status_code == 403
    r2 = c.get(
        "/v1/settings/security/retention", headers={"X-API-Key": "acme-admin"}
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["tenant_id"] == "acme"
    assert body["enabled"] is False
    assert body["retention_days"] is None


def test_retention_put_validates_input(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    bad = c.put(
        "/v1/settings/security/retention",
        headers={"X-API-Key": "acme-admin"},
        json={"retention_days": -5},
    )
    assert bad.status_code == 422
    too_big = c.put(
        "/v1/settings/security/retention",
        headers={"X-API-Key": "acme-admin"},
        json={"retention_days": 99999},
    )
    assert too_big.status_code == 422
    ok = c.put(
        "/v1/settings/security/retention",
        headers={"X-API-Key": "acme-admin"},
        json={"retention_days": 30},
    )
    assert ok.status_code == 200
    assert ok.json()["retention_days"] == 30
    # Round-trip
    again = c.get(
        "/v1/settings/security/retention", headers={"X-API-Key": "acme-admin"}
    )
    assert again.json()["retention_days"] == 30


def test_retention_purge_is_tenant_scoped(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    acme_old = _seed_old("acme", "api-key", age_days=60, filename="acme-old.png")
    acme_new = _seed_old("acme", "api-key", age_days=1, filename="acme-new.png")
    globex_old = _seed_old(
        "globex", "api-key", age_days=60, filename="globex-old.png"
    )

    # Acme sets a 30-day policy; globex has no policy at all.
    r = c.put(
        "/v1/settings/security/retention",
        headers={"X-API-Key": "acme-admin"},
        json={"retention_days": 30},
    )
    assert r.status_code == 200

    # Acme admin runs an immediate purge.
    run = c.post(
        "/v1/settings/security/retention/run",
        headers={"X-API-Key": "acme-admin"},
    )
    assert run.status_code == 200
    payload = run.json()
    assert payload["tenant_id"] == "acme"
    assert payload["removed"] == 1

    # Acme: old row purged, new row kept.
    from shotclassify_store import Repository

    repo = Repository()
    assert repo.get(acme_old, tenant_id="acme") is None
    assert repo.get(acme_new, tenant_id="acme") is not None
    # Globex row untouched even though it is older than acme's window.
    assert repo.get(globex_old, tenant_id="globex") is not None

    # Globex with no policy: manual run is a no-op.
    run2 = c.post(
        "/v1/settings/security/retention/run",
        headers={"X-API-Key": "globex-admin"},
    )
    assert run2.status_code == 200
    assert run2.json()["removed"] == 0
    assert repo.get(globex_old, tenant_id="globex") is not None


def test_retention_disable_sets_null(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.put(
        "/v1/settings/security/retention",
        headers={"X-API-Key": "acme-admin"},
        json={"retention_days": 30},
    )
    r = c.put(
        "/v1/settings/security/retention",
        headers={"X-API-Key": "acme-admin"},
        json={"retention_days": None},
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert r.json()["retention_days"] is None
