"""Validation tests for inverted filter ranges on /v1/history.

An inverted range (``min_conf > max_conf`` or ``since > until``) can never
match a row. Returning an empty list there is indistinguishable from "no
results" and burns real debug time on the caller's side, so the API rejects
the request with a 400 instead.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'api.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def test_list_rejects_inverted_confidence_range(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/history?min_conf=0.9&max_conf=0.1",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 400
    assert "min_conf" in r.json()["detail"]


def test_list_rejects_inverted_date_range(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/history?since=2025-01-02T00:00:00Z&until=2025-01-01T00:00:00Z",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 400
    assert "since" in r.json()["detail"]


def test_export_rejects_inverted_confidence_range(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/history/export?format=json&min_conf=0.8&max_conf=0.2",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 400


def test_export_rejects_inverted_date_range(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/history/export?format=csv"
        "&since=2025-06-01T00:00:00Z&until=2025-01-01T00:00:00Z",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 400


def test_list_accepts_equal_endpoints(monkeypatch, tmp_path):
    """``min == max`` and ``since == until`` are valid (degenerate but legal)."""
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/history?min_conf=0.5&max_conf=0.5",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    r = c.get(
        "/v1/history?since=2025-01-01T00:00:00Z&until=2025-01-01T00:00:00Z",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200


def test_list_accepts_one_sided_range(monkeypatch, tmp_path):
    """A single bound must still be honoured; the guard only fires when both sides are set."""
    c = _client(monkeypatch, tmp_path)
    for qs in ("min_conf=0.9", "max_conf=0.1", "since=2025-01-01T00:00:00Z", "until=2025-01-01T00:00:00Z"):
        r = c.get(f"/v1/history?{qs}", headers={"X-API-Key": "k"})
        assert r.status_code == 200, (qs, r.text)
