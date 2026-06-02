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


def _seed(filename: str, tags: list[str] | None, pinned: bool = False) -> None:
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
                pinned=pinned,
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
    # Nothing was pinned in this fixture.
    assert body["pinned"] == 0
    assert body["pinned_untagged"] == 0


def test_stats_all_untagged_when_no_tags(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", None)
    _seed("b.png", [])

    body = c.get("/v1/history/stats", headers={"X-API-Key": "k"}).json()
    assert body == {
        "count": 2,
        "untagged": 2,
        "tagged": 0,
        "pinned": 0,
        "pinned_untagged": 0,
    }


def test_stats_all_tagged(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["x"])
    _seed("b.png", ["y", "z"])

    body = c.get("/v1/history/stats", headers={"X-API-Key": "k"}).json()
    assert body == {
        "count": 2,
        "untagged": 0,
        "tagged": 2,
        "pinned": 0,
        "pinned_untagged": 0,
    }


def test_stats_empty(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    from shotclassify_store.db import init_db
    init_db()

    body = c.get("/v1/history/stats", headers={"X-API-Key": "k"}).json()
    assert body == {
        "count": 0,
        "untagged": 0,
        "tagged": 0,
        "pinned": 0,
        "pinned_untagged": 0,
    }


def test_stats_reports_pinned_count_independent_of_tagged(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Pinned + tagged.
    _seed("a.png", ["finance"], pinned=True)
    # Pinned + untagged (pinned should still count it).
    _seed("b.png", None, pinned=True)
    # Unpinned + tagged.
    _seed("c.png", ["q1"], pinned=False)
    # Unpinned + untagged.
    _seed("d.png", [], pinned=False)

    body = c.get("/v1/history/stats", headers={"X-API-Key": "k"}).json()
    assert body["count"] == 4
    assert body["tagged"] == 2
    assert body["untagged"] == 2
    assert body["pinned"] == 2
    # Pinned is independent of the tagged/untagged split; it can overlap
    # either bucket and is not required to sum with them.
    assert body["untagged"] + body["tagged"] == body["count"]
    # Only b.png is both pinned and untagged in this fixture.
    assert body["pinned_untagged"] == 1
    # The intersection can never exceed either side it intersects.
    assert body["pinned_untagged"] <= body["pinned"]
    assert body["pinned_untagged"] <= body["untagged"]


def test_stats_pinned_untagged_zero_when_all_pinned_are_tagged(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Every pinned row also has at least one tag.
    _seed("a.png", ["finance"], pinned=True)
    _seed("b.png", ["q1"], pinned=True)
    # Unpinned + untagged: not part of the intersection.
    _seed("c.png", None, pinned=False)

    body = c.get("/v1/history/stats", headers={"X-API-Key": "k"}).json()
    assert body["pinned"] == 2
    assert body["untagged"] == 1
    assert body["pinned_untagged"] == 0
