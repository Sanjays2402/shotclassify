"""Tests for /auth/whoami used by the web sign-in UI."""
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


def test_whoami_anonymous_is_unauthorized(monkeypatch, tmp_path):
    # Anonymous /auth/whoami is rejected by auth middleware; the web proxy
    # translates this into {principal: null} for the UI.
    c = _client(monkeypatch, tmp_path)
    r = c.get("/auth/whoami")
    assert r.status_code in (401, 403)


def test_whoami_with_api_key_returns_principal(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/auth/whoami", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    body = r.json()
    # API-key auth should populate request.state.principal to something truthy
    assert body.get("principal")


def test_logout_clears_cookie(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post("/auth/logout", follow_redirects=False)
    # logout returns a redirect and clears the cookie
    assert r.status_code in (200, 303)
    set_cookie = r.headers.get("set-cookie", "")
    assert "sc_session" in set_cookie
