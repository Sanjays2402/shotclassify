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


def test_history_export_ndjson_empty(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/history/export?format=ndjson", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd and ".ndjson" in cd
    assert r.headers["x-record-count"] == "0"
    assert r.text == ""


def test_history_export_ndjson_one_line_per_record(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_one("a.png", 0.91)
    _seed_one("b.png", 0.55)

    r = c.get("/v1/history/export?format=ndjson", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    assert r.headers["x-record-count"] == "2"
    lines = [ln for ln in r.text.split("\n") if ln]
    assert len(lines) == 2
    # Each line must be standalone JSON (no wrapper object, no trailing comma).
    parsed = [json.loads(ln) for ln in lines]
    filenames = {p["filename"] for p in parsed}
    assert filenames == {"a.png", "b.png"}
    for p in parsed:
        assert "id" in p and "primary_category" in p and "confidence" in p


def test_history_export_signals_truncation(monkeypatch, tmp_path):
    """When the row count beats ``limit`` the export must flag truncation
    so the caller can paginate or widen the filter instead of silently
    shipping a partial download."""
    c = _client(monkeypatch, tmp_path)
    for i in range(5):
        _seed_one(f"shot-{i}.png", 0.5 + i * 0.05)

    # Cap below the matching count.
    r = c.get(
        "/v1/history/export?format=csv&limit=2",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    assert r.headers["x-record-count"] == "2"
    assert r.headers["x-total-matched"] == "5"
    assert r.headers["x-truncated"] == "true"

    # JSON body mirrors the headers so a downstream tool sees the same
    # truncation signal whether it inspects body or headers.
    r = c.get(
        "/v1/history/export?format=json&limit=2",
        headers={"X-API-Key": "k"},
    )
    body = json.loads(r.text)
    assert body["count"] == 2
    assert body["total_matched"] == 5
    assert body["truncated"] is True
    assert r.headers["x-truncated"] == "true"

    # NDJSON only carries the signal in headers (no wrapper object exists).
    r = c.get(
        "/v1/history/export?format=ndjson&limit=2",
        headers={"X-API-Key": "k"},
    )
    assert r.headers["x-truncated"] == "true"
    assert r.headers["x-total-matched"] == "5"


def test_history_export_truncated_false_when_full_set_fits(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_one("only.png", 0.7)

    r = c.get(
        "/v1/history/export?format=json&limit=50",
        headers={"X-API-Key": "k"},
    )
    body = json.loads(r.text)
    assert body["count"] == 1
    assert body["total_matched"] == 1
    assert body["truncated"] is False
    assert r.headers["x-truncated"] == "false"


def test_history_export_offset_paginates_through_truncated_set(monkeypatch, tmp_path):
    """`offset` lets a caller resume a truncated export. Walking the pages
    yields every row exactly once with no overlap or gap, and the last
    page reports truncated=false with no next_offset."""
    c = _client(monkeypatch, tmp_path)
    for i in range(5):
        _seed_one(f"shot-{i}.png", 0.5 + i * 0.05)

    # Page 1: rows 0..1 of 5. Headers expose the next cursor.
    r1 = c.get(
        "/v1/history/export?format=json&limit=2&offset=0",
        headers={"X-API-Key": "k"},
    )
    assert r1.status_code == 200
    b1 = json.loads(r1.text)
    assert b1["count"] == 2
    assert b1["offset"] == 0
    assert b1["total_matched"] == 5
    assert b1["truncated"] is True
    assert b1["next_offset"] == 2
    assert r1.headers["x-offset"] == "0"
    assert r1.headers["x-next-offset"] == "2"
    assert r1.headers["x-truncated"] == "true"

    # Page 2: rows 2..3.
    r2 = c.get(
        "/v1/history/export?format=json&limit=2&offset=2",
        headers={"X-API-Key": "k"},
    )
    b2 = json.loads(r2.text)
    assert b2["offset"] == 2
    assert b2["next_offset"] == 4
    assert b2["truncated"] is True

    # Page 3: row 4 only, end of set. No next cursor, not truncated.
    r3 = c.get(
        "/v1/history/export?format=json&limit=2&offset=4",
        headers={"X-API-Key": "k"},
    )
    b3 = json.loads(r3.text)
    assert b3["count"] == 1
    assert b3["offset"] == 4
    assert b3["truncated"] is False
    assert b3["next_offset"] is None
    assert "x-next-offset" not in r3.headers
    assert r3.headers["x-truncated"] == "false"

    # Coverage + uniqueness across pages.
    ids = [rec["id"] for rec in b1["records"] + b2["records"] + b3["records"]]
    assert len(ids) == 5
    assert len(set(ids)) == 5


def test_history_export_offset_works_for_csv_and_ndjson(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    for i in range(4):
        _seed_one(f"row-{i}.png", 0.6 + i * 0.05)

    # CSV: offset=2, limit=2 -> 2 data rows, x-offset header set.
    r = c.get(
        "/v1/history/export?format=csv&limit=2&offset=2",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    assert r.headers["x-record-count"] == "2"
    assert r.headers["x-offset"] == "2"
    assert r.headers["x-total-matched"] == "4"
    assert r.headers["x-truncated"] == "false"
    reader = csv.reader(io.StringIO(r.text))
    rows = list(reader)
    assert len(rows) == 1 + 2  # header + 2 data rows

    # NDJSON exposes the same cursor headers.
    r = c.get(
        "/v1/history/export?format=ndjson&limit=2&offset=0",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    assert r.headers["x-offset"] == "0"
    assert r.headers["x-next-offset"] == "2"
    assert r.headers["x-truncated"] == "true"
    lines = [ln for ln in r.text.splitlines() if ln.strip()]
    assert len(lines) == 2
