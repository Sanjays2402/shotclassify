"""Tests for the GET /v1/history/tags/{tag} usage summary endpoint."""
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
    pinned: bool = False,
) -> None:
    from shotclassify_store.db import ClassificationRow, get_session, init_db
    from shotclassify_common import Category

    init_db()
    with get_session() as s:
        s.add(
            ClassificationRow(
                id=uuid.uuid4().hex,
                created_at=created_at or datetime.now(timezone.utc),
                filename=filename,
                primary_category=Category.receipt.value,
                confidence=0.9,
                ocr_text="",
                image_path=None,
                tenant_id=tenant_id,
                label=None,
                tags=tags,
                pinned=pinned,
            )
        )
        s.commit()


def test_tag_detail_count_and_window(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    base = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    _seed("a.png", ["finance", "q1"], created_at=base)
    _seed("b.png", ["finance"], created_at=base + timedelta(days=5))
    _seed("c.png", ["finance", "urgent"], created_at=base + timedelta(days=10))
    _seed("d.png", ["ops"], created_at=base + timedelta(days=20))  # excluded

    r = c.get("/v1/history/tags/finance", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tag"] == "finance"
    assert body["count"] == 3
    assert body["first_seen"] == base.isoformat()
    assert body["last_seen"] == (base + timedelta(days=10)).isoformat()


def test_tag_detail_unknown_tag_returns_empty(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"])
    r = c.get("/v1/history/tags/nope", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    assert r.json() == {
        "tag": "nope",
        "count": 0,
        "pinned": 0,
        "low_confidence": 0,
        "pinned_low_confidence": 0,
        "first_seen": None,
        "last_seen": None,
    }


def _seed_conf(
    filename: str,
    tags: list[str],
    confidence: float,
    pinned: bool = False,
    tenant_id: str | None = None,
) -> None:
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


def test_tag_detail_low_confidence_counts(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # tag = finance: 4 total, 2 low-conf (<=0.7), 1 pinned-low-conf
    _seed_conf("a.png", ["finance"], confidence=0.95, pinned=True)
    _seed_conf("b.png", ["finance"], confidence=0.6, pinned=True)   # low + pinned
    _seed_conf("c.png", ["finance"], confidence=0.4, pinned=False)  # low
    _seed_conf("d.png", ["finance"], confidence=0.8, pinned=False)
    # other tag, low-conf -- must not leak into finance counts
    _seed_conf("e.png", ["ops"], confidence=0.1, pinned=True)

    r = c.get("/v1/history/tags/finance", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 4
    assert body["pinned"] == 2
    assert body["low_confidence"] == 2
    assert body["pinned_low_confidence"] == 1

    # Custom threshold tightens the band: only conf <= 0.5 counts.
    r = c.get(
        "/v1/history/tags/finance?low_conf_threshold=0.5",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["low_confidence"] == 1
    assert body["pinned_low_confidence"] == 0


def test_tag_detail_low_conf_threshold_validation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/history/tags/finance?low_conf_threshold=1.5",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 422


def test_tag_detail_pinned_count(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"], pinned=True)
    _seed("b.png", ["finance"], pinned=True)
    _seed("c.png", ["finance"], pinned=False)
    _seed("d.png", ["ops"], pinned=True)  # different tag, ignored

    r = c.get("/v1/history/tags/finance", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 3
    assert body["pinned"] == 2


def test_tag_detail_normalizes_input(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"])
    r = c.get("/v1/history/tags/%20FINANCE%20", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    body = r.json()
    assert body["tag"] == "finance"
    assert body["count"] == 1


def test_tag_detail_tenant_isolation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"], tenant_id="acme")
    _seed("b.png", ["finance"], tenant_id="other")
    _seed("c.png", ["finance"], tenant_id="other")

    r = c.get(
        "/v1/history/tags/finance",
        headers={"X-API-Key": "k", "X-Tenant": "acme"},
    )
    assert r.status_code == 200
    assert r.json()["count"] == 1

    r = c.get(
        "/v1/history/tags/finance",
        headers={"X-API-Key": "k", "X-Tenant": "other"},
    )
    assert r.status_code == 200
    assert r.json()["count"] == 2


def test_tag_detail_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/history/tags/finance")
    assert r.status_code in (401, 403)
