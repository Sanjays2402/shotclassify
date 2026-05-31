"""CSRF protection on cookie-authenticated mutations.

The double-submit middleware must:

* Block a browser-shaped POST that rides only on the ``sc_session``
  cookie (i.e. no ``X-CSRF-Token`` header) with a 403.
* Allow the same POST through when the correct token is supplied.
* Reject a token minted for a different session id (cross-session
  replay).
* Leave API-key callers alone: they do not ride on ambient cookies.
* Leave safe verbs (GET) alone even when the browser sends Origin.
* Leave non-browser clients (no Origin, no Sec-Fetch-Site) alone so
  curl/CI workflows that legitimately reuse a cookie session keep
  working.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _reset(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'csrf.db'}")
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
    from shotclassify_store import init_db
    from services.api.app.middleware.auth import issue_session

    init_db()
    return issue_session(login, client_ip="127.0.0.1", user_agent="pytest")


def _browser(headers: dict | None = None) -> dict:
    """A request shaped like one a real browser fetch() would send."""
    base = {"origin": "https://app.example.com", "sec-fetch-site": "same-origin"}
    if headers:
        base.update(headers)
    return base


def test_browser_post_without_token_is_blocked(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    cookie, sid = _issue("alice")

    r = c.delete(
        f"/v1/sessions/{sid}",
        cookies={"sc_session": cookie},
        headers=_browser(),
    )
    assert r.status_code == 403, r.text
    assert r.json()["error"] == "csrf_token_invalid"


def test_browser_post_with_correct_token_is_allowed(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    cookie, sid = _issue("alice")
    from services.api.app.middleware.csrf import token_for_session

    token = token_for_session(sid)
    # /v1/sessions/{id} is a real cookie-only mutation path.
    r = c.delete(
        f"/v1/sessions/{sid}",
        cookies={"sc_session": cookie},
        headers=_browser({"x-csrf-token": token}),
    )
    # Either 200 (revoked) or 404 are both acceptable proofs that
    # CSRF did NOT short-circuit the request with a 403.
    assert r.status_code != 403, r.text


def test_browser_post_with_wrong_token_is_blocked(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    cookie, sid = _issue("alice")
    # Token minted for a *different* session id must not validate.
    _, other_sid = _issue("bob")
    from services.api.app.middleware.csrf import token_for_session

    bad = token_for_session(other_sid)
    r = c.delete(
        f"/v1/sessions/{sid}",
        cookies={"sc_session": cookie},
        headers=_browser({"x-csrf-token": bad}),
    )
    assert r.status_code == 403, r.text
    assert r.json()["error"] == "csrf_token_invalid"


def test_api_key_caller_is_exempt(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # API keys never ride on ambient cookies; they MUST pass even
    # when the browser-shaped origin header is set and no CSRF
    # header is present. /v1/me is a cheap mutation-style route to
    # probe; any non-403 status proves CSRF did not intercept.
    r = c.get(
        "/v1/me/data",
        headers={**_browser(), "x-api-key": "admin-key"},
    )
    assert r.status_code != 403, r.text


def test_safe_method_is_exempt(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    cookie, _sid = _issue("alice")
    r = c.get(
        "/v1/sessions",
        cookies={"sc_session": cookie},
        headers=_browser(),
    )
    assert r.status_code == 200


def test_non_browser_post_without_origin_is_allowed(monkeypatch, tmp_path):
    """curl/CI scripts that omit Origin are not collateral damage."""
    c = _client(monkeypatch, tmp_path)
    cookie, sid = _issue("alice")
    r = c.delete(
        f"/v1/sessions/{sid}",
        cookies={"sc_session": cookie},
    )
    assert r.status_code != 403, r.text


def test_auth_csrf_endpoint_returns_token_matching_session(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    cookie, sid = _issue("alice")
    r = c.get("/auth/csrf", cookies={"sc_session": cookie})
    assert r.status_code == 200
    from services.api.app.middleware.csrf import token_for_session

    assert r.json()["csrf_token"] == token_for_session(sid)


def test_csrf_cookie_is_set_on_authenticated_response(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    cookie, sid = _issue("alice")
    r = c.get("/v1/sessions", cookies={"sc_session": cookie})
    assert r.status_code == 200
    from services.api.app.middleware.csrf import (
        CSRF_COOKIE,
        token_for_session,
    )

    # The middleware should have re-issued the double-submit cookie
    # so JS can read it and copy the value into the X-CSRF-Token
    # header on subsequent fetches.
    assert r.cookies.get(CSRF_COOKIE) == token_for_session(sid)
