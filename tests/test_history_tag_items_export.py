"""Tests for GET /v1/history/tags/{tag}/items/export."""
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
    tenant_id: str | None = None,
    created_at: datetime | None = None,
    confidence: float = 0.9,
    pinned: bool = False,
) -> str:
    from shotclassify_store.db import ClassificationRow, get_session, init_db
    from shotclassify_common import Category

    init_db()
    rid = uuid.uuid4().hex
    with get_session() as s:
        s.add(
            ClassificationRow(
                id=rid,
                created_at=created_at or datetime.now(timezone.utc),
                filename=filename,
                primary_category=Category.receipt.value,
                confidence=confidence,
                ocr_text="",
                image_path=None,
                tenant_id=tenant_id,
                label=None,
                tags=tags,
                pinned=pinned,
            )
        )
        s.commit()
    return rid


def test_export_csv_default(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    base = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    _seed("a.png", ["finance"], created_at=base)
    _seed("b.png", ["finance"], created_at=base + timedelta(days=1))
    _seed("c.png", ["ops"], created_at=base + timedelta(days=2))

    r = c.get(
        "/v1/history/tags/finance/items/export",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "shotclassify-tag-finance-items-" in r.headers["content-disposition"]
    assert r.headers["x-record-count"] == "2"
    assert r.headers["x-total-matched"] == "2"
    assert r.headers["x-truncated"] == "false"

    reader = csv.DictReader(io.StringIO(r.text))
    rows = list(reader)
    assert {row["filename"] for row in rows} == {"a.png", "b.png"}
    assert "id" in reader.fieldnames
    assert "tags" in reader.fieldnames


def test_export_json_payload(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"], pinned=True)
    _seed("b.png", ["finance"], pinned=False)

    r = c.get(
        "/v1/history/tags/finance/items/export?format=json",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = json.loads(r.text)
    assert body["tag"] == "finance"
    assert body["count"] == 2
    assert body["total_matched"] == 2
    assert body["truncated"] is False
    assert body["filters"]["pinned"] is None
    assert {rec["filename"] for rec in body["records"]} == {"a.png", "b.png"}


def test_export_ndjson(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"])
    _seed("b.png", ["finance"])

    r = c.get(
        "/v1/history/tags/finance/items/export?format=ndjson",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    lines = [ln for ln in r.text.splitlines() if ln.strip()]
    assert len(lines) == 2
    for ln in lines:
        rec = json.loads(ln)
        assert rec["filename"] in {"a.png", "b.png"}


def test_export_pinned_filter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("p1.png", ["finance"], pinned=True)
    _seed("p2.png", ["finance"], pinned=True)
    _seed("u1.png", ["finance"], pinned=False)

    r = c.get(
        "/v1/history/tags/finance/items/export?format=json&pinned=true",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = json.loads(r.text)
    assert body["count"] == 2
    assert {rec["filename"] for rec in body["records"]} == {"p1.png", "p2.png"}

    r = c.get(
        "/v1/history/tags/finance/items/export?format=json&pinned=false",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = json.loads(r.text)
    assert body["count"] == 1
    assert body["records"][0]["filename"] == "u1.png"


def test_export_truncation_headers(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    base = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(5):
        _seed(f"f{i}.png", ["finance"], created_at=base + timedelta(minutes=i))

    r = c.get(
        "/v1/history/tags/finance/items/export?format=ndjson&limit=2&offset=0",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    assert r.headers["x-record-count"] == "2"
    assert r.headers["x-total-matched"] == "5"
    assert r.headers["x-truncated"] == "true"
    assert r.headers["x-next-offset"] == "2"


def test_export_unknown_tag_returns_empty(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"])

    r = c.get(
        "/v1/history/tags/nope/items/export?format=json",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = json.loads(r.text)
    assert body["count"] == 0
    assert body["records"] == []


def test_export_tenant_isolation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"], tenant_id="acme")
    _seed("b.png", ["finance"], tenant_id="other")

    r = c.get(
        "/v1/history/tags/finance/items/export?format=json",
        headers={"X-API-Key": "k", "X-Tenant": "acme"},
    )
    assert r.status_code == 200
    body = json.loads(r.text)
    assert [rec["filename"] for rec in body["records"]] == ["a.png"]


def test_export_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/history/tags/finance/items/export")
    assert r.status_code in (401, 403)


def test_export_bad_format_rejected(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/history/tags/finance/items/export?format=xml",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 422


def test_export_filename_sanitized(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["weird tag!"])

    # Spaces and punctuation in the tag must be scrubbed before they hit
    # the Content-Disposition filename so the download lands cleanly.
    r = c.get(
        "/v1/history/tags/weird%20tag%21/items/export",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    fname = r.headers["content-disposition"].split("filename=")[1]
    for ch in (" ", "!", "/", "\\"):
        assert ch not in fname


def test_export_confidence_band_filter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("low.png", ["finance"], confidence=0.2)
    _seed("mid.png", ["finance"], confidence=0.5)
    _seed("high.png", ["finance"], confidence=0.9)

    r = c.get(
        "/v1/history/tags/finance/items/export?format=json&max_conf=0.4",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = json.loads(r.text)
    assert [rec["filename"] for rec in body["records"]] == ["low.png"]
    assert body["filters"]["max_conf"] == 0.4
    assert body["filters"]["min_conf"] is None

    r = c.get(
        "/v1/history/tags/finance/items/export?format=json&min_conf=0.4&max_conf=0.8",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    body = json.loads(r.text)
    assert [rec["filename"] for rec in body["records"]] == ["mid.png"]

    # Inverted range rejected.
    r = c.get(
        "/v1/history/tags/finance/items/export?min_conf=0.9&max_conf=0.1",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 400
