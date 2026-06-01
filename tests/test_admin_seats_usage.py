"""Per-seat usage endpoint: RBAC and strict tenant isolation."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv("AUTH_API_KEYS", '{"viewer-key": "viewer"}')
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'seats.db'}")
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


def test_seats_usage_requires_admin_role(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/admin/seats/usage", headers={"X-API-Key": "viewer-key"})
    assert r.status_code == 403, r.text


def test_seats_usage_unauthenticated_is_401(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/admin/seats/usage")
    assert r.status_code == 401, r.text


def test_seats_usage_shape_and_tenant_isolation(monkeypatch, tmp_path):
    """An admin in tenant A must never see usage rows from tenant B.

    Seeds classifications under tenant B and confirms the seat-usage
    response for the admin (whose resolved tenant is not "tenant-b") does
    not include the tenant-b principal in either ``members`` or
    ``orphans``, and that its totals do not count those rows.
    """
    c = _client(monkeypatch, tmp_path)
    c.get("/healthz")  # force lifespan/init_db
    from shotclassify_store import ClassificationRow
    from shotclassify_store.db import get_session

    with get_session() as s:
        for i in range(3):
            s.merge(
                ClassificationRow(
                    id=f"other-{i}",
                    filename=f"seed-{i}.png",
                    image_path=None,
                    created_at=datetime.now(UTC),
                    primary_category="other",
                    confidence=0.9,
                    ocr_text="",
                    ocr_lang="",
                    extracted={},
                    route={},
                    elapsed_ms=0,
                    principal="leaked-user@tenant-b",
                    tenant_id="tenant-b",
                )
            )
        s.commit()

    r = c.get("/v1/admin/seats/usage", headers={"X-API-Key": "admin-key"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] != "tenant-b"
    assert set(body.keys()) >= {"tenant_id", "period", "seats", "totals", "members", "orphans"}
    assert isinstance(body["members"], list)
    assert isinstance(body["orphans"], list)
    leaked = "leaked-user@tenant-b"
    assert all(m["principal"] != leaked for m in body["members"])
    assert all(o["principal"] != leaked for o in body["orphans"])
    assert body["totals"]["classifications"] == 0
