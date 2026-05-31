"""Server-side session tracking: revoke, force-logout, isolation.

Covers:

* Issuing a session writes a row that ``read_session`` will accept.
* ``read_session`` rejects a cookie whose backing session row was revoked,
  which is the property that lets ``/v1/sessions`` actually log a stolen
  device out instead of being a pure UI flourish.
* Cross-principal isolation: principal A cannot revoke (or even probe)
  principal B's session id, which is the cross-tenant safety promise the
  admin console depends on.
* ``revoke_all_for_principal`` invalidates every active session but
  honors ``except_sid`` so "log out everywhere else" leaves the caller
  signed in.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _reset(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'sessions.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()


def _client(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    from services.api.app.main import create_app

    return TestClient(create_app())


def _issue(login: str):
    """Mint a server-side session and return ``(cookie, sid)``."""
    from shotclassify_store import init_db
    from services.api.app.middleware.auth import issue_session

    init_db()
    return issue_session(login, client_ip="127.0.0.1", user_agent="pytest")


def test_revoked_session_cookie_is_rejected(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    cookie, sid = _issue("alice")
    # Live cookie reaches a protected route via /v1/sessions
    r = c.get("/v1/sessions", cookies={"sc_session": cookie})
    assert r.status_code == 200
    assert any(s["id"] == sid for s in r.json()["sessions"])

    # Revoke that session id; the same cookie must now be unauthorized.
    from shotclassify_store import session_store

    assert session_store.revoke(sid) is True
    r2 = c.get("/v1/sessions", cookies={"sc_session": cookie})
    assert r2.status_code == 401, "revoked session cookie must be rejected"


def test_cross_principal_session_revoke_is_blocked(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    alice_cookie, _ = _issue("alice")
    _, bob_sid = _issue("bob")

    # Alice tries to revoke Bob's session. Server returns 404 (not 403) to
    # avoid leaking the existence of bob_sid to a probing attacker.
    r = c.delete(f"/v1/sessions/{bob_sid}", cookies={"sc_session": alice_cookie})
    assert r.status_code == 404

    # And Bob's session is still active.
    from shotclassify_store import session_store

    info = session_store.get(bob_sid)
    assert info is not None and info.revoked_at is None


def test_revoke_all_keeps_current_session(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    cookie_a, sid_a = _issue("alice")
    _, sid_b = _issue("alice")
    _, sid_c = _issue("alice")

    r = c.post(
        "/v1/sessions/revoke-all",
        cookies={"sc_session": cookie_a},
    )
    assert r.status_code == 200
    assert r.json()["revoked"] == 2  # b and c, not the current one (a)

    from shotclassify_store import session_store

    assert session_store.get(sid_a).revoked_at is None
    assert session_store.get(sid_b).revoked_at is not None
    assert session_store.get(sid_c).revoked_at is not None


def test_logout_revokes_session_row(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    cookie, sid = _issue("alice")
    r = c.post("/auth/logout", cookies={"sc_session": cookie}, follow_redirects=False)
    assert r.status_code in (200, 303)
    from shotclassify_store import session_store

    info = session_store.get(sid)
    assert info is not None and info.revoked_at is not None, (
        "POST /auth/logout must revoke the server-side session row"
    )
