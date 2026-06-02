"""Tests for GET /v1/history/tags/{tag}/related/export."""
from __future__ import annotations

import csv
import io
import json
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


def _seed_set(c):
    _seed("a.png", ["finance", "q1", "urgent"])
    _seed("b.png", ["finance", "q1"])
    _seed("c.png", ["finance", "q2"])
    _seed("d.png", ["finance"])
    _seed("e.png", ["ops", "urgent"])  # no seed -> ignored


def test_export_csv_default(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_set(c)
    r = c.get(
        "/v1/history/tags/finance/related/export",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment;" in r.headers["content-disposition"]
    assert "shotclassify-related-finance-" in r.headers["content-disposition"]
    assert r.headers["x-record-count"] == "3"
    assert r.headers["x-base-count"] == "4"

    reader = csv.DictReader(io.StringIO(r.text))
    rows = list(reader)
    assert [r["tag"] for r in rows] == ["q1", "q2", "urgent"]
    assert [int(r["count"]) for r in rows] == [2, 1, 1]


def test_export_json_payload(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_set(c)
    r = c.get(
        "/v1/history/tags/finance/related/export?format=json",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    body = json.loads(r.text)
    assert body["tag"] == "finance"
    assert body["base_count"] == 4
    assert body["count"] == 3
    assert body["filters"]["min_count"] == 1
    assert [it["tag"] for it in body["items"]] == ["q1", "q2", "urgent"]


def test_export_min_count_filter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_set(c)
    r = c.get(
        "/v1/history/tags/finance/related/export?min_count=2",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [r["tag"] for r in rows] == ["q1"]
    assert r.headers["x-record-count"] == "1"


def test_export_invalid_format(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_set(c)
    r = c.get(
        "/v1/history/tags/finance/related/export?format=xml",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 422


def test_export_filename_slug_safe(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["foo bar", "x"])
    r = c.get(
        "/v1/history/tags/foo%20bar/related/export",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    # space normalized to underscore in the filename slug
    assert "shotclassify-related-foo_bar-" in r.headers["content-disposition"]


def test_export_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_set(c)
    r = c.get("/v1/history/tags/finance/related/export")
    assert r.status_code in (401, 403)
