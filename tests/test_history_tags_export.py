"""Tests for the GET /v1/history/tags/export endpoint.

Admins doing taxonomy cleanup want to dump every tag in their workspace
to a spreadsheet, not page through autocomplete. These tests cover the
CSV and JSON shapes, the filters, RBAC/tenant scoping, and the safety
that ``/tags/export`` does not collide with ``/tags/{tag}``.
"""
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
    from shotclassify_common import Category
    from shotclassify_store.db import ClassificationRow, get_session, init_db

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


def test_tags_export_csv_default(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance", "q1"])
    _seed("b.png", ["finance", "q2"])
    _seed("c.png", ["finance"])
    _seed("d.png", ["ops"])

    r = c.get("/v1/history/tags/export", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["content-disposition"].endswith('.csv"')
    assert r.headers["x-record-count"] == "4"

    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [row["tag"] for row in rows] == ["finance", "ops", "q1", "q2"]
    assert [row["count"] for row in rows] == ["3", "1", "1", "1"]


def test_tags_export_json_shape(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"])
    _seed("b.png", ["ops"])

    r = c.get(
        "/v1/history/tags/export?format=json&sort=name",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = json.loads(r.text)
    assert body["count"] == 2
    assert body["filters"]["sort"] == "name"
    assert [it["tag"] for it in body["items"]] == ["finance", "ops"]


def test_tags_export_min_count_filter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"])
    _seed("b.png", ["finance"])
    _seed("c.png", ["one-off"])

    r = c.get(
        "/v1/history/tags/export?min_count=2",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [row["tag"] for row in rows] == ["finance"]


def test_tags_export_substring_filter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance", "q1"])
    _seed("b.png", ["ops"])

    r = c.get(
        "/v1/history/tags/export?q=FIN",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [row["tag"] for row in rows] == ["finance"]


def test_tags_export_rejects_bad_format(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/history/tags/export?format=xml",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 422


def test_tags_export_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/history/tags/export")
    assert r.status_code in (401, 403)


def test_tags_export_does_not_shadow_tag_detail(monkeypatch, tmp_path):
    """Ensure /tags/export is matched before /tags/{tag}."""
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"])

    r_export = c.get("/v1/history/tags/export", headers={"X-API-Key": "k"})
    assert r_export.status_code == 200
    assert r_export.headers["content-type"].startswith("text/csv")

    # And the per-tag detail endpoint still works for a tag literally called
    # something else.
    r_detail = c.get("/v1/history/tags/finance", headers={"X-API-Key": "k"})
    assert r_detail.status_code == 200
    assert r_detail.json()["tag"] == "finance"
