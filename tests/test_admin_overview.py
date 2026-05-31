"""Admin overview endpoint: RBAC and tenant scoping."""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    # Provision a viewer-scoped key via AUTH_API_KEYS so we can prove the
    # admin route denies non-admins.
    monkeypatch.setenv("AUTH_API_KEYS", '{"viewer-key": "viewer"}')
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'admin.db'}")
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


def test_admin_overview_requires_admin_role(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/admin/overview", headers={"X-API-Key": "viewer-key"})
    assert r.status_code == 403, r.text


def test_admin_overview_unauthenticated_is_401(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/admin/overview")
    assert r.status_code == 401, r.text


def test_admin_overview_returns_tenant_scoped_summary(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/admin/overview", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) >= {
        "tenant_id",
        "members",
        "invitations",
        "sessions",
        "api_keys",
        "audit",
        "classifications",
    }
    assert isinstance(body["members"]["total"], int)
    assert isinstance(body["sessions"]["active"], int)
    assert isinstance(body["api_keys"]["active"], int)
    assert isinstance(body["classifications"]["total"], int)


def test_admin_overview_does_not_leak_other_tenants(monkeypatch, tmp_path):
    """An admin keyed to tenant A must never see tenant B's rows.

    Seeds a classification under tenant B directly through the repository,
    then confirms the admin overview for tenant A shows zero classifications.
    """
    c = _client(monkeypatch, tmp_path)
    # Trigger lifespan startup (init_db) by hitting healthz first.
    c.get("/healthz")
    from datetime import UTC, datetime
    from shotclassify_store import ClassificationRow
    from shotclassify_store.db import get_session

    with get_session() as s:
        s.merge(
            ClassificationRow(
                id="other-1",
                filename="seed.png",
                image_path=None,
                created_at=datetime.now(UTC),
                primary_category="other",
                confidence=0.9,
                ocr_text="",
                ocr_lang="",
                extracted={},
                route={},
                elapsed_ms=0,
                principal="someone-else",
                tenant_id="tenant-b",
            )
        )
        s.commit()

    # Default tenant for the admin key is "default" (or whatever the deployment
    # resolves); whatever it is, it must not equal "tenant-b" and must not
    # include the tenant-b classification in its count.
    r = c.get("/v1/admin/overview", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] != "tenant-b"
    assert body["classifications"]["total"] == 0
