"""Update a saved view by name: PATCH /v1/saved-views/by-name/{name}."""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import create_app


HEADERS = {"x-api-key": "k"}


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'svubn.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def _make(c, name, filters=None):
    r = c.post(
        "/v1/saved-views",
        json={"name": name, "filters": filters or {"category": "receipt"}},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_update_by_name_renames_view(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    vid = _make(c, "Receipts")

    r = c.patch(
        "/v1/saved-views/by-name/Receipts",
        json={"name": "Receipts Q3"},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == vid
    assert body["name"] == "Receipts Q3"

    # Old name no longer resolves; new name does.
    assert c.get("/v1/saved-views/by-name/Receipts", headers=HEADERS).status_code == 404
    assert c.get("/v1/saved-views/by-name/Receipts Q3", headers=HEADERS).status_code == 200


def test_update_by_name_updates_filters(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    vid = _make(c, "Receipts")

    r = c.patch(
        "/v1/saved-views/by-name/Receipts",
        json={"filters": {"category": "invoice"}},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == vid
    assert body["filters"].get("category") == "invoice"


def test_update_by_name_is_case_insensitive_and_trims(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    vid = _make(c, "Receipts")

    r = c.patch(
        "/v1/saved-views/by-name/  receipts  ",
        json={"name": "Renamed"},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == vid


def test_update_by_name_duplicate_target_returns_409(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _make(c, "Receipts")
    _make(c, "Invoices")

    r = c.patch(
        "/v1/saved-views/by-name/Receipts",
        json={"name": "Invoices"},
        headers=HEADERS,
    )
    assert r.status_code == 409, r.text


def test_update_by_name_missing_returns_404(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _make(c, "Receipts")

    r = c.patch(
        "/v1/saved-views/by-name/Nope",
        json={"name": "Whatever"},
        headers=HEADERS,
    )
    assert r.status_code == 404


def test_update_by_name_requires_name_or_filters(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _make(c, "Receipts")

    r = c.patch(
        "/v1/saved-views/by-name/Receipts",
        json={},
        headers=HEADERS,
    )
    assert r.status_code == 422


def test_update_by_name_rejects_bad_types(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _make(c, "Receipts")

    r = c.patch(
        "/v1/saved-views/by-name/Receipts",
        json={"name": "   "},
        headers=HEADERS,
    )
    assert r.status_code == 422

    r = c.patch(
        "/v1/saved-views/by-name/Receipts",
        json={"filters": "nope"},
        headers=HEADERS,
    )
    assert r.status_code == 422
