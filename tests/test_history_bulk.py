"""POST /v1/history/bulk for delete + tag actions."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from services.api.app.main import create_app
from shotclassify_common import Category


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'bulk.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def _seed(ids):
    from shotclassify_store.db import ClassificationRow, get_session, init_db

    init_db()
    with get_session() as s:
        for i, rid in enumerate(ids):
            s.add(
                ClassificationRow(
                    id=rid,
                    created_at=datetime.now(timezone.utc),
                    filename=f"{rid}.png",
                    primary_category=Category.receipt.value,
                    confidence=0.9,
                    ocr_text="x",
                    image_path=None,
                    tenant_id=None,
                )
            )
        s.commit()


HEADERS = {"x-api-key": "k"}


def test_bulk_tag_add_and_remove(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed(["a", "b", "c"])

    res = c.post(
        "/v1/history/bulk",
        json={"ids": ["a", "b", "missing"], "action": "tag_add", "tags": ["Finance", "FINANCE", "Reviewed"]},
        headers=HEADERS,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["action"] == "tag_add"
    assert body["affected"] == 2
    assert body["missing"] == ["missing"]
    assert sorted(body["tags"]) == ["finance", "reviewed"]

    # Verify tags landed
    got = c.get("/v1/history/a", headers=HEADERS).json()
    assert sorted(got["tags"]) == ["finance", "reviewed"]

    # tag_remove
    res = c.post(
        "/v1/history/bulk",
        json={"ids": ["a", "b"], "action": "tag_remove", "tags": ["finance"]},
        headers=HEADERS,
    )
    assert res.status_code == 200
    assert res.json()["affected"] == 2
    got = c.get("/v1/history/a", headers=HEADERS).json()
    assert got["tags"] == ["reviewed"]


def test_bulk_delete(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed(["x", "y", "z"])

    res = c.post(
        "/v1/history/bulk",
        json={"ids": ["x", "y"], "action": "delete"},
        headers=HEADERS,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["affected"] == 2
    assert body["missing"] == []

    assert c.get("/v1/history/x", headers=HEADERS).status_code == 404
    assert c.get("/v1/history/z", headers=HEADERS).status_code == 200


def test_bulk_validation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed(["a"])

    # empty ids
    assert c.post("/v1/history/bulk", json={"ids": [], "action": "delete"}, headers=HEADERS).status_code == 400
    # bad action
    assert c.post("/v1/history/bulk", json={"ids": ["a"], "action": "nuke"}, headers=HEADERS).status_code == 400
    # tag action without tags
    assert c.post("/v1/history/bulk", json={"ids": ["a"], "action": "tag_add"}, headers=HEADERS).status_code == 400
