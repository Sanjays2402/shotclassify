"""Tests for tagged/untagged split on /v1/history/stats."""
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


def _seed(filename: str, tags: list[str] | None) -> None:
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
                tenant_id=None,
                label=None,
                tags=tags,
                pinned=False,
            )
        )
        s.commit()


def test_stats_reports_untagged_and_tagged_split(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"])
    _seed("b.png", ["finance", "q1"])
    _seed("c.png", [])
    _seed("d.png", None)

    r = c.get("/v1/history/stats", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 4
    assert body["untagged"] == 2
    assert body["tagged"] == 2
    # Invariant: untagged + tagged == count, always.
    assert body["untagged"] + body["tagged"] == body["count"]


def test_stats_all_untagged_when_no_tags(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", None)
    _seed("b.png", [])

    body = c.get("/v1/history/stats", headers={"X-API-Key": "k"}).json()
    assert body == {"count": 2, "untagged": 2, "tagged": 0}


def test_stats_all_tagged(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["x"])
    _seed("b.png", ["y", "z"])

    body = c.get("/v1/history/stats", headers={"X-API-Key": "k"}).json()
    assert body == {"count": 2, "untagged": 0, "tagged": 2}


def test_stats_empty(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    from shotclassify_store.db import init_db
    init_db()

    body = c.get("/v1/history/stats", headers={"X-API-Key": "k"}).json()
    assert body == {"count": 0, "untagged": 0, "tagged": 0}
