"""Delete a saved view by name: DELETE /v1/saved-views/by-name/{name}."""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import create_app


HEADERS = {"x-api-key": "k"}


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'svdbn.db'}")
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


def test_delete_by_name_removes_the_view(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    vid = _make(c, "Receipts Q3")
    _make(c, "Invoices")

    r = c.delete("/v1/saved-views/by-name/Receipts Q3", headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["id"] == vid
    assert body["name"] == "Receipts Q3"

    # Lookup now misses, and id-route also 404s.
    assert c.get("/v1/saved-views/by-name/Receipts Q3", headers=HEADERS).status_code == 404
    assert c.get(f"/v1/saved-views/{vid}", headers=HEADERS).status_code == 404
    # The other view is untouched.
    assert c.get("/v1/saved-views/by-name/Invoices", headers=HEADERS).status_code == 200


def test_delete_by_name_is_case_insensitive_and_trims(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    vid = _make(c, "Receipts Q3")

    r = c.delete("/v1/saved-views/by-name/  receipts q3  ", headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == vid


def test_delete_by_name_missing_returns_404(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _make(c, "Receipts")

    r = c.delete("/v1/saved-views/by-name/Nope", headers=HEADERS)
    assert r.status_code == 404


def test_delete_by_name_dry_run_does_not_mutate(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    vid = _make(c, "Receipts")

    r = c.delete(
        "/v1/saved-views/by-name/Receipts?dry_run=true", headers=HEADERS
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("dry_run") is True
    assert body.get("would_delete", {}).get("id") == vid

    # The view still exists after a dry run.
    r2 = c.get(f"/v1/saved-views/{vid}", headers=HEADERS)
    assert r2.status_code == 200
