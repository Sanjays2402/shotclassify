"""Confidence band filter on GET /v1/history/tags and /v1/history/tags/export."""
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


def _seed(filename: str, tags: list[str], confidence: float) -> None:
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


def _seed_corpus() -> None:
    # low-confidence row: finance + draft
    _seed("low.png", ["finance", "draft"], 0.3)
    # mid-confidence row: finance + q1
    _seed("mid.png", ["finance", "q1"], 0.6)
    # high-confidence row: finance + ops
    _seed("hi.png", ["finance", "ops"], 0.95)


def _counts(items: list[dict]) -> dict[str, int]:
    return {it["tag"]: it["count"] for it in items}


def test_tags_endpoint_min_conf_filters_to_high_band(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_corpus()

    r = c.get("/v1/history/tags?min_conf=0.8", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    counts = _counts(r.json()["items"])
    # Only the high-confidence row contributes.
    assert counts == {"finance": 1, "ops": 1}


def test_tags_endpoint_max_conf_filters_to_low_band(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_corpus()

    r = c.get("/v1/history/tags?max_conf=0.5", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    counts = _counts(r.json()["items"])
    # Only the low-confidence row contributes.
    assert counts == {"finance": 1, "draft": 1}


def test_tags_endpoint_band_filters_to_mid(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_corpus()

    r = c.get(
        "/v1/history/tags?min_conf=0.5&max_conf=0.7",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200, r.text
    counts = _counts(r.json()["items"])
    assert counts == {"finance": 1, "q1": 1}


def test_tags_endpoint_inverted_band_rejected(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_corpus()

    r = c.get(
        "/v1/history/tags?min_conf=0.9&max_conf=0.1",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 400


def test_tags_endpoint_out_of_range_rejected_by_route(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_corpus()

    r = c.get("/v1/history/tags?min_conf=1.5", headers={"X-API-Key": "k"})
    assert r.status_code == 422


def test_tags_endpoint_omit_returns_all(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_corpus()

    r = c.get("/v1/history/tags", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    counts = _counts(r.json()["items"])
    assert counts == {"finance": 3, "draft": 1, "q1": 1, "ops": 1}


def test_tags_export_csv_honours_confidence_band(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_corpus()

    r = c.get(
        "/v1/history/tags/export?format=csv&max_conf=0.5",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200, r.text
    reader = csv.DictReader(io.StringIO(r.text))
    rows = list(reader)
    got = {row["tag"]: int(row["count"]) for row in rows}
    assert got == {"finance": 1, "draft": 1}


def test_tags_export_json_echoes_band_filters(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_corpus()

    r = c.get(
        "/v1/history/tags/export?format=json&min_conf=0.5&max_conf=0.7",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200, r.text
    body = json.loads(r.text)
    assert body["filters"]["min_conf"] == 0.5
    assert body["filters"]["max_conf"] == 0.7
    got = {it["tag"]: it["count"] for it in body["items"]}
    assert got == {"finance": 1, "q1": 1}
