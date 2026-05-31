"""Per-user saved views CRUD: /v1/saved-views."""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'sv.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


HEADERS = {"x-api-key": "k"}


def test_saved_views_round_trip(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    # Empty list on first visit.
    r = c.get("/v1/saved-views", headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json() == {"items": [], "count": 0}

    # Create.
    payload = {
        "name": "  Low conf, last week ",
        "filters": {
            "category": "receipt",
            "min_conf": 0.4,
            "since": "2025-01-01",
            "sort": "conf_asc",
            "garbage": "should_drop",
            "limit": 9999,
        },
    }
    r = c.post("/v1/saved-views", json=payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["name"] == "Low conf, last week"
    f = created["filters"]
    assert "garbage" not in f
    assert f["category"] == "receipt"
    assert f["min_conf"] == 0.4
    assert f["sort"] == "conf_asc"
    assert f["limit"] == 500  # clamped to max
    view_id = created["id"]

    # Listed.
    r = c.get("/v1/saved-views", headers=HEADERS)
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == view_id

    # Bad sort dropped, valid name rewritten.
    r = c.patch(
        f"/v1/saved-views/{view_id}",
        json={"name": "Renamed", "filters": {"sort": "nope", "q": "tip"}},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["name"] == "Renamed"
    assert "sort" not in updated["filters"]
    assert updated["filters"]["q"] == "tip"

    # Delete.
    r = c.delete(f"/v1/saved-views/{view_id}", headers=HEADERS)
    assert r.status_code == 200
    r = c.get(f"/v1/saved-views/{view_id}", headers=HEADERS)
    assert r.status_code == 404


def test_saved_view_requires_name(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/saved-views",
        json={"name": "  ", "filters": {}},
        headers=HEADERS,
    )
    assert r.status_code == 422


def test_saved_view_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/saved-views")
    assert r.status_code in (401, 403)
