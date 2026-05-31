"""Tests for /v1/history/export (CSV + JSON)."""
from __future__ import annotations

import io
import csv
import json

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
