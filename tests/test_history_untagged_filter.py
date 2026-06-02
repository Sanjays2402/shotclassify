"""GET /v1/history?untagged=true|false filter.

Covers the unlabeled-queue UI: surface rows that still need tagging
(``untagged=true``) or only rows that have been tagged at least once
(``untagged=false``). Empty list and NULL both count as untagged.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from services.api.app.main import create_app
from shotclassify_common import Category


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'untagged.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def _seed(rows: list[tuple[str, list[str] | None]]) -> None:
    from shotclassify_store.db import ClassificationRow, get_session, init_db

    init_db()
    with get_session() as s:
        for rid, tags in rows:
            s.add(
                ClassificationRow(
                    id=rid,
                    created_at=datetime.now(timezone.utc),
                    filename=f"{rid}.png",
                    primary_category=Category.receipt.value,
                    confidence=0.9,
                    ocr_text="hello",
                    image_path=None,
                    tenant_id=None,
                    tags=tags,
                )
            )
        s.commit()


HEADERS = {"x-api-key": "k"}


def test_untagged_true_returns_null_and_empty_list(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed(
        [
            ("a", None),          # NULL
            ("b", []),            # empty list
            ("c", ["finance"]),   # tagged
            ("d", ["q1", "ops"]),
        ]
    )

    res = c.get("/v1/history?untagged=true", headers=HEADERS)
    assert res.status_code == 200, res.text
    items = res.json()
    assert {i["id"] for i in items} == {"a", "b"}
    assert res.headers["x-total-count"] == "2"


def test_untagged_false_returns_only_tagged(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed(
        [
            ("a", None),
            ("b", []),
            ("c", ["finance"]),
            ("d", ["q1", "ops"]),
        ]
    )

    res = c.get("/v1/history?untagged=false", headers=HEADERS)
    assert res.status_code == 200, res.text
    items = res.json()
    assert {i["id"] for i in items} == {"c", "d"}
    assert res.headers["x-total-count"] == "2"


def test_untagged_omitted_returns_all(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed([("a", None), ("b", []), ("c", ["finance"])])
    res = c.get("/v1/history", headers=HEADERS)
    assert res.status_code == 200
    assert {i["id"] for i in res.json()} == {"a", "b", "c"}


def test_untagged_combines_with_tag_filter_is_empty(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed([("a", None), ("c", ["finance"])])
    # untagged=true AND tag=finance is logically empty.
    res = c.get("/v1/history?untagged=true&tag=finance", headers=HEADERS)
    assert res.status_code == 200
    assert res.json() == []
    assert res.headers["x-total-count"] == "0"


def test_untagged_export_csv_and_json(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed([("a", None), ("b", []), ("c", ["finance"])])

    res = c.get("/v1/history/export?format=json&untagged=true", headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == 2
    assert body["total_matched"] == 2
    assert body["filters"]["untagged"] is True
    assert {r["id"] for r in body["records"]} == {"a", "b"}

    res = c.get("/v1/history/export?format=csv&untagged=false", headers=HEADERS)
    assert res.status_code == 200
    assert res.headers["x-record-count"] == "1"
    assert res.headers["x-total-matched"] == "1"
    text = res.text
    assert "c.png" in text
    assert "a.png" not in text
