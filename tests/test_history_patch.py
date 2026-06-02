"""PATCH /v1/history/{id} for label + tag editing."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from services.api.app.main import create_app
from shotclassify_common import Category


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'patch.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def _seed_one(rid: str = "shot-1"):
    from shotclassify_store.db import ClassificationRow, get_session, init_db

    init_db()
    with get_session() as s:
        s.add(
            ClassificationRow(
                id=rid,
                created_at=datetime.now(timezone.utc),
                filename="raw.png",
                primary_category=Category.receipt.value,
                confidence=0.91,
                ocr_text="receipt text",
                image_path=None,
                tenant_id=None,
            )
        )
        s.commit()


HEADERS = {"x-api-key": "k"}


def test_patch_rename_and_tag(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_one()

    res = c.patch(
        "/v1/history/shot-1",
        json={"label": "Q3 Receipts", "tags": ["Finance", "finance", "Reviewed"]},
        headers=HEADERS,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["label"] == "Q3 Receipts"
    assert body["tags"] == ["finance", "reviewed"]

    # Tag filter on list returns the renamed record.
    res = c.get("/v1/history?tag=finance", headers=HEADERS)
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["id"] == "shot-1"
    assert rows[0]["label"] == "Q3 Receipts"

    # Unknown tag returns empty.
    res = c.get("/v1/history?tag=nope", headers=HEADERS)
    assert res.status_code == 200
    assert res.json() == []


def test_patch_clear_label(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_one("shot-2")

    c.patch("/v1/history/shot-2", json={"label": "temp"}, headers=HEADERS)
    res = c.patch("/v1/history/shot-2", json={"label": None}, headers=HEADERS)
    assert res.status_code == 200
    assert res.json()["label"] is None


def test_patch_rejects_unknown_fields(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_one("shot-3")
    res = c.patch(
        "/v1/history/shot-3", json={"primary_category": "meme"}, headers=HEADERS
    )
    assert res.status_code == 400


def test_patch_404(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    res = c.patch("/v1/history/missing", json={"label": "x"}, headers=HEADERS)
    assert res.status_code == 404


def test_patch_rejects_bad_tags(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_one("shot-4")
    res = c.patch(
        "/v1/history/shot-4", json={"tags": [1, 2, 3]}, headers=HEADERS
    )
    assert res.status_code == 400


def test_patch_rejects_too_many_tags(monkeypatch, tmp_path):
    # The store caps tags at 16 per record. Sending more should be a clean
    # 400 with the real cap in the message, not a silent truncation and
    # not a misleading "max 16 kept" while accepting up to 64.
    c = _client(monkeypatch, tmp_path)
    _seed_one("shot-5")
    too_many = [f"t{i}" for i in range(17)]
    res = c.patch(
        "/v1/history/shot-5", json={"tags": too_many}, headers=HEADERS
    )
    assert res.status_code == 400, res.text
    assert "16" in res.json()["detail"]

    # Boundary: exactly 16 is accepted and persisted in full.
    sixteen = [f"t{i}" for i in range(16)]
    res = c.patch(
        "/v1/history/shot-5", json={"tags": sixteen}, headers=HEADERS
    )
    assert res.status_code == 200, res.text
    assert len(res.json()["tags"]) == 16
