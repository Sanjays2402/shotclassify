"""Tests for /v1/history/export (CSV + JSON)."""
from __future__ import annotations

import io
import csv
import json
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


def test_history_export_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/v1/history/export").status_code == 401


def test_history_export_csv_empty(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/history/export?format=csv", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd and ".csv" in cd
    reader = csv.reader(io.StringIO(r.text))
    header = next(reader)
    # Header is always present even with zero rows.
    for col in ("id", "created_at", "filename", "primary_category", "confidence"):
        assert col in header


def test_history_export_json_empty(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/history/export?format=json&limit=10", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = json.loads(r.text)
    assert body["count"] == 0
    assert body["records"] == []
    assert body["filters"]["limit"] == 10


def test_history_export_rejects_bad_format(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/history/export?format=xml", headers={"X-API-Key": "k"})
    assert r.status_code == 422


def _seed_one(name: str, confidence: float) -> None:
    from shotclassify_store.db import ClassificationRow, get_session, init_db
    from shotclassify_common import Category
    import uuid

    init_db()
    with get_session() as s:
        s.add(
            ClassificationRow(
                id=uuid.uuid4().hex,
                created_at=datetime.now(timezone.utc),
                filename=name,
                primary_category=Category.receipt.value,
                confidence=confidence,
                ocr_text="",
                image_path=None,
                tenant_id=None,
            )
        )
        s.commit()


def test_history_export_honours_min_conf_filter(monkeypatch, tmp_path):
    """Export must apply the same min_conf filter as the list view so the
    download matches what the user sees on screen."""
    c = _client(monkeypatch, tmp_path)
    _seed_one("low.png", 0.42)

    # Below the floor: empty export.
    r = c.get(
        "/v1/history/export?format=json&min_conf=0.9",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = json.loads(r.text)
    assert body["count"] == 0
    assert body["filters"]["min_conf"] == 0.9

    # Within range: row comes back.
    r = c.get(
        "/v1/history/export?format=json&min_conf=0.1",
        headers={"X-API-Key": "k"},
    )
    body = json.loads(r.text)
    assert body["count"] == 1
    assert body["records"][0]["filename"] == "low.png"


def test_history_export_csv_includes_label_tags_and_pinned(monkeypatch, tmp_path):
    """CSV export must surface label, tags, and pinned so a download lines
    up with the dashboard filters that already use those fields."""
    c = _client(monkeypatch, tmp_path)

    from shotclassify_store.db import ClassificationRow, get_session, init_db
    from shotclassify_common import Category
    import uuid

    init_db()
    with get_session() as s:
        s.add(
            ClassificationRow(
                id=uuid.uuid4().hex,
                created_at=datetime.now(timezone.utc),
                filename="invoice.png",
                primary_category=Category.receipt.value,
                confidence=0.95,
                ocr_text="",
                image_path=None,
                tenant_id=None,
                label="Q1 invoice",
                tags=["finance", "q1"],
                pinned=True,
            )
        )
        s.commit()

    r = c.get("/v1/history/export?format=csv", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    reader = csv.DictReader(io.StringIO(r.text))
    header = reader.fieldnames or []
    for col in ("label", "tags", "pinned"):
        assert col in header, f"missing {col} in CSV header"
    rows = list(reader)
    assert len(rows) == 1
    row = rows[0]
    assert row["label"] == "Q1 invoice"
    assert row["pinned"] == "true"
    # Tags joined with comma so a spreadsheet user can split on the cell.
    parts = [p.strip() for p in row["tags"].split(",")]
    assert set(parts) == {"finance", "q1"}
