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


def test_saved_view_persists_extended_filters(monkeypatch, tmp_path):
    """max_conf, pinned, and multi-tag filters round-trip on save.

    These keys were added to the history list/export route but were not in
    the saved-views whitelist, so a view created from a UI that exposed them
    would silently drop those filters on replay.
    """
    c = _client(monkeypatch, tmp_path)
    payload = {
        "name": "Pinned high-conf Q1",
        "filters": {
            "min_conf": 0.6,
            "max_conf": 0.95,
            "pinned": True,
            "tags": ["Finance", "finance", "  Q1 ", "", "x" * 64],
        },
    }
    r = c.post("/v1/saved-views", json=payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    f = r.json()["filters"]
    assert f["min_conf"] == 0.6
    assert f["max_conf"] == 0.95
    assert f["pinned"] is True
    # Dedup on lowercase, trim, drop empties and oversized tags.
    assert f["tags"] == ["finance", "q1"]


def test_saved_view_drops_inverted_conf_range(monkeypatch, tmp_path):
    """An inverted min/max range never reaches the row."""
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/saved-views",
        json={
            "name": "bad range",
            "filters": {"min_conf": 0.9, "max_conf": 0.1, "pinned": False},
        },
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    f = r.json()["filters"]
    assert f["min_conf"] == 0.9
    assert "max_conf" not in f
    # ``pinned=False`` is a real filter, not a synonym for "unset".
    assert f["pinned"] is False


def test_saved_view_rejects_duplicate_name(monkeypatch, tmp_path):
    """Re-saving under the same name returns 409 instead of cloning the row.

    Without this guard, re-clicking "Save view" on the same filters spawns
    identical-looking entries in the sidebar that the user then has to clean
    up by hand. Match is case-insensitive and whitespace-normalised so
    ``"Q1 review"`` and ``"q1   review"`` collide.
    """
    c = _client(monkeypatch, tmp_path)
    base = {"name": "Q1 review", "filters": {"min_conf": 0.7}}
    r = c.post("/v1/saved-views", json=base, headers=HEADERS)
    assert r.status_code == 200, r.text
    first_id = r.json()["id"]

    r = c.post(
        "/v1/saved-views",
        json={"name": "q1   review", "filters": {"min_conf": 0.7}},
        headers=HEADERS,
    )
    assert r.status_code == 409, r.text
    assert "already exists" in r.json()["detail"]

    # Still exactly one row for this principal.
    r = c.get("/v1/saved-views", headers=HEADERS)
    assert r.json()["count"] == 1

    # Renaming a different view onto an existing name also collides.
    r = c.post(
        "/v1/saved-views",
        json={"name": "other", "filters": {}},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    other_id = r.json()["id"]
    r = c.patch(
        f"/v1/saved-views/{other_id}",
        json={"name": "Q1 REVIEW"},
        headers=HEADERS,
    )
    assert r.status_code == 409, r.text

    # Renaming the original to its own name (case/whitespace variant) is a noop, not a conflict.
    r = c.patch(
        f"/v1/saved-views/{first_id}",
        json={"name": "Q1   Review"},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Q1 Review"
