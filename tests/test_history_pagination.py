"""Pagination and advanced filter behavior for /v1/history."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from services.api.app.main import create_app
from shotclassify_common import Category


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'hist.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def _seed(n: int = 25):
    from shotclassify_store.db import ClassificationRow, get_session, init_db

    init_db()
    now = datetime.now(timezone.utc)
    with get_session() as s:
        for i in range(n):
            conf = 0.5 + (i % 5) * 0.1
            row = ClassificationRow(
                id=f"rec-{i:03d}",
                created_at=now - timedelta(minutes=i),
                filename=f"shot-{i}.png",
                primary_category=Category.receipt.value,
                confidence=conf,
                ocr_text="hello world",
                image_path=None,
                tenant_id=None,
            )
            s.add(row)
        s.commit()


def test_history_pagination_and_filters(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed(25)

    r = c.get("/v1/history?limit=10&offset=0", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    page1 = r.json()
    assert len(page1) == 10
    assert r.headers.get("x-total-count") == "25"
    assert r.headers.get("x-offset") == "0"
    assert r.headers.get("x-limit") == "10"

    r2 = c.get("/v1/history?limit=10&offset=10", headers={"X-API-Key": "k"})
    page2 = r2.json()
    assert len(page2) == 10
    ids1 = {row["id"] for row in page1}
    ids2 = {row["id"] for row in page2}
    assert ids1.isdisjoint(ids2)

    r3 = c.get(
        "/v1/history?limit=50&min_conf=0.7", headers={"X-API-Key": "k"}
    )
    assert r3.status_code == 200
    for row in r3.json():
        assert row["confidence"] >= 0.7 - 1e-9

    r4 = c.get(
        "/v1/history?limit=5&sort=conf_desc", headers={"X-API-Key": "k"}
    )
    confs = [row["confidence"] for row in r4.json()]
    assert confs == sorted(confs, reverse=True)

    r5 = c.get(
        "/v1/history?limit=5&sort=old", headers={"X-API-Key": "k"}
    )
    times = [row["created_at"] for row in r5.json()]
    assert times == sorted(times)

    r6 = c.get("/v1/history?limit=10&sort=bogus", headers={"X-API-Key": "k"})
    assert r6.status_code == 422
