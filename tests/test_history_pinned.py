"""Pin/unpin a saved classification.

Covers:
  * PATCH /v1/history/{id} body `pinned` toggle.
  * GET /v1/history?pinned=true filter.
  * POST /v1/history/bulk with action `pin` / `unpin`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from services.api.app.main import create_app
from shotclassify_common import Category


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'pin.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def _seed(ids: list[str]) -> None:
    from shotclassify_store.db import ClassificationRow, get_session, init_db

    init_db()
    with get_session() as s:
        for rid in ids:
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
                )
            )
        s.commit()


HEADERS = {"x-api-key": "k"}


def test_patch_pinned_toggle_and_filter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed(["a", "b", "c"])

    # Default is unpinned.
    res = c.get("/v1/history", headers=HEADERS)
    assert res.status_code == 200
    items = res.json()
    assert {i["id"] for i in items} == {"a", "b", "c"}
    assert all(i["pinned"] is False for i in items)

    # Pin one.
    res = c.patch("/v1/history/a", json={"pinned": True}, headers=HEADERS)
    assert res.status_code == 200, res.text
    assert res.json()["pinned"] is True

    # Filter pinned only.
    res = c.get("/v1/history?pinned=true", headers=HEADERS)
    assert res.status_code == 200
    items = res.json()
    assert [i["id"] for i in items] == ["a"]
    assert res.headers["x-total-count"] == "1"

    # Filter pinned=false returns the other two.
    res = c.get("/v1/history?pinned=false", headers=HEADERS)
    assert {i["id"] for i in res.json()} == {"b", "c"}

    # Unpin returns it to the unpinned set.
    res = c.patch("/v1/history/a", json={"pinned": False}, headers=HEADERS)
    assert res.status_code == 200
    assert res.json()["pinned"] is False
    res = c.get("/v1/history?pinned=true", headers=HEADERS)
    assert res.json() == []


def test_bulk_pin_and_unpin(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed(["a", "b", "c"])

    res = c.post(
        "/v1/history/bulk",
        json={"ids": ["a", "b", "missing"], "action": "pin"},
        headers=HEADERS,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["affected"] == 2
    assert body["missing"] == ["missing"]

    res = c.get("/v1/history?pinned=true", headers=HEADERS)
    assert {i["id"] for i in res.json()} == {"a", "b"}

    # Pinning again is a no-op (affected stays 0 for already-pinned rows).
    res = c.post(
        "/v1/history/bulk",
        json={"ids": ["a"], "action": "pin"},
        headers=HEADERS,
    )
    assert res.json()["affected"] == 0

    res = c.post(
        "/v1/history/bulk",
        json={"ids": ["a", "b"], "action": "unpin"},
        headers=HEADERS,
    )
    assert res.json()["affected"] == 2
    res = c.get("/v1/history?pinned=true", headers=HEADERS)
    assert res.json() == []


def test_patch_rejects_non_bool_pinned(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed(["a"])
    res = c.patch("/v1/history/a", json={"pinned": "yes"}, headers=HEADERS)
    assert res.status_code == 400
