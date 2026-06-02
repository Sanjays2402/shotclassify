"""Lookup a saved view by name: GET /v1/saved-views/by-name/{name}."""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import create_app


HEADERS = {"x-api-key": "k"}


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'svbn.db'}")
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


def test_by_name_round_trip(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    vid = _make(c, "Receipts Q3")
    _make(c, "Invoices")

    r = c.get("/v1/saved-views/by-name/Receipts Q3", headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == vid
    assert body["name"] == "Receipts Q3"


def test_by_name_is_case_insensitive_and_trims(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    vid = _make(c, "Receipts Q3")

    r = c.get("/v1/saved-views/by-name/  receipts q3  ", headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == vid


def test_by_name_missing_returns_404(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _make(c, "Receipts")

    r = c.get("/v1/saved-views/by-name/Nope", headers=HEADERS)
    assert r.status_code == 404


def test_by_name_does_not_collide_with_id_route(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    vid = _make(c, "Receipts")

    # /{view_id} still works.
    r = c.get(f"/v1/saved-views/{vid}", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["name"] == "Receipts"
