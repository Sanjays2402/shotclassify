"""Per-tenant security settings: read and update the IP allowlist.

These endpoints are admin-only. Reads return the active list for the
caller's resolved tenant. Writes replace the list atomically and the
audit log middleware records the change with the actor, request id,
client IP, and target tenant.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from shotclassify_store import (
    API_KEY_MAX_TTL_DAYS,
    API_KEY_MIN_TTL_DAYS,
    API_KEY_INACTIVITY_MAX_DAYS,
    API_KEY_INACTIVITY_MIN_DAYS,
    API_KEY_MAX_ACTIVE_MAX,
    API_KEY_MAX_ACTIVE_MIN,
    SESSION_TTL_MAX_MINUTES,
    SESSION_TTL_MIN_MINUTES,
    SESSION_IDLE_MAX_MINUTES,
    SESSION_IDLE_MIN_MINUTES,
    get_api_key_inactivity_policy,
    get_api_key_max_active_policy,
    get_api_key_ttl_policy,
    get_cors_origins,
    get_ip_allowlist,
    get_mfa_policy,
    get_privacy_settings,
    get_retention_days,
    get_session_policy,
    get_sso_config,
    get_tenant_oidc,
    get_webhook_egress_allowed_hosts,
    purge_expired_for_tenant,
    set_api_key_inactivity_policy,
    set_api_key_max_active_policy,
    set_api_key_ttl_policy,
    set_cors_origins,
    set_ip_allowlist,
    set_mfa_policy,
    set_privacy_settings,
    set_retention_days,
    set_session_policy,
    set_session_idle_policy,
    set_sso_config,
    set_tenant_oidc,
    set_webhook_egress_allowed_hosts,
    WEBHOOK_EGRESS_HOSTS_MAX,
)
from datetime import timedelta
from shotclassify_store.sessions import SESSION_TTL, clip_active_for_tenant

from ..middleware.mfa import require_mfa_step_up
from ..middleware.rbac import require_role

router = APIRouter(prefix="/v1/settings/security", tags=["settings"])


def _tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        # Admin cross-tenant view (X-Tenant: *) cannot be used to mutate a
        # specific tenant's allowlist; they must pick one explicitly.
        raise HTTPException(
            400, "No tenant resolved. Pass X-Tenant header to target a tenant."
        )
    return tenant_id


@router.get("/ip-allowlist", dependencies=[require_role("admin")])
def get_ip_allowlist_route(request: Request) -> dict:
    tenant_id = _tenant(request)
    return {
        "tenant_id": tenant_id,
        "cidrs": get_ip_allowlist(tenant_id),
    }


@router.put("/ip-allowlist", dependencies=[require_role("admin"), require_mfa_step_up()])
def put_ip_allowlist_route(
    request: Request,
    payload: dict = Body(...),
) -> dict:
    tenant_id = _tenant(request)
    raw = payload.get("cidrs")
    if not isinstance(raw, list):
        raise HTTPException(422, "Field 'cidrs' must be a list of CIDR strings.")
    if len(raw) > 256:
        raise HTTPException(422, "At most 256 CIDR entries are supported.")
    actor = getattr(request.state, "principal", None)
    try:
        normalized = set_ip_allowlist(tenant_id, raw, updated_by=actor)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"tenant_id": tenant_id, "cidrs": normalized}


@router.get("/cors-origins", dependencies=[require_role("admin")])
def get_cors_origins_route(request: Request) -> dict:
    """Return the browser-origin allowlist for the caller's tenant."""
    tenant_id = _tenant(request)
    return {
        "tenant_id": tenant_id,
        "origins": get_cors_origins(tenant_id),
    }


@router.put(
    "/cors-origins",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_cors_origins_route(
    request: Request,
    payload: dict = Body(...),
) -> dict:
    """Replace the browser-origin allowlist for the caller's tenant.

    Empty list disables the policy (no browser-origin enforcement; the
    deployment-level CORS allowlist still applies).
    """
    tenant_id = _tenant(request)
    raw = payload.get("origins")
    if not isinstance(raw, list):
        raise HTTPException(422, "Field 'origins' must be a list of origin strings.")
    if len(raw) > 64:
        raise HTTPException(422, "At most 64 origins are supported per tenant.")
    actor = getattr(request.state, "principal", None)
    try:
        normalized = set_cors_origins(tenant_id, raw, updated_by=actor)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"tenant_id": tenant_id, "origins": normalized}


