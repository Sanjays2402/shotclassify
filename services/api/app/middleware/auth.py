"""Authentication: API key (header) or session cookie (web OAuth).

Web sessions are server-side: the signed cookie only carries an opaque
session id (``sid``). Validity, expiry, and revocation all live in the
``sessions`` table, which lets us list active devices, revoke a single
session, and force-logout every device a user is signed in on.
"""
from __future__ import annotations

from itsdangerous import BadSignature, URLSafeSerializer
from shotclassify_common import get_settings
from shotclassify_store import api_keys_store, session_store
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
    "/auth/sso/login",
    "/auth/sso/callback",
    "/auth/sso/config",
    "/auth/sso/_test/issue",
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
    auth_method: str = "oauth",
) -> tuple[str, str]:
    """Mint a server-side session, return ``(cookie_value, session_id)``.

    The cookie carries only the signed session id; the principal and
    every other attribute live in the database so they can be revoked
    independently of the cookie's signature. ``auth_method`` records
    which flow minted the session ("oauth", "sso") so the enforce-SSO
    check in the auth middleware can reject legacy logins for tenants
    that have switched to OIDC-only.
    """
    info = session_store.create(
        principal=login,
        tenant_id=tenant_id,
        client_ip=client_ip,
        user_agent=user_agent,
        auth_method=auth_method,
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
            # DB-backed keys are the source of truth. They carry their own
            # scopes, tenant binding, and revocation state so cycling a key
            # is a single UPDATE and does not require a redeploy.
            record = api_keys_store.get_active_by_token(api_key)
            if record is not None:
                request.state.principal = f"api-key:{record.id}"
                request.state.auth_api_key = api_key
                request.state.auth_api_key_id = record.id
                request.state.auth_api_key_tenant = record.tenant_id
                request.state.auth_scopes = list(record.scopes)
                request.state.role = api_keys_store.role_for_scopes(record.scopes)
                api_keys_store.touch_last_used(record.id)
                return await call_next(request)
            # Fall back to env-var configured keys for backward compatibility
            # with the legacy AUTH_API_KEY / AUTH_API_KEYS deployment style.
            role = role_for_api_key(api_key)
            if role:
                request.state.principal = "api-key"
                request.state.auth_api_key = api_key
                request.state.auth_scopes = []
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
                # Enforce SSO at the session boundary. If the resolved tenant
                # has ``sso_enforced=True`` and this session was not minted
                # via the SSO callback, refuse it. API-key callers are exempt
                # because they cover machine-to-machine integrations that
                # cannot run an interactive browser flow.
                from shotclassify_store.tenant_settings import get_sso_config

                if info.tenant_id:
                    cfg = get_sso_config(info.tenant_id)
                    if cfg.enforced and info.auth_method != "sso":
                        return JSONResponse(
                            {
                                "error": "sso_required",
                                "detail": (
                                    "This workspace requires single sign-on. "
                                    "Sign in again via /auth/sso/login."
                                ),
                            },
                            status_code=401,
                        )
                request.state.principal = info.principal
                request.state.session_id = info.id
                request.state.role = role_for_login(info.principal)
                return await call_next(request)
        return JSONResponse(
            {"error": "unauthorized", "detail": "Provide X-API-Key or login via /auth/login."},
            status_code=401,
        )
