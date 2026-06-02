"""Quota endpoint: /v1/saved-views/quota."""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import create_app
from shotclassify_store.saved_views import PER_USER_MAX


HEADERS = {"x-api-key": "k"}


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


def test_quota_empty(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/saved-views/quota", headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "used": 0,
        "limit": PER_USER_MAX,
        "remaining": PER_USER_MAX,
        "at_limit": False,
    }


def test_quota_tracks_creates_and_deletes(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    for i in range(3):
        r = c.post(
            "/v1/saved-views",
            json={"name": f"view {i}", "filters": {"category": "receipt"}},
            headers=HEADERS,
        )
        assert r.status_code == 200, r.text

    r = c.get("/v1/saved-views/quota", headers=HEADERS)
    body = r.json()
    assert body["used"] == 3
    assert body["limit"] == PER_USER_MAX
    assert body["remaining"] == PER_USER_MAX - 3
    assert body["at_limit"] is False

    # Delete one and re-check.
    listed = c.get("/v1/saved-views", headers=HEADERS).json()["items"]
    victim = listed[0]["id"]
    assert c.delete(f"/v1/saved-views/{victim}", headers=HEADERS).status_code == 200

    body = c.get("/v1/saved-views/quota", headers=HEADERS).json()
    assert body["used"] == 2
    assert body["remaining"] == PER_USER_MAX - 2


def test_quota_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/saved-views/quota")  # no API key
    assert r.status_code in (401, 403)


def test_quota_route_does_not_shadow_view_id(monkeypatch, tmp_path):
    """A view literally named 'quota' (and the id route) must still work."""
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/saved-views",
        json={"name": "quota", "filters": {}},
        headers=HEADERS,
    )
    assert r.status_code == 200
    view_id = r.json()["id"]

    # /quota returns the quota dict, not the view row.
    body = c.get("/v1/saved-views/quota", headers=HEADERS).json()
    assert "used" in body and "limit" in body and "remaining" in body
    assert body["used"] == 1

    # The id route still resolves the view by its real id.
    got = c.get(f"/v1/saved-views/{view_id}", headers=HEADERS).json()
    assert got["id"] == view_id
    assert got["name"] == "quota"
