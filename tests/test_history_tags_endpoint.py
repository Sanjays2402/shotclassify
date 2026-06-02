"""Tests for the GET /v1/history/tags discovery endpoint."""
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


def _seed(filename: str, tags: list[str], tenant_id: str | None = None) -> None:
    from shotclassify_store.db import ClassificationRow, get_session, init_db
    from shotclassify_common import Category

    init_db()
    with get_session() as s:
        s.add(
            ClassificationRow(
                id=uuid.uuid4().hex,
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


def test_tags_endpoint_counts_and_sort(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance", "q1"])
    _seed("b.png", ["finance", "q2"])
    _seed("c.png", ["finance"])
    _seed("d.png", ["ops"])

    r = c.get("/v1/history/tags", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 4
    items = body["items"]
    # finance: 3, ops: 1, q1: 1, q2: 1. Count desc, then tag asc.
    assert items[0] == {"tag": "finance", "count": 3}
    assert items[1] == {"tag": "ops", "count": 1}
    assert items[2] == {"tag": "q1", "count": 1}
    assert items[3] == {"tag": "q2", "count": 1}


def test_tags_endpoint_substring_filter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance", "q1"])
    _seed("b.png", ["ops"])

    r = c.get("/v1/history/tags?q=FIN", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    body = r.json()
    assert [it["tag"] for it in body["items"]] == ["finance"]


def test_tags_endpoint_limit_clamped(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["alpha", "beta", "gamma"])

    r = c.get("/v1/history/tags?limit=2", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    # Limit values outside [1, 500] are rejected at the route layer.
    r = c.get("/v1/history/tags?limit=0", headers={"X-API-Key": "k"})
    assert r.status_code == 422
    r = c.get("/v1/history/tags?limit=600", headers={"X-API-Key": "k"})
    assert r.status_code == 422


def test_tags_endpoint_empty(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/history/tags", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    assert r.json() == {"items": [], "count": 0}


def test_tags_endpoint_min_count_filter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance", "q1"])
    _seed("b.png", ["finance", "q2"])
    _seed("c.png", ["finance"])
    _seed("d.png", ["ops"])

    # min_count=2 drops the one-offs (ops, q1, q2), keeps finance.
    r = c.get("/v1/history/tags?min_count=2", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["items"] == [{"tag": "finance", "count": 3}]

    # min_count=4 drops everything.
    r = c.get("/v1/history/tags?min_count=4", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    assert r.json() == {"items": [], "count": 0}

    # Values below 1 are rejected at the route layer.
    r = c.get("/v1/history/tags?min_count=0", headers={"X-API-Key": "k"})
    assert r.status_code == 422


def test_tags_endpoint_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/history/tags")
    assert r.status_code in (401, 403)
