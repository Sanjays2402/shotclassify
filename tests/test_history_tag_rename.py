"""Tests for the POST /v1/history/tags/rename endpoint."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'api.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def _seed(filename: str, tags: list[str], tenant_id: str | None = None) -> str:
    from shotclassify_store.db import ClassificationRow, get_session, init_db
    from shotclassify_common import Category

    init_db()
    rid = uuid.uuid4().hex
    with get_session() as s:
        s.add(
            ClassificationRow(
                id=rid,
                created_at=datetime.now(timezone.utc),
                filename=filename,
                primary_category=Category.receipt.value,
                confidence=0.9,
                ocr_text="",
                image_path=None,
                tenant_id=tenant_id,
                label=None,
                tags=tags,
                pinned=False,
            )
        )
        s.commit()
    return rid


def _tags_of(rid: str) -> list[str]:
    from shotclassify_store.db import ClassificationRow, get_session

    with get_session() as s:
        return list(s.get(ClassificationRow, rid).tags or [])


def test_rename_tag_updates_matching_rows(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    a = _seed("a.png", ["finace", "q1"])
    b = _seed("b.png", ["finace"])
    other = _seed("c.png", ["ops"])

    r = c.post(
        "/v1/history/tags/rename",
        headers={"X-API-Key": "k"},
        json={"from": "finace", "to": "finance"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"updated": 2, "old": "finace", "new": "finance"}
    assert _tags_of(a) == ["finance", "q1"]
    assert _tags_of(b) == ["finance"]
    assert _tags_of(other) == ["ops"]


def test_rename_tag_merges_when_target_already_present(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    rid = _seed("a.png", ["finance", "finace", "q1"])
    r = c.post(
        "/v1/history/tags/rename",
        headers={"X-API-Key": "k"},
        json={"from": "finace", "to": "finance"},
    )
    assert r.status_code == 200
    assert r.json()["updated"] == 1
    # Old dropped, new not duplicated, order preserved (finance kept where it was).
    assert _tags_of(rid) == ["finance", "q1"]


def test_rename_tag_normalizes_inputs(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    rid = _seed("a.png", ["finance"])
    r = c.post(
        "/v1/history/tags/rename",
        headers={"X-API-Key": "k"},
        json={"from": "  FINANCE  ", "to": "Money"},
    )
    assert r.status_code == 200
    assert r.json() == {"updated": 1, "old": "finance", "new": "money"}
    assert _tags_of(rid) == ["money"]


def test_rename_tag_dry_run_does_not_mutate(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    rid = _seed("a.png", ["finace"])
    r = c.post(
        "/v1/history/tags/rename?dry_run=true",
        headers={"X-API-Key": "k"},
        json={"from": "finace", "to": "finance"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["applied"] is False
    assert body["would_update"] == 1
    assert r.headers.get("X-Dry-Run") == "true"
    # Untouched.
    assert _tags_of(rid) == ["finace"]


def test_rename_tag_noop_when_old_equals_new(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"])
    r = c.post(
        "/v1/history/tags/rename",
        headers={"X-API-Key": "k"},
        json={"from": "finance", "to": "FINANCE"},
    )
    assert r.status_code == 200
    assert r.json() == {"updated": 0, "old": "finance", "new": "finance"}


def test_rename_tag_validates_body(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Missing fields.
    r = c.post(
        "/v1/history/tags/rename",
        headers={"X-API-Key": "k"},
        json={"from": "x"},
    )
    assert r.status_code == 400
    # Empty strings normalize away.
    r = c.post(
        "/v1/history/tags/rename",
        headers={"X-API-Key": "k"},
        json={"from": "   ", "to": "x"},
    )
    assert r.status_code == 400
    # Unknown field.
    r = c.post(
        "/v1/history/tags/rename",
        headers={"X-API-Key": "k"},
        json={"from": "a", "to": "b", "extra": 1},
    )
    assert r.status_code == 400


def test_rename_tag_is_tenant_scoped(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Seed rows in two tenants; rename via tenant A should leave tenant B alone.
    a = _seed("a.png", ["finace"], tenant_id="acme")
    b = _seed("b.png", ["finace"], tenant_id="globex")
    r = c.post(
        "/v1/history/tags/rename",
        headers={"X-API-Key": "k", "X-Tenant": "acme"},
        json={"from": "finace", "to": "finance"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 1
    assert _tags_of(a) == ["finance"]
    assert _tags_of(b) == ["finace"]


def test_rename_tag_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/history/tags/rename",
        json={"from": "a", "to": "b"},
    )
    assert r.status_code in (401, 403)
