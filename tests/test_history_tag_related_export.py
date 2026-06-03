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


def test_export_pinned_filter_csv(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Pinned rows: finance co-occurs with q1 (x2) and q2 (x1).
    _seed_pinned("a.png", ["finance", "q1"], pinned=True)
    _seed_pinned("b.png", ["finance", "q1"], pinned=True)
    _seed_pinned("c.png", ["finance", "q2"], pinned=True)
    # Unpinned rows: finance co-occurs with urgent only.
    _seed_pinned("d.png", ["finance", "urgent"], pinned=False)
    _seed_pinned("e.png", ["finance", "urgent"], pinned=False)

    r = c.get(
        "/v1/history/tags/finance/related/export?pinned=true",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200, r.text
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [row["tag"] for row in rows] == ["q1", "q2"]
    assert [int(row["count"]) for row in rows] == [2, 1]
    # base_count reflects pinned rows only when pinned=true.
    assert r.headers["x-base-count"] == "3"
    assert r.headers["x-record-count"] == "2"

    r = c.get(
        "/v1/history/tags/finance/related/export?pinned=false",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200, r.text
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [row["tag"] for row in rows] == ["urgent"]
    assert [int(row["count"]) for row in rows] == [2]
    assert r.headers["x-base-count"] == "2"


def test_export_pinned_filter_json(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_pinned("a.png", ["finance", "q1"], pinned=True)
    _seed_pinned("b.png", ["finance", "q1"], pinned=True)
    _seed_pinned("c.png", ["finance", "urgent"], pinned=False)

    r = c.get(
        "/v1/history/tags/finance/related/export?format=json&pinned=true",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200, r.text
    body = json.loads(r.text)
    assert body["tag"] == "finance"
    assert body["base_count"] == 2
    assert body["filters"]["pinned"] is True
    assert [it["tag"] for it in body["items"]] == ["q1"]

    # Omitted pinned param defaults to None in filters echo.
    r = c.get(
        "/v1/history/tags/finance/related/export?format=json",
        headers={"X-API-Key": "k"},
    )
    body = json.loads(r.text)
    assert body["filters"]["pinned"] is None
    assert body["base_count"] == 3


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


def test_export_confidence_band_filter_csv(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Low-confidence seed rows: q1 co-occurs twice, q2 once.
    _seed_conf("a.png", ["finance", "q1"], confidence=0.30)
    _seed_conf("b.png", ["finance", "q1"], confidence=0.40)
    _seed_conf("c.png", ["finance", "q2"], confidence=0.45)
    # High-confidence seed rows: only urgent co-occurs.
    _seed_conf("d.png", ["finance", "urgent"], confidence=0.95)
    _seed_conf("e.png", ["finance", "urgent"], confidence=0.99)

    r = c.get(
        "/v1/history/tags/finance/related/export?max_conf=0.5",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200, r.text
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [row["tag"] for row in rows] == ["q1", "q2"]
    assert [int(row["count"]) for row in rows] == [2, 1]
    assert r.headers["x-base-count"] == "3"
    assert r.headers["x-record-count"] == "2"

    r = c.get(
        "/v1/history/tags/finance/related/export?min_conf=0.9",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [row["tag"] for row in rows] == ["urgent"]
    assert r.headers["x-base-count"] == "2"


def test_export_confidence_band_filter_json(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_conf("a.png", ["finance", "q1"], confidence=0.30)
    _seed_conf("b.png", ["finance", "urgent"], confidence=0.95)

    r = c.get(
        "/v1/history/tags/finance/related/export?format=json&min_conf=0.9",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200, r.text
    body = json.loads(r.text)
    assert body["base_count"] == 1
    assert body["filters"]["min_conf"] == 0.9
    assert body["filters"]["max_conf"] is None
    assert [it["tag"] for it in body["items"]] == ["urgent"]


def test_export_confidence_band_inverted_returns_400(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_conf("a.png", ["finance", "q1"], confidence=0.5)
    r = c.get(
        "/v1/history/tags/finance/related/export?min_conf=0.9&max_conf=0.1",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 400


def test_export_confidence_band_out_of_range_returns_422(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_conf("a.png", ["finance", "q1"], confidence=0.5)
    r = c.get(
        "/v1/history/tags/finance/related/export?min_conf=1.5",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 422
