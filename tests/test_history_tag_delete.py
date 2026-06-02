"""Tests for the POST /v1/history/tags/delete endpoint."""
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


def test_delete_tag_removes_from_matching_rows(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    a = _seed("a.png", ["obsolete", "q1"])
    b = _seed("b.png", ["obsolete"])
    other = _seed("c.png", ["ops"])

    r = c.post(
        "/v1/history/tags/delete",
        headers={"X-API-Key": "k"},
        json={"tag": "obsolete"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"updated": 2, "tag": "obsolete"}
    assert _tags_of(a) == ["q1"]
    assert _tags_of(b) == []
    assert _tags_of(other) == ["ops"]


def test_delete_tag_preserves_order_of_other_tags(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    rid = _seed("a.png", ["one", "two", "three", "two"])
    r = c.post(
        "/v1/history/tags/delete",
        headers={"X-API-Key": "k"},
        json={"tag": "two"},
    )
    assert r.status_code == 200
    assert r.json()["updated"] == 1
    assert _tags_of(rid) == ["one", "three"]


def test_delete_tag_normalizes_input(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    rid = _seed("a.png", ["finance", "q1"])
    r = c.post(
        "/v1/history/tags/delete",
        headers={"X-API-Key": "k"},
        json={"tag": "  FINANCE  "},
    )
    assert r.status_code == 200
    assert r.json() == {"updated": 1, "tag": "finance"}
    assert _tags_of(rid) == ["q1"]


def test_delete_tag_dry_run_does_not_mutate(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    rid = _seed("a.png", ["obsolete", "q1"])
    r = c.post(
        "/v1/history/tags/delete?dry_run=true",
        headers={"X-API-Key": "k"},
        json={"tag": "obsolete"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["applied"] is False
    assert body["would_update"] == 1
    assert body["tag"] == "obsolete"
    assert r.headers.get("X-Dry-Run") == "true"
    assert _tags_of(rid) == ["obsolete", "q1"]


def test_delete_tag_validates_body(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Missing field.
    r = c.post(
        "/v1/history/tags/delete",
        headers={"X-API-Key": "k"},
        json={},
    )
    assert r.status_code == 400
    # Empty string normalizes away.
    r = c.post(
        "/v1/history/tags/delete",
        headers={"X-API-Key": "k"},
        json={"tag": "   "},
    )
    assert r.status_code == 400
    # Wrong type.
    r = c.post(
        "/v1/history/tags/delete",
        headers={"X-API-Key": "k"},
        json={"tag": 5},
    )
    assert r.status_code == 400
    # Unknown field.
    r = c.post(
        "/v1/history/tags/delete",
        headers={"X-API-Key": "k"},
        json={"tag": "x", "extra": 1},
    )
    assert r.status_code == 400


def test_delete_tag_is_tenant_scoped(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    a = _seed("a.png", ["obsolete"], tenant_id="acme")
    b = _seed("b.png", ["obsolete"], tenant_id="globex")
    r = c.post(
        "/v1/history/tags/delete",
        headers={"X-API-Key": "k", "X-Tenant": "acme"},
        json={"tag": "obsolete"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 1
    assert _tags_of(a) == []
    assert _tags_of(b) == ["obsolete"]


def test_delete_tag_noop_when_no_match(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    rid = _seed("a.png", ["finance"])
    r = c.post(
        "/v1/history/tags/delete",
        headers={"X-API-Key": "k"},
        json={"tag": "nope"},
    )
    assert r.status_code == 200
    assert r.json() == {"updated": 0, "tag": "nope"}
    assert _tags_of(rid) == ["finance"]


def test_delete_tag_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/history/tags/delete",
        json={"tag": "x"},
    )
    assert r.status_code in (401, 403)
