"""Tests for the multi-tag AND filter on /v1/history and /v1/history/export."""
from __future__ import annotations

import io
import csv
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


def _seed(filename: str, tags: list[str]) -> None:
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


def test_history_tags_filter_and_match(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance", "q1"])
    _seed("b.png", ["finance", "q2"])
    _seed("c.png", ["ops"])

    # Single tag in list behaves like the legacy `tag` filter.
    r = c.get("/v1/history?tags=finance", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    names = sorted(item["filename"] for item in r.json())
    assert names == ["a.png", "b.png"]
    assert r.headers["x-total-count"] == "2"

    # Multi-tag is AND: only the record with both tags wins.
    r = c.get("/v1/history?tags=finance&tags=q1", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    items = r.json()
    assert [item["filename"] for item in items] == ["a.png"]
    assert r.headers["x-total-count"] == "1"

    # Case-insensitive and whitespace-tolerant.
    r = c.get("/v1/history?tags=FINANCE&tags=%20Q1%20", headers={"X-API-Key": "k"})
    assert [item["filename"] for item in r.json()] == ["a.png"]


def test_history_tags_filter_no_match(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance", "q1"])

    r = c.get("/v1/history?tags=finance&tags=ops", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    assert r.json() == []
    assert r.headers["x-total-count"] == "0"


def test_history_tags_filter_combines_with_legacy_tag(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance", "q1", "urgent"])
    _seed("b.png", ["finance", "q1"])

    r = c.get(
        "/v1/history?tag=urgent&tags=finance&tags=q1",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    assert [item["filename"] for item in r.json()] == ["a.png"]


def test_history_tags_filter_rejects_overlong_tag(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/history?tags=" + ("x" * 33),
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 400
    assert "32 characters" in r.json()["detail"]


def test_history_export_tags_filter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance", "q1"])
    _seed("b.png", ["finance", "q2"])
    _seed("c.png", ["ops"])

    r = c.get(
        "/v1/history/export?format=ndjson&tags=finance&tags=q1",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    assert r.headers["x-record-count"] == "1"
    lines = [json.loads(ln) for ln in r.text.split("\n") if ln]
    assert [p["filename"] for p in lines] == ["a.png"]

    # JSON export echoes the normalized tags filter for reproducibility.
    r = c.get(
        "/v1/history/export?format=json&tags=FINANCE&tags=Q1",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = json.loads(r.text)
    assert body["filters"]["tags"] == ["finance", "q1"]
    assert body["count"] == 1
    assert [r["filename"] for r in body["records"]] == ["a.png"]

    # CSV export honours the filter too.
    r = c.get(
        "/v1/history/export?format=csv&tags=finance&tags=q2",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [row["filename"] for row in rows] == ["b.png"]
