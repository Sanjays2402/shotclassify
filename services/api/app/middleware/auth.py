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
from shotclassify_store import api_keys_store, auth_lockouts_store, memberships_store, scim_store, session_store
from shotclassify_store import get_session_policy
from shotclassify_store.sessions import SESSION_TTL
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .rbac import role_for_api_key, role_for_login


def _client_ip(request: Request) -> str:
    """Best-effort source IP, honoring an upstream X-Forwarded-For.

    Used by the brute-force lockout to bucket failed credential attempts.
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _api_key_tenant_guess(api_key: str) -> str | None:
    """Resolve the tenant a presented API key *would* authenticate as.

    The DB lookup only matches active, non-revoked tokens; for the
    brute-force counter we still want to attribute a failed attempt to
    *some* tenant so the lockout can fire even when the attacker is
    guessing random strings. We fall back to the env-mapped tenant via
    :func:`tenant_for_principal('api-key:<prefix>')`, and finally to the
    deployment-wide default tenant. None means "could not attribute".
    """
    try:
        record = api_keys_store.get_active_by_token(api_key)
    except Exception:
        record = None
    if record is not None:
        return record.tenant_id
    # No active key matches; attribute the failure to the deployment
    # default tenant so the lockout still applies. Without this, an
    # attacker spraying random keys would never trigger a lockout
    # because no tenant_id is ever resolved.
    s = get_settings()
    return getattr(s, "auth_default_tenant", None) or "default"

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
    "/v1/trust/legal",
    "/.well-known/security.txt",
    "/security.txt",
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


def _resolve_session_idle(tenant_id: str | None) -> timedelta | None:
    """Return the per-tenant session idle (inactivity) timeout.

    Returns ``None`` when no policy is configured so callers leave the
    historical "no idle timeout" behaviour alone. A corrupt settings row
    is treated as "no policy" rather than failing closed so a misconfig
    cannot lock an entire tenant out.
    """
    try:
        if not tenant_id:
            return None
        policy = get_session_policy(tenant_id)
        if policy.session_idle_minutes is None:
            return None
        return timedelta(minutes=int(policy.session_idle_minutes))
    except Exception:
        return None


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
        if not s.auth_enabled or path in PUBLIC_PATHS:
            return await call_next(request)

        # Source IP and (when known) candidate tenant for the brute-force
        # lockout. The check below runs *before* any credential lookup so
        # an attacker burning a locked-out IP cannot also burn DB
        # round-trips against bcrypt-class verifiers.
        src_ip = _client_ip(request)

        def _lockout_response(status, *, tenant_label: str) -> JSONResponse:
            return JSONResponse(
                {
                    "error": "auth_locked_out",
                    "detail": (
                        "Too many failed authentication attempts from this "
                        "source IP. Try again after the cooldown elapses or "
                        "contact a workspace admin to clear the lockout."
                    ),
                    "tenant": tenant_label,
                    "retry_after_seconds": status.retry_after_seconds,
                    "locked_until": status.locked_until.isoformat() if status.locked_until else None,
                },
                status_code=423,
                headers={"Retry-After": str(status.retry_after_seconds)},
            )

        # SCIM 2.0 bearer auth. Only honored under /scim/v2/* so a leaked
        # SCIM token cannot reach the rest of the API surface. The token is
        # resolved to a tenant_id via a SHA-256 index lookup; missing or
        # disabled tenants fall through to the 401 path below.
        if path.startswith("/scim/v2/") or path == "/scim/v2":
            authz = request.headers.get("authorization") or ""
            bearer = ""
            if authz.lower().startswith("bearer "):
                bearer = authz.split(" ", 1)[1].strip()
                tenant_id = scim_store.get_tenant_by_scim_token(bearer)
                if tenant_id:
                    # Successful SCIM auth clears the failure counter for
                    # this (tenant, ip) so a legitimate caller that just
                    # rotated does not stay near the threshold forever.
                    status_before = auth_lockouts_store.check_locked(tenant_id, src_ip)
                    if status_before.locked:
                        return _lockout_response(status_before, tenant_label=tenant_id)
                    request.state.principal = f"scim:{tenant_id}"
                    request.state.tenant_id = tenant_id
                    request.state.scim_authenticated = True
                    request.state.role = "admin"
                    request.state.auth_scopes = ["scim:provision"]
                    return await call_next(request)
            # Failed SCIM bearer: attribute to the deployment default
            # tenant so the lockout still fires for credential spraying.
            fallback_tenant = getattr(s, "auth_default_tenant", None) or "default"
            auth_lockouts_store.record_failure(fallback_tenant, src_ip, "scim")
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
                # Brute-force lockout check: even a valid key cannot pass
                # if its tenant has a live lockout for this source IP.
                lo_status = auth_lockouts_store.check_locked(record.tenant_id, src_ip)
                if lo_status.locked:
                    return _lockout_response(lo_status, tenant_label=record.tenant_id)
                # Per-tenant API key inactivity cap. When the workspace has
                # opted in to auto-revocation of dormant credentials, any
                # key that has been idle longer than the cap is revoked
                # right here and the request is rejected. The same token
                # presented again will hit the "not active" branch above
                # and 401 with the standard missing-key shape.
                from shotclassify_store import get_api_key_inactivity_policy
                policy = get_api_key_inactivity_policy(record.tenant_id)
                if api_keys_store.is_stale(record, policy.inactivity_days):
                    api_keys_store.revoke(record.id, tenant_id=record.tenant_id)
                    request.state.tenant_id = record.tenant_id
                    request.state.principal = f"api-key:{record.id}"
                    request.state.auto_revoked_api_key_id = record.id
                    return JSONResponse(
                        {
                            "error": "api_key_stale_inactive",
                            "detail": (
                                "This API key has been idle longer than "
                                "the workspace inactivity policy and has "
                                "been automatically revoked. Mint a new "
                                "key to continue."
                            ),
                            "inactivity_days": policy.inactivity_days,
                            "key_id": record.id,
                        },
                        status_code=401,
                    )
                if record.allowed_cidrs:
                    if not api_keys_store.ip_in_cidrs(src_ip, record.allowed_cidrs):
                        return JSONResponse(
                            {
                                "error": "api_key_ip_not_allowed",
                                "detail": (
                                    "This API key is restricted to a fixed "
                                    "set of source IPs. Your request came "
                                    "from outside the allowlist."
                                ),
                                "client_ip": src_ip,
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
                # Resolve the tenant this env-mapped key is bound to so
                # the brute-force lockout applies symmetrically to env
                # keys and DB keys. Without this, an attacker spraying
                # against a tenant whose admins use env keys could not
                # be locked out at all.
                from ..middleware.tenant import tenant_for_principal as _tfp
                env_tenant = _tfp(api_key) or (
                    getattr(s, "auth_default_tenant", None) or "default"
                )
                lo_status = auth_lockouts_store.check_locked(env_tenant, src_ip)
                if lo_status.locked:
                    return _lockout_response(lo_status, tenant_label=env_tenant)
                request.state.principal = "api-key"
                request.state.auth_api_key = api_key
                request.state.auth_scopes = []
                request.state.role = role
                return await call_next(request)
            # Invalid X-API-Key. Attribute the failure to the deployment
            # default tenant so credential-spray lockouts still apply when
            # the attacker hits prefixes that resolve to no real key. The
            # returned status check lets us answer the *next* spray attempt
            # from this IP with a 423 instead of another 401.
            fallback_tenant = getattr(s, "auth_default_tenant", None) or "default"
            after = auth_lockouts_store.record_failure(
                fallback_tenant, src_ip, "api_key"
            )
            if after.locked:
                return _lockout_response(after, tenant_label=fallback_tenant)
        cookie = request.cookies.get("sc_session")
        sid = _decode_sid(cookie)
        if sid:
            # Peek the row (no last_seen_at bump) to learn the tenant so we
            # can apply that tenant's idle-timeout policy on this touch.
            peek = session_store.get(sid)
            # Brute-force lockout check for cookie sessions, using the
            # session's tenant when known.
            peek_tenant = peek.tenant_id if peek and peek.tenant_id else None
            if peek_tenant:
                lo_status = auth_lockouts_store.check_locked(peek_tenant, src_ip)
                if lo_status.locked:
                    return _lockout_response(lo_status, tenant_label=peek_tenant)
            idle = _resolve_session_idle(peek.tenant_id) if peek else None
            info = session_store.touch(sid, idle_timeout=idle)
            if info and (
                not s.auth_allowed_github_login
                or info.principal == s.auth_allowed_github_login
            ):
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
                member_role = memberships_store.role_for_member(
                    info.tenant_id, info.principal
                )
                request.state.role = member_role or role_for_login(info.principal)
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
            # Cookie present but did not resolve to a live session row.
            # Counts as a failed authentication for brute-force purposes.
            attribute_tenant = (
                peek_tenant or getattr(s, "auth_default_tenant", None) or "default"
            )
            after = auth_lockouts_store.record_failure(
                attribute_tenant, src_ip, "session"
            )
            if after.locked:
                return _lockout_response(after, tenant_label=attribute_tenant)
        return JSONResponse(
            {"error": "unauthorized", "detail": "Provide X-API-Key or login via /auth/login."},
            status_code=401,
        )