@router.get("/retention", dependencies=[require_role("admin")])
def get_retention_route(request: Request) -> dict:
    tenant_id = _tenant(request)
    days = get_retention_days(tenant_id)
    return {
        "tenant_id": tenant_id,
        "retention_days": days,
        "enabled": bool(days),
    }


@router.put("/retention", dependencies=[require_role("admin"), require_mfa_step_up()])
def put_retention_route(
    request: Request,
    payload: dict = Body(...),
) -> dict:
    tenant_id = _tenant(request)
    if "retention_days" not in payload:
        raise HTTPException(422, "Field 'retention_days' is required (int or null).")
    actor = getattr(request.state, "principal", None)
    try:
        days = set_retention_days(
            tenant_id, payload["retention_days"], updated_by=actor
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {
        "tenant_id": tenant_id,
        "retention_days": days,
        "enabled": bool(days),
    }


@router.post("/retention/run", dependencies=[require_role("admin"), require_mfa_step_up()])
def run_retention_route(request: Request) -> dict:
    """Manually trigger a purge for the caller's tenant.

    Useful for operators who just lowered the policy and want immediate
    cleanup instead of waiting for the next scheduled sweep. Same tenant
    scoping rules as the scheduled job.
    """
    tenant_id = _tenant(request)
    result = purge_expired_for_tenant(tenant_id)
    return result.to_dict()


@router.get("/sso", dependencies=[require_role("admin")])
def get_sso_route(request: Request) -> dict:
    """Return the SSO config for the caller's tenant."""
    tenant_id = _tenant(request)
    return get_sso_config(tenant_id).to_dict()


@router.put("/sso", dependencies=[require_role("admin"), require_mfa_step_up()])
def put_sso_route(request: Request, payload: dict = Body(...)) -> dict:
    """Update per-tenant SSO config.

    Body: ``{"enforced": bool, "domain": str|null, "provider": str|null}``.
    Setting ``enforced=True`` immediately rejects any active non-SSO session
    for the tenant on its next request. Domain uniqueness is enforced at the
    store layer so two tenants cannot claim the same email domain.
    """
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "Body must be a JSON object.")
    enforced = bool(payload.get("enforced", False))
    domain = payload.get("domain")
    provider = payload.get("provider")
    auto_join_role = payload.get("auto_join_role")
    if domain is not None and not isinstance(domain, str):
        raise HTTPException(422, "'domain' must be a string or null.")
    if provider is not None and not isinstance(provider, str):
        raise HTTPException(422, "'provider' must be a string or null.")
    if auto_join_role is not None and not isinstance(auto_join_role, str):
        raise HTTPException(422, "'auto_join_role' must be a string or null.")
    actor = getattr(request.state, "principal", None)
    try:
        cfg = set_sso_config(
            tenant_id,
            enforced=enforced,
            domain=domain or None,
            provider=provider or None,
            auto_join_role=auto_join_role or None,
            updated_by=actor,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return cfg.to_dict()


@router.get("/privacy", dependencies=[require_role("admin")])
def get_privacy_route(request: Request) -> dict:
    """Return the tenant's PII redaction modes and data residency hint.

    Admin-only because the available_modes list and the active modes
    are themselves a compliance disclosure: a non-admin member should
    not be able to enumerate which fields the workspace is sanitizing
    before persistence.
    """
    tenant_id = _tenant(request)
    return get_privacy_settings(tenant_id).to_dict()


@router.put(
    "/privacy",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_privacy_route(request: Request, payload: dict = Body(...)) -> dict:
    """Update the tenant's PII redaction modes and data residency hint.

    Body: ``{"redact_modes": [str], "data_residency": str|null}``.
    Both fields are required so a half-supplied PUT does not silently
    keep stale state from a previous version of the UI.
    """
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "Body must be a JSON object.")
    if "redact_modes" not in payload:
        raise HTTPException(422, "Field 'redact_modes' is required (list of strings).")
    if "data_residency" not in payload:
        raise HTTPException(422, "Field 'data_residency' is required (string or null).")
    actor = getattr(request.state, "principal", None)
    try:
        cfg = set_privacy_settings(
            tenant_id,
            redact_modes=payload["redact_modes"],
            data_residency=payload["data_residency"],
            updated_by=actor,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return cfg.to_dict()


@router.get("/sessions", dependencies=[require_role("admin")])
def get_session_policy_route(request: Request) -> dict:
    """Return the per-tenant cookie session TTL policy.

    Includes the effective minutes (the override if set, else the global
    default) so the UI can show what every new login will actually use
    without re-implementing the fallback logic.
    """
    tenant_id = _tenant(request)
    policy = get_session_policy(tenant_id)
    default_minutes = int(SESSION_TTL.total_seconds() // 60)
    effective = policy.session_ttl_minutes or default_minutes
    return {
        **policy.to_dict(),
        "default_minutes": default_minutes,
        "effective_minutes": effective,
    }


@router.put(
    "/sessions",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_session_policy_route(request: Request, payload: dict = Body(...)) -> dict:
    """Set or clear the per-tenant cookie session TTL.

    Body: ``{"session_ttl_minutes": int|null}``. ``null`` clears the
    override and the tenant returns to the global default. Lowering the
    TTL also clips every active session whose remaining lifetime exceeds
    the new ceiling so a long-lived browser cookie cannot outlive the
    new rule. ``clipped`` in the response reports how many sessions were
    shortened.
    """
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "Body must be a JSON object.")
    if "session_ttl_minutes" not in payload:
        raise HTTPException(
            422, "Field 'session_ttl_minutes' is required (integer or null)."
        )
    raw = payload["session_ttl_minutes"]
    actor = getattr(request.state, "principal", None)
    try:
        policy = set_session_policy(
            tenant_id, session_ttl_minutes=raw, updated_by=actor
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    default_minutes = int(SESSION_TTL.total_seconds() // 60)
    effective = policy.session_ttl_minutes or default_minutes
    clipped = clip_active_for_tenant(tenant_id, timedelta(minutes=effective))
    return {
        **policy.to_dict(),
        "default_minutes": default_minutes,
        "effective_minutes": effective,
        "clipped": clipped,
    }


# ---------------------------------------------------------------------------
# Legal holds
# ---------------------------------------------------------------------------
#
# Active legal holds freeze every destructive code path for the workspace:
# scheduled retention purge, per-shot DELETE, bulk history DELETE, per-user
# /me/data erasure, and workspace-wide /workspace/data erasure all refuse
# with HTTP 423 Locked while at least one matter is active. Lifting a hold
# writes lifted_at / lifted_by instead of deleting the row so the
# e-discovery trail survives.
from shotclassify_store import legal_holds_store as _legal_holds


@router.get("/legal-holds", dependencies=[require_role("admin")])
def list_legal_holds_route(
    request: Request, active_only: bool = False
) -> dict:
    tenant_id = _tenant(request)
    holds = _legal_holds.list_holds(tenant_id, active_only=active_only)
    return {
        "tenant_id": tenant_id,
        "active": any(h.active for h in holds),
        "active_count": sum(1 for h in holds if h.active),
        "holds": [h.to_dict() for h in holds],
    }


@router.post(
    "/legal-holds",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def create_legal_hold_route(request: Request, payload: dict = Body(...)) -> dict:
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "Body must be a JSON object.")
    actor = getattr(request.state, "principal", None)
    try:
        hold = _legal_holds.create_hold(
            tenant_id,
            payload.get("matter"),
            payload.get("reason"),
            created_by=actor,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return hold.to_dict()


@router.post(
    "/legal-holds/{hold_id}/lift",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def lift_legal_hold_route(
    hold_id: str, request: Request, payload: dict | None = Body(default=None)
) -> dict:
    tenant_id = _tenant(request)
    actor = getattr(request.state, "principal", None)
    reason = (payload or {}).get("reason") if isinstance(payload, dict) else None
    try:
        hold = _legal_holds.lift_hold(
            tenant_id, hold_id, reason, lifted_by=actor
        )
    except KeyError:
        raise HTTPException(404, "Legal hold not found for this workspace.")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return hold.to_dict()


@router.get("/oidc", dependencies=[require_role("admin")])
def get_tenant_oidc_route(request: Request) -> dict:
    """Return this tenant's per-tenant OIDC IdP config.

    The client secret is never returned. A SHA-256 fingerprint and the
    last four characters are surfaced so an operator can confirm the
    expected value is in place without re-entering it.
    """
    tenant_id = _tenant(request)
    return get_tenant_oidc(tenant_id).to_dict()


@router.put(
    "/oidc",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_tenant_oidc_route(request: Request, payload: dict = Body(...)) -> dict:
    """Replace this tenant's per-tenant OIDC IdP config.

    Body: ``{"issuer": str|null, "client_id": str|null, "client_secret": str|null, "scopes": str|null}``.

    Pass all four to configure or update. Pass ``issuer`` and ``client_id``
    as null/empty to clear. When editing an existing config, ``client_secret``
    may be omitted to keep the existing secret in place. Admin-only with a
    fresh MFA step-up because it changes who can sign into the workspace.
    """
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "Body must be a JSON object.")
    for field in ("issuer", "client_id", "client_secret", "scopes"):
        if payload.get(field) is not None and not isinstance(payload.get(field), str):
            raise HTTPException(422, f"'{field}' must be a string or null.")
    actor = getattr(request.state, "principal", None)
    try:
        cfg = set_tenant_oidc(
            tenant_id,
            issuer=payload.get("issuer") or None,
            client_id=payload.get("client_id") or None,
            client_secret=payload.get("client_secret") or None,
            scopes=payload.get("scopes") or None,
            updated_by=actor,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return cfg.to_dict()


@router.delete(
    "/oidc",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def delete_tenant_oidc_route(request: Request) -> dict:
    """Clear this tenant's per-tenant OIDC IdP config.

    After this call, ``/auth/sso/login`` for an email in this tenant's
    domain falls back to the deployment-level shared IdP (if configured).
    """
    tenant_id = _tenant(request)
    actor = getattr(request.state, "principal", None)
    try:
        cfg = set_tenant_oidc(
            tenant_id,
            issuer=None,
            client_id=None,
            client_secret=None,
            scopes=None,
            updated_by=actor,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return cfg.to_dict()


@router.get("/api-key-ttl", dependencies=[require_role("admin")])
def get_api_key_ttl_route(request: Request) -> dict:
    """Return the tenant's API key max-TTL policy (days, or null = no policy)."""
    tenant_id = _tenant(request)
    return get_api_key_ttl_policy(tenant_id).to_dict()


@router.put(
    "/api-key-ttl",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_api_key_ttl_route(
    request: Request,
    payload: dict = Body(...),
) -> dict:
    """Set or clear the tenant's max API key TTL in days.

    Body: ``{"max_ttl_days": int|null}``. ``null`` clears the policy and
    returns the tenant to legacy "no cap" behaviour. When set, every
    subsequent ``POST /v1/api-keys`` with a longer ``ttl_days`` is
    rejected 422, and ``POST /v1/api-keys/{id}/rotate`` clamps the
    successor's expiry to ``now + max_ttl_days``. Existing keys are not
    retroactively shortened so we never break a live integration on
    policy change.
    """
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "JSON object body required.")
    if "max_ttl_days" not in payload:
        raise HTTPException(422, "Field 'max_ttl_days' is required (int or null).")
    raw = payload["max_ttl_days"]
    if raw is not None and (isinstance(raw, bool) or not isinstance(raw, int)):
        raise HTTPException(422, "max_ttl_days must be an integer or null.")
    actor = getattr(request.state, "principal", None)
    try:
        cfg = set_api_key_ttl_policy(
            tenant_id, max_ttl_days=raw, updated_by=actor
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return cfg.to_dict()


# ---------------------------------------------------------------------------
# Workspace-wide MFA enrolment policy
# ---------------------------------------------------------------------------


@router.get("/mfa-policy", dependencies=[require_role("admin")])
def get_mfa_policy_route(request: Request) -> dict:
    """Return the workspace-wide MFA enrolment policy.

    When ``required`` is True, every member must have a confirmed TOTP
    credential before they can use any /v1 cookie-authenticated endpoint
    other than the enrolment surface (``/v1/mfa/*``, ``/v1/me``,
    ``/v1/sessions``, logout). API-key callers are not affected.
    """
    tenant_id = _tenant(request)
    return get_mfa_policy(tenant_id).to_dict()


@router.put(
    "/mfa-policy",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_mfa_policy_route(request: Request, payload: dict = Body(...)) -> dict:
    """Set or clear the workspace-wide member MFA enrolment requirement.

    Body: ``{"required": true|false}``. Turning the policy on requires
    the calling admin to already have a confirmed TOTP credential and a
    fresh MFA step-up so an admin cannot lock themselves out by enabling
    enforcement from a non-MFA session. Lowering to ``false`` clears the
    policy and members go back to the per-action step-up only model.
    """
    tenant_id = _tenant(request)
    if not isinstance(payload, dict) or "required" not in payload:
        raise HTTPException(422, "Body must be {\"required\": bool}.")
    raw = payload["required"]
    if not isinstance(raw, bool):
        raise HTTPException(422, "Field 'required' must be a boolean.")
    actor = getattr(request.state, "principal", None)
    # Defensive: refuse to enable the policy if the actor enabling it
    # does not have a confirmed credential themselves. They would
    # otherwise be locked out of every non-allowlisted route on the
    # next request. ``require_mfa_step_up`` above already proves that
    # they have a confirmed credential, but we re-check explicitly so
    # the failure surface is a 422 with a clear message rather than a
    # later 403 they have to debug.
    if raw:
        from shotclassify_store import mfa_store

        if not mfa_store.is_confirmed(actor or ""):
            raise HTTPException(
                422,
                "Enrol TOTP under Settings -> Security before enabling "
                "workspace-wide MFA.",
            )
    try:
        policy = set_mfa_policy(tenant_id, required=raw, updated_by=actor)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return policy.to_dict()


@router.put(
    "/sessions/idle",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_session_idle_policy_route(
    request: Request, payload: dict = Body(...)
) -> dict:
    """Set or clear the per-tenant session idle (inactivity) timeout.

    Body: ``{"session_idle_minutes": int|null}``. ``null`` removes the
    idle requirement entirely so sessions are only bounded by the
    absolute TTL. A non-null value is enforced on every authenticated
    request: any session whose ``last_seen_at`` is older than the
    configured number of minutes is revoked in place and the caller
    falls back to the login flow. SOC2 CC6.1 and most enterprise
    security questionnaires treat an idle timeout as a hard requirement;
    defaulting to NULL preserves the pre-existing behaviour for tenants
    that have not opted in.
    """
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "Body must be a JSON object.")
    if "session_idle_minutes" not in payload:
        raise HTTPException(
            422, "Field 'session_idle_minutes' is required (integer or null)."
        )
    raw = payload["session_idle_minutes"]
    actor = getattr(request.state, "principal", None)
    try:
        policy = set_session_idle_policy(
            tenant_id, session_idle_minutes=raw, updated_by=actor
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    default_minutes = int(SESSION_TTL.total_seconds() // 60)
    effective = policy.session_ttl_minutes or default_minutes
    return {
        **policy.to_dict(),
        "default_minutes": default_minutes,
        "effective_minutes": effective,
    }


# ---------------------------------------------------------------------------
# Per-tenant API key inactivity (auto-revoke) policy
# ---------------------------------------------------------------------------


@router.get("/api-key-inactivity", dependencies=[require_role("admin")])
def get_api_key_inactivity_route(request: Request) -> dict:
    """Return the tenant's API key inactivity policy (days, or null = no policy)."""
    tenant_id = _tenant(request)
    return get_api_key_inactivity_policy(tenant_id).to_dict()


@router.put(
    "/api-key-inactivity",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_api_key_inactivity_route(
    request: Request,
    payload: dict = Body(...),
) -> dict:
    """Set or clear the tenant's API key inactivity cap in days.

    Body: ``{"inactivity_days": int|null}``. ``null`` clears the policy
    and disables auto-revocation. When set, any DB-backed API key whose
    effective last-use (falling back to creation time) is older than the
    cap is auto-revoked the next time it is presented to the API and the
    request is rejected with 401 ``api_key_stale_inactive``. Existing
    keys are not retroactively shortened: a tightened policy only takes
    effect on the next request that comes in with the stale key.
    """
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "JSON object body required.")
    if "inactivity_days" not in payload:
        raise HTTPException(
            422, "Field 'inactivity_days' is required (int or null)."
        )
    raw = payload["inactivity_days"]
    if raw is not None and (isinstance(raw, bool) or not isinstance(raw, int)):
        raise HTTPException(422, "inactivity_days must be an integer or null.")
    actor = getattr(request.state, "principal", None)
    try:
        cfg = set_api_key_inactivity_policy(
            tenant_id, inactivity_days=raw, updated_by=actor
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return cfg.to_dict()


# ---------------------------------------------------------------------------
# Per-tenant cap on the number of active (non-revoked) API keys
# ---------------------------------------------------------------------------


def _count_active_keys(tenant_id: str) -> int:
    """Helper: count non-revoked DB-backed API keys for a tenant.

    Used to surface the "X of Y in use" hint alongside the policy so
    admins can see how close they are to the cap before they tighten it.
    """
    from shotclassify_store import api_keys_store as _ak

    records = _ak.list_keys(tenant_id=tenant_id, include_revoked=False)
    return len(records)


@router.get("/api-key-max-active", dependencies=[require_role("admin")])
def get_api_key_max_active_route(request: Request) -> dict:
    """Return the tenant's active-API-key cap and current usage."""
    tenant_id = _tenant(request)
    body = get_api_key_max_active_policy(tenant_id).to_dict()
    body["current_active"] = _count_active_keys(tenant_id)
    return body


@router.put(
    "/api-key-max-active",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_api_key_max_active_route(
    request: Request,
    payload: dict = Body(...),
) -> dict:
    """Set or clear the cap on active (non-revoked) API keys for the tenant.

    Body: ``{"max_active": int|null}``. ``null`` clears the policy and
    reverts to unbounded. When set, mints (``POST /v1/api-keys``) and
    rotations beyond the cap are rejected with 422 carrying
    ``api_key_max_active_reached``. Tightening the cap below the current
    active count does not retroactively revoke anyone; it only blocks
    the next mint until an admin frees a slot.
    """
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "JSON object body required.")
    if "max_active" not in payload:
        raise HTTPException(
            422, "Field 'max_active' is required (int or null)."
        )
    raw = payload["max_active"]
    if raw is not None and (isinstance(raw, bool) or not isinstance(raw, int)):
        raise HTTPException(422, "max_active must be an integer or null.")
    actor = getattr(request.state, "principal", None)
    try:
        cfg = set_api_key_max_active_policy(
            tenant_id, max_active=raw, updated_by=actor
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    body = cfg.to_dict()
    body["current_active"] = _count_active_keys(tenant_id)
    return body


@router.get(
    "/webhook-egress-hosts",
    dependencies=[require_role("admin")],
)
def get_webhook_egress_hosts_route(request: Request) -> dict:
    """Return the webhook egress host allowlist for the caller's tenant.

    Empty list means no policy: only the deployment-level SSRF block
    applies (private addresses, loopback, link-local, cloud metadata
    endpoints). When non-empty, every subscription URL must resolve to
    a hostname that matches one of the configured patterns.
    """
    tenant_id = _tenant(request)
    return {
        "tenant_id": tenant_id,
        "hosts": get_webhook_egress_allowed_hosts(tenant_id),
        "max_hosts": WEBHOOK_EGRESS_HOSTS_MAX,
    }


@router.put(
    "/webhook-egress-hosts",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_webhook_egress_hosts_route(
    request: Request,
    payload: dict = Body(...),
) -> dict:
    """Replace the webhook egress host allowlist for the caller's tenant.

    Empty list disables the policy. Entries can be exact hostnames
    (``hooks.example.com``) or leading-dot suffixes
    (``.example.com``) which match the apex and any subdomain.
    Wildcards are rejected so an admin cannot accidentally configure
    a permissive rule that looks restrictive. Tightening the policy
    takes effect on the next delivery for every existing subscription;
    nothing is retroactively unsubscribed.
    """
    tenant_id = _tenant(request)
    raw = payload.get("hosts")
    if not isinstance(raw, list):
        raise HTTPException(
            422,
            "Field 'hosts' must be a list of hostname strings.",
        )
    if len(raw) > WEBHOOK_EGRESS_HOSTS_MAX:
        raise HTTPException(
            422,
            f"At most {WEBHOOK_EGRESS_HOSTS_MAX} hosts are supported per tenant.",
        )
    actor = getattr(request.state, "principal", None)
    try:
        normalized = set_webhook_egress_allowed_hosts(
            tenant_id, raw, updated_by=actor
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "tenant_id": tenant_id,
        "hosts": normalized,
        "max_hosts": WEBHOOK_EGRESS_HOSTS_MAX,
    }
