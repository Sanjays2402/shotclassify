"""Authentication: API key (header) or session cookie (web OAuth)."""
from __future__ import annotations

from itsdangerous import BadSignature, URLSafeSerializer
from shotclassify_common import get_settings
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


def issue_session(login: str) -> str:
    return _signer().dumps({"login": login})


def read_session(token: str | None) -> str | None:
    if not token:
        return None
    try:
        data = _signer().loads(token)
        return data.get("login")
    except BadSignature:
        return None


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
                request.state.role = role
                return await call_next(request)
        session = request.cookies.get("sc_session")
        login = read_session(session)
        if login and (
            not s.auth_allowed_github_login or login == s.auth_allowed_github_login
        ):
            request.state.principal = login
            request.state.role = role_for_login(login)
            return await call_next(request)
        return JSONResponse(
            {"error": "unauthorized", "detail": "Provide X-API-Key or login via /auth/login."},
            status_code=401,
        )
