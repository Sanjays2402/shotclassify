"""Authentication: API key (header) or session cookie (web OAuth).

Web sessions are server-side: the signed cookie only carries an opaque
session id (``sid``). Validity, expiry, and revocation all live in the
``sessions`` table, which lets us list active devices, revoke a single
session, and force-logout every device a user is signed in on.
"""
from __future__ import annotations

from datetime import timedelta

from itsdangerous import BadSignature, URLSafeSerializer
from shotclassify_common import get_settings
from shotclassify_store import api_keys_store, memberships_store, scim_store, session_store
from shotclassify_store import get_session_policy
from shotclassify_store.sessions import SESSION_TTL
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .rbac import role_for_api_key, role_for_login

# Paths exempt from the workspace-wide MFA enrolment policy. A member
# who has not yet enrolled MFA can still hit these so they can complete
# enrolment, see who they are signed in as, list/revoke their sessions,
# and sign out. Everything else returns 403 mfa_enrollment_required
# until the credential is confirmed. Healthchecks live in PUBLIC_PATHS
# and never reach this check.
MFA_ENROLLMENT_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/v1/mfa",
    "/v1/me",
    "/v1/sessions",
    "/auth/logout",
)


def _mfa_path_exempt(path: str) -> bool:
    """True when ``path`` is allowed under the MFA enrolment policy."""
    for prefix in MFA_ENROLLMENT_EXEMPT_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False

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
    "/v1/trust/subprocessors",
    "/v1/trust/incidents",
}


def _signer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().app_secret_key, salt="shotclassify-session")


def _resolve_session_ttl(tenant_id: str | None) -> timedelta:
    """Return the cookie session TTL for ``tenant_id``.

    Falls back to the global :data:`SESSION_TTL` when the tenant has
    not set an override (or when no tenant context is available, as is
    the case for pre-login flows). Any unexpected error reading the
    settings is logged silently to the global default so a corrupt
    settings row can never lock a workspace out of fresh logins.
    """
    try:
        if not tenant_id:
            return SESSION_TTL
        policy = get_session_policy(tenant_id)
        if policy.session_ttl_minutes is None:
            return SESSION_TTL
        return timedelta(minutes=int(policy.session_ttl_minutes))
    except Exception:
        return SESSION_TTL


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
        ttl=_resolve_session_ttl(tenant_id),
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
        # SCIM 2.0 bearer auth. Only honored under /scim/v2/* so a leaked
        # SCIM token cannot reach the rest of the API surface. The token is
        # resolved to a tenant_id via a SHA-256 index lookup; missing or
        # disabled tenants fall through to the 401 path below.
        if path.startswith("/scim/v2/") or path == "/scim/v2":
            authz = request.headers.get("authorization") or ""
            if authz.lower().startswith("bearer "):
                bearer = authz.split(" ", 1)[1].strip()
                tenant_id = scim_store.get_tenant_by_scim_token(bearer)
                if tenant_id:
                    request.state.principal = f"scim:{tenant_id}"
                    request.state.tenant_id = tenant_id
                    request.state.scim_authenticated = True
                    # SCIM provisioning needs admin-level membership writes.
                    # The scope is constrained by the path prefix above so
                    # this elevated role never bleeds outside /scim/v2.
                    request.state.role = "admin"
                    request.state.auth_scopes = ["scim:provision"]
                    return await call_next(request)
            return JSONResponse(
                {
                    "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
                    "status": "401",
                    "detail": "SCIM bearer token missing, invalid, or disabled.",
                },
                status_code=401,
            )
        api_key = request.headers.get("x-api-key")
        if api_key:
            # DB-backed keys are the source of truth. They carry their own
            # scopes, tenant binding, and revocation state so cycling a key
            # is a single UPDATE and does not require a redeploy.
            record = api_keys_store.get_active_by_token(api_key)
            if record is not None:
                # Per-key source-IP allowlist. When the key carries a
                # non-empty CIDR list, the request's source IP must be
                # contained by at least one range. This is the per-
                # credential complement to the per-tenant IP allowlist
                # and is enforced at the auth layer so adding a new route
                # cannot accidentally bypass it.
                if record.allowed_cidrs:
                    fwd = request.headers.get("x-forwarded-for")
                    client_ip = (
                        fwd.split(",")[0].strip()
                        if fwd
                        else (request.client.host if request.client else "")
                    )
                    if not api_keys_store.ip_in_cidrs(client_ip, record.allowed_cidrs):
                        return JSONResponse(
                            {
                                "error": "api_key_ip_not_allowed",
                                "detail": (
                                    "This API key is restricted to a fixed "
                                    "set of source IPs. Your request came "
                                    "from outside the allowlist."
                                ),
                                "client_ip": client_ip,
                            },
                            status_code=403,
                        )
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
                # Membership rows (if any) are the source of truth for role.
                # This is the wiring that lets workspace admins hand out
                # roles from the /members UI without redeploying the env
                # var ``AUTH_ROLE_MAP``.
                member_role = memberships_store.role_for_member(
                    info.tenant_id, info.principal
                )
                request.state.role = member_role or role_for_login(info.principal)
                # Workspace-wide MFA enrolment policy. When the tenant has
                # opted in, every cookie session must be backed by a
                # confirmed TOTP credential. A small allowlist of paths
                # is exempt so a member without a second factor can still
                # navigate to the enrolment UI and complete it without
                # being locked out of the very pages that let them comply.
                if info.tenant_id:
                    from shotclassify_store import mfa_store
                    from shotclassify_store.tenant_settings import get_mfa_policy

                    mp = get_mfa_policy(info.tenant_id)
                    if mp.required and not _mfa_path_exempt(request.url.path):
                        if not mfa_store.is_confirmed(info.principal):
                            return JSONResponse(
                                {
                                    "error": "mfa_enrollment_required",
                                    "detail": (
                                        "This workspace requires every member "
                                        "to enrol a second factor. Visit "
                                        "Settings -> Security -> Multi-factor "
                                        "authentication to enrol before "
                                        "continuing."
                                    ),
                                },
                                status_code=403,
                            )
                return await call_next(request)
        return JSONResponse(
            {"error": "unauthorized", "detail": "Provide X-API-Key or login via /auth/login."},
            status_code=401,
        )
