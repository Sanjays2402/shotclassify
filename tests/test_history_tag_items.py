"""Tests for the GET /v1/history/tags/{tag}/items recent-uses endpoint."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

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


def _seed(
    filename: str,
    tags: list[str],
    tenant_id: str | None = None,
    created_at: datetime | None = None,
    confidence: float = 0.9,
    pinned: bool = False,
) -> str:
    from shotclassify_store.db import ClassificationRow, get_session, init_db
    from shotclassify_common import Category

    init_db()
    rid = uuid.uuid4().hex
    with get_session() as s:
        s.add(
            ClassificationRow(
                id=rid,
                created_at=created_at or datetime.now(timezone.utc),
                filename=filename,
                primary_category=Category.receipt.value,
                confidence=confidence,
                ocr_text="",
                image_path=None,
                tenant_id=tenant_id,
                label=None,
                tags=tags,
                pinned=pinned,
            )
        )
        s.commit()
    return rid


def test_tag_items_returns_matching_records_newest_first(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    base = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    _seed("a.png", ["finance", "q1"], created_at=base)
    _seed("b.png", ["finance"], created_at=base + timedelta(days=5))
    _seed("c.png", ["finance", "urgent"], created_at=base + timedelta(days=10))
    _seed("d.png", ["ops"], created_at=base + timedelta(days=20))  # excluded

    r = c.get("/v1/history/tags/finance/items", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [row["filename"] for row in body] == ["c.png", "b.png", "a.png"]
    assert r.headers["x-total-count"] == "3"
    assert r.headers["x-offset"] == "0"
    assert r.headers["x-limit"] == "50"


def test_tag_items_unknown_tag_returns_empty_list(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"])
    r = c.get("/v1/history/tags/nope/items", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    assert r.json() == []
    assert r.headers["x-total-count"] == "0"


def test_tag_items_normalizes_input(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"])
    r = c.get("/v1/history/tags/%20FINANCE%20/items", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_tag_items_pagination(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    base = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(5):
        _seed(f"f{i}.png", ["finance"], created_at=base + timedelta(minutes=i))

    r = c.get(
        "/v1/history/tags/finance/items?limit=2&offset=0",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    page1 = r.json()
    assert len(page1) == 2
    assert r.headers["x-total-count"] == "5"

    r = c.get(
        "/v1/history/tags/finance/items?limit=2&offset=2",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    page2 = r.json()
    assert len(page2) == 2
    assert {row["id"] for row in page1}.isdisjoint({row["id"] for row in page2})


def test_tag_items_sort_conf_desc(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("low.png", ["finance"], confidence=0.10)
    _seed("mid.png", ["finance"], confidence=0.50)
    _seed("high.png", ["finance"], confidence=0.95)

    r = c.get(
        "/v1/history/tags/finance/items?sort=conf_desc",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    names = [row["filename"] for row in r.json()]
    assert names == ["high.png", "mid.png", "low.png"]


def test_tag_items_tenant_isolation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"], tenant_id="acme")
    _seed("b.png", ["finance"], tenant_id="other")
    _seed("c.png", ["finance"], tenant_id="other")

    r = c.get(
        "/v1/history/tags/finance/items",
        headers={"X-API-Key": "k", "X-Tenant": "acme"},
    )
    assert r.status_code == 200
    assert [row["filename"] for row in r.json()] == ["a.png"]

    r = c.get(
        "/v1/history/tags/finance/items",
        headers={"X-API-Key": "k", "X-Tenant": "other"},
    )
    assert r.status_code == 200
    assert {row["filename"] for row in r.json()} == {"b.png", "c.png"}


def test_tag_items_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/history/tags/finance/items")
    assert r.status_code in (401, 403)


def test_tag_items_bad_sort_rejected(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/history/tags/finance/items?sort=bogus",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 422


def test_tag_items_pinned_filter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    base = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    _seed("p1.png", ["finance"], created_at=base, pinned=True)
    _seed("p2.png", ["finance"], created_at=base + timedelta(days=1), pinned=True)
    _seed("u1.png", ["finance"], created_at=base + timedelta(days=2), pinned=False)
    _seed("other.png", ["ops"], created_at=base + timedelta(days=3), pinned=True)

    # pinned=true returns only pinned records for the tag.
    r = c.get(
        "/v1/history/tags/finance/items?pinned=true",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = r.json()
    assert {row["filename"] for row in body} == {"p1.png", "p2.png"}
    assert all(row["pinned"] is True for row in body)
    assert r.headers["x-total-count"] == "2"

    # pinned=false returns only unpinned records for the tag.
    r = c.get(
        "/v1/history/tags/finance/items?pinned=false",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = r.json()
    assert {row["filename"] for row in body} == {"u1.png"}
    assert r.headers["x-total-count"] == "1"

    # Omitting pinned returns both, ignoring records of other tags.
    r = c.get(
        "/v1/history/tags/finance/items",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    assert {row["filename"] for row in r.json()} == {"p1.png", "p2.png", "u1.png"}
    assert r.headers["x-total-count"] == "3"


def test_tag_items_pinned_bad_value_rejected(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/history/tags/finance/items?pinned=maybe",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 422
