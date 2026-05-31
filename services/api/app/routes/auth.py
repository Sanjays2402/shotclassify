"""OAuth login (GitHub) + session cookie."""
from __future__ import annotations

import secrets
import urllib.parse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from shotclassify_common import get_settings
from shotclassify_store import session_store

from ..middleware.auth import _decode_sid, issue_session
from ..middleware.tenant import tenant_for_principal

router = APIRouter(prefix="/auth", tags=["auth"])

_AUTHORIZE = "https://github.com/login/oauth/authorize"
_TOKEN = "https://github.com/login/oauth/access_token"
_USER = "https://api.github.com/user"


@router.get("/login")
def login(request: Request):
    s = get_settings()
    if not s.auth_oauth_client_id:
        return HTMLResponse(
            "<h1>OAuth not configured</h1>"
            "<p>Set AUTH_OAUTH_CLIENT_ID/SECRET, or use X-API-Key for the CLI.</p>",
            status_code=200,
        )
    state = secrets.token_urlsafe(16)
    redirect_uri = str(request.url_for("auth_callback"))
    params = {
        "client_id": s.auth_oauth_client_id,
        "redirect_uri": redirect_uri,
        "scope": "read:user",
        "state": state,
    }
    resp = RedirectResponse(f"{_AUTHORIZE}?{urllib.parse.urlencode(params)}")
    resp.set_cookie("sc_oauth_state", state, httponly=True, samesite="lax")
    return resp


@router.get("/callback", name="auth_callback")
def callback(request: Request, code: str, state: str):
    s = get_settings()
    cookie_state = request.cookies.get("sc_oauth_state")
    if not cookie_state or cookie_state != state:
        raise HTTPException(400, "Invalid OAuth state.")
    with httpx.Client(timeout=10) as client:
        r = client.post(
            _TOKEN,
            data={
                "client_id": s.auth_oauth_client_id,
                "client_secret": s.auth_oauth_client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        r.raise_for_status()
        access = r.json().get("access_token")
        if not access:
            raise HTTPException(400, "No access token returned.")
        u = client.get(_USER, headers={"Authorization": f"Bearer {access}"})
        u.raise_for_status()
        login_name = u.json().get("login")
    if s.auth_allowed_github_login and login_name != s.auth_allowed_github_login:
        raise HTTPException(403, "Not in allowlist.")
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    cookie, _sid = issue_session(
        login_name,
        client_ip=client_ip,
        user_agent=user_agent,
        tenant_id=tenant_for_principal(login_name),
    )
    resp = RedirectResponse("/")
    resp.set_cookie(
        "sc_session", cookie, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30
    )
    return resp


@router.post("/logout")
def logout(request: Request):
    # Revoke the server-side session row so the cookie cannot be replayed
    # even if the user neglects to clear it.
    sid = _decode_sid(request.cookies.get("sc_session"))
    if sid:
        session_store.revoke(sid)
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("sc_session")
    return resp


@router.get("/whoami")
def whoami(request: Request):
    return {"principal": getattr(request.state, "principal", None)}


@router.get("/csrf")
def csrf_token(request: Request):
    """Expose the current double-submit CSRF token for cookie callers.

    SPA clients call this once at boot to fetch the token, then attach
    it to every state-changing fetch via ``X-CSRF-Token``. API-key
    callers never need this endpoint: they are exempt from CSRF
    enforcement because they do not ride on ambient browser cookies.
    """
    sid = getattr(request.state, "session_id", None)
    if not sid:
        # API-key principals reach this branch when they hit the
        # endpoint by accident. Returning a CSRF token to them would
        # be misleading: it would not match anything.
        return {"csrf_token": None, "detail": "No cookie session on this request."}
    from ..middleware.csrf import token_for_session

    return {"csrf_token": token_for_session(sid)}
