"""Tests for the GET /v1/history/tags/{tag}/timeseries sparkline endpoint."""
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
                pinned=False,
            )
        )
        s.commit()


def test_timeseries_dense_zero_filled_and_counts(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    today = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    _seed("a.png", ["finance"], created_at=today)
    _seed("b.png", ["finance"], created_at=today)
    _seed("c.png", ["finance"], created_at=today - timedelta(days=2))
    _seed("d.png", ["ops"], created_at=today)  # different tag, ignored

    r = c.get(
        "/v1/history/tags/finance/timeseries?days=7",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tag"] == "finance"
    assert body["days"] == 7
    assert len(body["series"]) == 7
    assert body["series"][0]["date"] < body["series"][-1]["date"]
    # Dense: every entry has count and a date.
    assert all("count" in b and "date" in b for b in body["series"])
    assert body["total"] == 3
    # Today is the last bucket, with the two finance hits today.
    assert body["series"][-1]["count"] == 2
    # Two days ago has the third hit.
    assert body["series"][-3]["count"] == 1


def test_timeseries_unknown_tag_is_empty_series(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"])
    r = c.get(
        "/v1/history/tags/nope/timeseries?days=5",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tag"] == "nope"
    assert body["total"] == 0
    assert len(body["series"]) == 5
    assert all(b["count"] == 0 for b in body["series"])


def test_timeseries_excludes_rows_outside_window(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    today = datetime.now(timezone.utc)
    _seed("old.png", ["finance"], created_at=today - timedelta(days=400))
    _seed("recent.png", ["finance"], created_at=today)

    r = c.get(
        "/v1/history/tags/finance/timeseries?days=30",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_timeseries_normalizes_input(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"])
    r = c.get(
        "/v1/history/tags/%20FINANCE%20/timeseries?days=3",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tag"] == "finance"
    assert body["total"] == 1


def test_timeseries_tenant_isolation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"], tenant_id="acme")
    _seed("b.png", ["finance"], tenant_id="other")
    _seed("c.png", ["finance"], tenant_id="other")

    r = c.get(
        "/v1/history/tags/finance/timeseries?days=14",
        headers={"X-API-Key": "k", "X-Tenant": "acme"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r = c.get(
        "/v1/history/tags/finance/timeseries?days=14",
        headers={"X-API-Key": "k", "X-Tenant": "other"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_timeseries_clamps_days_param(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/history/tags/finance/timeseries?days=0",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 422
    r = c.get(
        "/v1/history/tags/finance/timeseries?days=10000",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 422


def test_timeseries_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/history/tags/finance/timeseries")
    assert r.status_code in (401, 403)


def _seed_pinned(filename: str, tags: list[str], pinned: bool, created_at):
    """Like _seed but lets the test control the ``pinned`` flag."""
    from shotclassify_store.db import ClassificationRow, get_session, init_db
    from shotclassify_common import Category

    init_db()
    with get_session() as s:
        s.add(
            ClassificationRow(
                id=uuid.uuid4().hex,
                created_at=created_at,
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


def test_timeseries_pinned_filter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    today = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    _seed_pinned("p1.png", ["finance"], True, today)
    _seed_pinned("p2.png", ["finance"], True, today - timedelta(days=2))
    _seed_pinned("u1.png", ["finance"], False, today)
    _seed_pinned("u2.png", ["finance"], False, today - timedelta(days=1))

    # No filter: all four counted.
    r = c.get(
        "/v1/history/tags/finance/timeseries?days=7",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 4

    # pinned=true: only the two pinned rows.
    r = c.get(
        "/v1/history/tags/finance/timeseries?days=7&pinned=true",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["series"][-1]["count"] == 1  # one pinned today
    assert body["series"][-3]["count"] == 1  # one pinned two days ago

    # pinned=false: only the two unpinned rows.
    r = c.get(
        "/v1/history/tags/finance/timeseries?days=7&pinned=false",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["series"][-1]["count"] == 1
    assert body["series"][-2]["count"] == 1


def _seed_conf(filename: str, tags: list[str], confidence: float, created_at):
    """Like _seed but lets the test control the ``confidence`` value."""
    from shotclassify_store.db import ClassificationRow, get_session, init_db
    from shotclassify_common import Category

    init_db()
    with get_session() as s:
        s.add(
            ClassificationRow(
                id=uuid.uuid4().hex,
                created_at=created_at,
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


def test_timeseries_confidence_band_filter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    today = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    _seed_conf("lo1.png", ["finance"], 0.20, today)
    _seed_conf("lo2.png", ["finance"], 0.35, today - timedelta(days=2))
    _seed_conf("mid.png", ["finance"], 0.65, today)
    _seed_conf("hi.png", ["finance"], 0.95, today - timedelta(days=1))

    # No filter: all four counted.
    r = c.get(
        "/v1/history/tags/finance/timeseries?days=7",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 4

    # Low-confidence band: only the two below 0.5.
    r = c.get(
        "/v1/history/tags/finance/timeseries?days=7&max_conf=0.5",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["series"][-1]["count"] == 1
    assert body["series"][-3]["count"] == 1

    # High-confidence band: only the 0.95 row.
    r = c.get(
        "/v1/history/tags/finance/timeseries?days=7&min_conf=0.9",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["series"][-2]["count"] == 1

    # Inclusive bounds: 0.65 mid-row is included at the edge.
    r = c.get(
        "/v1/history/tags/finance/timeseries?days=7&min_conf=0.65&max_conf=0.65",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_timeseries_confidence_band_inverted_is_400(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/history/tags/finance/timeseries?days=7&min_conf=0.9&max_conf=0.1",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 400
