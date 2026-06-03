"""Tests for the GET /v1/history/tags/{tag}/related co-occurrence endpoint."""
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


def test_related_tags_counts_and_sort(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance", "q1", "urgent"])
    _seed("b.png", ["finance", "q1"])
    _seed("c.png", ["finance", "q2"])
    _seed("d.png", ["finance"])
    _seed("e.png", ["ops", "urgent"])  # no seed -> ignored

    r = c.get("/v1/history/tags/finance/related", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tag"] == "finance"
    assert body["base_count"] == 4
    # q1: 2, q2: 1, urgent: 1. Count desc then tag asc.
    assert body["items"] == [
        {"tag": "q1", "count": 2},
        {"tag": "q2", "count": 1},
        {"tag": "urgent", "count": 1},
    ]


def test_related_tags_excludes_seed(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance", "q1"])
    r = c.get("/v1/history/tags/finance/related", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    tags = [it["tag"] for it in r.json()["items"]]
    assert "finance" not in tags


def test_related_tags_min_count_filter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance", "q1"])
    _seed("b.png", ["finance", "q1"])
    _seed("c.png", ["finance", "q2"])

    r = c.get(
        "/v1/history/tags/finance/related?min_count=2",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["base_count"] == 3
    assert body["items"] == [{"tag": "q1", "count": 2}]


def test_related_tags_limit_clamped(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance", "alpha", "beta", "gamma"])

    r = c.get(
        "/v1/history/tags/finance/related?limit=2",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    assert len(r.json()["items"]) == 2

    r = c.get(
        "/v1/history/tags/finance/related?limit=0",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 422
    r = c.get(
        "/v1/history/tags/finance/related?limit=600",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 422


def test_related_tags_seed_normalized(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance", "q1"])
    # Seed comes in upper case with whitespace; route normalizes it.
    r = c.get("/v1/history/tags/%20FINANCE%20/related", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    body = r.json()
    assert body["tag"] == "finance"
    assert body["base_count"] == 1
    assert body["items"] == [{"tag": "q1", "count": 1}]


def test_related_tags_unknown_seed(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"])
    r = c.get("/v1/history/tags/nope/related", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    body = r.json()
    assert body == {"tag": "nope", "base_count": 0, "items": []}


def test_related_tags_tenant_isolation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance", "q1"], tenant_id="acme")
    _seed("b.png", ["finance", "q2"], tenant_id="other")

    # Default tenant header is None; only the rows without tenant scope match.
    # Use explicit tenant header to scope the query.
    r = c.get(
        "/v1/history/tags/finance/related",
        headers={"X-API-Key": "k", "X-Tenant": "acme"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["base_count"] == 1
    assert body["items"] == [{"tag": "q1", "count": 1}]


def test_related_tags_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/history/tags/finance/related")
    assert r.status_code in (401, 403)


def _seed_pinned(filename: str, tags: list[str], pinned: bool) -> None:
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


def test_related_tags_pinned_filter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Pinned rows with seed: q1 co-occurs twice, q2 once.
    _seed_pinned("a.png", ["finance", "q1"], pinned=True)
    _seed_pinned("b.png", ["finance", "q1"], pinned=True)
    _seed_pinned("c.png", ["finance", "q2"], pinned=True)
    # Unpinned rows with seed: only urgent co-occurs.
    _seed_pinned("d.png", ["finance", "urgent"], pinned=False)
    _seed_pinned("e.png", ["finance", "urgent"], pinned=False)

    # pinned=true narrows to pinned rows only.
    r = c.get(
        "/v1/history/tags/finance/related?pinned=true",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tag"] == "finance"
    assert body["base_count"] == 3
    assert body["items"] == [
        {"tag": "q1", "count": 2},
        {"tag": "q2", "count": 1},
    ]

    # pinned=false flips to the unpinned subset.
    r = c.get(
        "/v1/history/tags/finance/related?pinned=false",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["base_count"] == 2
    assert body["items"] == [{"tag": "urgent", "count": 2}]

    # Omitting pinned aggregates across both.
    r = c.get(
        "/v1/history/tags/finance/related",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["base_count"] == 5
    assert body["items"] == [
        {"tag": "q1", "count": 2},
        {"tag": "urgent", "count": 2},
        {"tag": "q2", "count": 1},
    ]


def test_related_tags_prefix_filter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance", "fin/q1", "fin/q2"])
    _seed("b.png", ["finance", "fin/q1", "ops/q1"])
    _seed("c.png", ["finance", "ops/q2"])

    # prefix narrows the result set; base_count unchanged.
    r = c.get(
        "/v1/history/tags/finance/related?prefix=fin/",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["base_count"] == 3
    assert body["items"] == [
        {"tag": "fin/q1", "count": 2},
        {"tag": "fin/q2", "count": 1},
    ]

    # Case-insensitive.
    r = c.get(
        "/v1/history/tags/finance/related?prefix=FIN/",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    assert [it["tag"] for it in r.json()["items"]] == ["fin/q1", "fin/q2"]

    # Non-matching prefix returns empty items but keeps base_count.
    r = c.get(
        "/v1/history/tags/finance/related?prefix=zzz",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["base_count"] == 3
    assert body["items"] == []


def _seed_conf(filename: str, tags: list[str], confidence: float) -> None:
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
                tenant_id=None,
                label=None,
                tags=tags,
                pinned=False,
            )
        )
        s.commit()


def test_related_tags_confidence_band_filter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Low-confidence seed rows: q1 co-occurs twice, q2 once.
    _seed_conf("a.png", ["finance", "q1"], confidence=0.30)
    _seed_conf("b.png", ["finance", "q1"], confidence=0.40)
    _seed_conf("c.png", ["finance", "q2"], confidence=0.45)
    # High-confidence seed rows: only urgent co-occurs.
    _seed_conf("d.png", ["finance", "urgent"], confidence=0.95)
    _seed_conf("e.png", ["finance", "urgent"], confidence=0.99)

    # Low band scopes to low-confidence neighbours.
    r = c.get(
        "/v1/history/tags/finance/related?max_conf=0.5",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["base_count"] == 3
    assert body["items"] == [
        {"tag": "q1", "count": 2},
        {"tag": "q2", "count": 1},
    ]

    # High band scopes to high-confidence neighbours.
    r = c.get(
        "/v1/history/tags/finance/related?min_conf=0.9",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["base_count"] == 2
    assert body["items"] == [{"tag": "urgent", "count": 2}]

    # Inverted band returns 400.
    r = c.get(
        "/v1/history/tags/finance/related?min_conf=0.9&max_conf=0.1",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 400

    # Out-of-range band returns 422 (FastAPI Query validation).
    r = c.get(
        "/v1/history/tags/finance/related?min_conf=1.5",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 422
