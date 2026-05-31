"""Authentication: API key (header) or session cookie (web OAuth).

Web sessions are server-side: the signed cookie only carries an opaque
session id (``sid``). Validity, expiry, and revocation all live in the
``sessions`` table, which lets us list active devices, revoke a single
session, and force-logout every device a user is signed in on.
"""
from __future__ import annotations

from itsdangerous import BadSignature, URLSafeSerializer
from shotclassify_common import get_settings
from shotclassify_store import session_store
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .rbac import role_for_api_key, role_for_login

PUBLIC_PATHS = {
    "/",
    "/healthz",
    "/readyz",
    "/metrics",
    "/auth/login",
    "/auth/callback",
    "/auth/logout",
    "/docs",
    "/redoc",
    "/openapi.json",
}


def _signer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().app_secret_key, salt="shotclassify-session")


def issue_session(
    login: str,
    *,
    client_ip: str | None = None,
    user_agent: str | None = None,
    tenant_id: str | None = None,
) -> tuple[str, str]:
    """Mint a server-side session, return ``(cookie_value, session_id)``.

    The cookie carries only the signed session id; the principal and
    every other attribute live in the database so they can be revoked
    independently of the cookie's signature.
    """
    info = session_store.create(
        principal=login,
        tenant_id=tenant_id,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    cookie = _signer().dumps({"sid": info.id})
    return cookie, info.id


def _decode_sid(token: str | None) -> str | None:
    if not token:
        return None
    try:
        data = _signer().loads(token)
    except BadSignature:
        return None
    if isinstance(data, dict):
        sid = data.get("sid")
        if isinstance(sid, str):
            return sid
    return None


def read_session(token: str | None) -> str | None:
    """Validate a session cookie against the server-side table.

    Returns the principal login on success; ``None`` if the cookie is
    missing, tampered with, expired, or revoked. Bumps ``last_seen_at``
    on the matching row so the admin console can show live activity.
    """
    sid = _decode_sid(token)
    if not sid:
        return None
    info = session_store.touch(sid)
    return info.principal if info else None


class APIKeyAndSessionAuth(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        s = get_settings()
        path = request.url.path
        if not s.auth_enabled or path in PUBLIC_PATHS or path.startswith("/blob"):
            return await call_next(request)
        api_key = request.headers.get("x-api-key")
        if api_key:
            role = role_for_api_key(api_key)
            if role:
                request.state.principal = "api-key"
                request.state.auth_api_key = api_key
                request.state.role = role
                return await call_next(request)
        cookie = request.cookies.get("sc_session")
        sid = _decode_sid(cookie)
        if sid:
            info = session_store.touch(sid)
            if info and (
                not s.auth_allowed_github_login
                or info.principal == s.auth_allowed_github_login
            ):
                request.state.principal = info.principal
                request.state.session_id = info.id
                request.state.role = role_for_login(info.principal)
                return await call_next(request)
        return JSONResponse(
            {"error": "unauthorized", "detail": "Provide X-API-Key or login via /auth/login."},
            status_code=401,
        )
