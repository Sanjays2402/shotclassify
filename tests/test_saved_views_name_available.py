"""Preflight name availability: GET /v1/saved-views/name-available."""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import create_app


HEADERS = {"x-api-key": "k"}


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'svna.db'}")
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


def test_available_when_unused(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/saved-views/name-available",
        params={"name": "Receipts Q3"},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True
    assert body["normalized"] == "Receipts Q3"
    assert "reason" not in body


def test_unavailable_when_taken_case_and_whitespace_insensitive(
    monkeypatch, tmp_path
):
    c = _client(monkeypatch, tmp_path)
    _make(c, "Receipts Q3")

    r = c.get(
        "/v1/saved-views/name-available",
        params={"name": "  receipts   q3  "},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is False
    assert body["reason"] == "duplicate"
    # Server normalizes the same way create does (trim + collapse spaces).
    assert body["normalized"] == "receipts q3"


def test_empty_name_returns_422(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/saved-views/name-available",
        params={"name": "   "},
        headers=HEADERS,
    )
    assert r.status_code == 422


def test_too_long_name_returns_422(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/saved-views/name-available",
        params={"name": "x" * 200},
        headers=HEADERS,
    )
    assert r.status_code == 422


def test_does_not_shadow_view_id_route(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    vid = _make(c, "Receipts")
    r = c.get(f"/v1/saved-views/{vid}", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["name"] == "Receipts"


def test_preflight_matches_create_decision(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _make(c, "Invoices")

    # Preflight says taken...
    r = c.get(
        "/v1/saved-views/name-available",
        params={"name": "invoices"},
        headers=HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["available"] is False

    # ...and create actually rejects with 409.
    r2 = c.post(
        "/v1/saved-views",
        json={"name": "invoices", "filters": {}},
        headers=HEADERS,
    )
    assert r2.status_code == 409
