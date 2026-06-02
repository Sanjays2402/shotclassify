"""Bulk delete for saved views: POST /v1/saved-views/bulk-delete."""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import create_app


HEADERS = {"x-api-key": "k"}


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'svbd.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def _make(c, name):
    r = c.post(
        "/v1/saved-views",
        json={"name": name, "filters": {"category": "receipt"}},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_bulk_delete_round_trip(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    ids = [_make(c, f"v{i}") for i in range(3)]
    keep = _make(c, "keep")

    target = ids[:2] + ["does-not-exist"]
    r = c.post(
        "/v1/saved-views/bulk-delete",
        json={"ids": target},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["deleted"]) == sorted(ids[:2])
    assert body["count"] == 2
    assert "does-not-exist" in body["not_found"]
    assert body["requested"] == 3

    # Survivors still present.
    listing = c.get("/v1/saved-views", headers=HEADERS).json()
    surviving = {r["id"] for r in listing["items"]}
    assert ids[2] in surviving
    assert keep in surviving
    assert ids[0] not in surviving and ids[1] not in surviving


def test_bulk_delete_dry_run_does_not_mutate(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    ids = [_make(c, f"v{i}") for i in range(2)]

    r = c.post(
        "/v1/saved-views/bulk-delete?dry_run=true",
        json={"ids": ids + ["missing"]},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("dry_run") is True
    plan = body["would_delete"]
    assert sorted(plan["ids"]) == sorted(ids)
    assert plan["count"] == 2
    assert "missing" in plan["not_found"]

    # Nothing actually deleted.
    listing = c.get("/v1/saved-views", headers=HEADERS).json()
    assert listing["count"] == 2


def test_bulk_delete_validation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    r = c.post("/v1/saved-views/bulk-delete", json={}, headers=HEADERS)
    assert r.status_code == 422

    r = c.post("/v1/saved-views/bulk-delete", json={"ids": []}, headers=HEADERS)
    assert r.status_code == 422

    r = c.post(
        "/v1/saved-views/bulk-delete",
        json={"ids": ["ok", "  "]},
        headers=HEADERS,
    )
    assert r.status_code == 422

    r = c.post(
        "/v1/saved-views/bulk-delete",
        json={"ids": [f"x{i}" for i in range(201)]},
        headers=HEADERS,
    )
    assert r.status_code == 422


def test_bulk_delete_dedups_ids(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    vid = _make(c, "only")

    r = c.post(
        "/v1/saved-views/bulk-delete",
        json={"ids": [vid, vid, vid]},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == [vid]
    assert body["count"] == 1
    # Deduped before processing, so requested counts unique ids.
    assert body["requested"] == 1
