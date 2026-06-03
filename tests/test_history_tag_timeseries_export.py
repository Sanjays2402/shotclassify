"""Tests for GET /v1/history/tags/{tag}/timeseries/export."""
from __future__ import annotations

import csv
import io
import json
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
                tenant_id=None,
                label=None,
                tags=tags,
                pinned=pinned,
            )
        )
        s.commit()


def test_export_csv_default(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    today = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    _seed("a.png", ["finance"], created_at=today)
    _seed("b.png", ["finance"], created_at=today)
    _seed("c.png", ["finance"], created_at=today - timedelta(days=2))

    r = c.get(
        "/v1/history/tags/finance/timeseries/export?days=7",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment;" in r.headers["content-disposition"]
    assert "shotclassify-timeseries-finance-" in r.headers["content-disposition"]
    assert r.headers["x-record-count"] == "7"
    assert r.headers["x-total-count"] == "3"

    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 7
    # Oldest first.
    assert rows[0]["date"] < rows[-1]["date"]
    # Today bucket has 2 hits, two-days-ago has 1.
    assert int(rows[-1]["count"]) == 2
    assert int(rows[-3]["count"]) == 1
    # Dense / zero-filled.
    assert sum(int(r["count"]) for r in rows) == 3


def test_export_json_payload(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    today = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    _seed("a.png", ["finance"], created_at=today)

    r = c.get(
        "/v1/history/tags/finance/timeseries/export?format=json&days=5",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    body = json.loads(r.text)
    assert body["tag"] == "finance"
    assert body["days"] == 5
    assert body["total"] == 1
    assert len(body["series"]) == 5
    assert body["filters"]["days"] == 5
    assert body["filters"]["pinned"] is None
    assert body["series"][-1]["count"] == 1


def test_export_pinned_filter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    today = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    _seed("a.png", ["finance"], created_at=today, pinned=True)
    _seed("b.png", ["finance"], created_at=today, pinned=False)
    _seed("c.png", ["finance"], created_at=today, pinned=False)

    r = c.get(
        "/v1/history/tags/finance/timeseries/export?days=3&pinned=true",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert sum(int(r["count"]) for r in rows) == 1
    assert r.headers["x-total-count"] == "1"

    r = c.get(
        "/v1/history/tags/finance/timeseries/export?days=3&pinned=false&format=json",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = json.loads(r.text)
    assert body["total"] == 2
    assert body["filters"]["pinned"] is False


def test_export_invalid_format(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/history/tags/finance/timeseries/export?format=xml",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 422


def test_export_filename_slug_safe(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["foo bar"])
    r = c.get(
        "/v1/history/tags/foo%20bar/timeseries/export",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    assert "shotclassify-timeseries-foo_bar-" in r.headers["content-disposition"]


def test_export_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/history/tags/finance/timeseries/export")
    assert r.status_code in (401, 403)


def test_export_unknown_tag_returns_zero_series(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/history/tags/nope/timeseries/export?days=4",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 4
    assert all(int(row["count"]) == 0 for row in rows)
    assert r.headers["x-total-count"] == "0"
