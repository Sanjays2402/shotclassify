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
    get_audit_retention_days,
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
    set_audit_retention_days,
    purge_expired_audit_for_tenant,
    MAX_AUDIT_RETENTION_DAYS,
    set_session_policy,
    set_session_idle_policy,
    set_sso_config,
    set_tenant_oidc,
    set_webhook_egress_allowed_hosts,
    WEBHOOK_EGRESS_HOSTS_MAX,
    get_webhook_autodisable_policy,
    set_webhook_autodisable_policy,
    WEBHOOK_AUTODISABLE_THRESHOLD_MIN,
    WEBHOOK_AUTODISABLE_THRESHOLD_MAX,
    UPLOAD_BYTES_MIN,
    UPLOAD_BYTES_MAX,
    get_upload_size_policy,
    set_upload_size_policy,
    ALLOWED_CONTENT_TYPES_MAX,
    KNOWN_IMAGE_CONTENT_TYPES,
    AllowedContentTypesPolicy,
    get_allowed_content_types,
    set_allowed_content_types,
    CMEK_PROVIDERS,
    CMEK_MODES,
    get_cmek_reference,
    set_cmek_reference,
    ALLOWED_INVITE_DOMAINS_MAX,
    get_allowed_invite_domains,
    set_allowed_invite_domains,
    ALLOWED_API_KEY_SCOPES_MAX,
    get_allowed_api_key_scopes,
    set_allowed_api_key_scopes,
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


@router.get("/audit-retention", dependencies=[require_role("admin")])
def get_audit_retention_route(request: Request) -> dict:
    """Read the per-tenant audit-log retention window.

    ``audit_retention_days`` is independent of the classifications retention
    window (``retention_days``) because enterprise customers negotiate the
    two separately: short GDPR windows (90 to 365 days) for data
    minimisation vs long SOC 2 / HIPAA windows (>= 365 days) for forensics.
    """
    tenant_id = _tenant(request)
    days = get_audit_retention_days(tenant_id)
    return {
        "tenant_id": tenant_id,
        "audit_retention_days": days,
        "enabled": bool(days),
        "max_days": MAX_AUDIT_RETENTION_DAYS,
    }


@router.put(
    "/audit-retention",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_audit_retention_route(
    request: Request,
    payload: dict = Body(...),
) -> dict:
    """Update the per-tenant audit-log retention window.

    Accepts ``{"audit_retention_days": int|null}``. ``null`` or ``0``
    disables the policy (keep audit data indefinitely). Lowering the
    window does not retroactively purge: the next scheduled or manual
    run does that. The change is recorded in the audit log via the
    middleware along with the actor, request id, client IP, and tenant.
    """
    tenant_id = _tenant(request)
    if "audit_retention_days" not in payload:
        raise HTTPException(
            422, "Field 'audit_retention_days' is required (int or null)."
        )
    actor = getattr(request.state, "principal", None)
    try:
        days = set_audit_retention_days(
            tenant_id, payload["audit_retention_days"], updated_by=actor
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {
        "tenant_id": tenant_id,
        "audit_retention_days": days,
        "enabled": bool(days),
        "max_days": MAX_AUDIT_RETENTION_DAYS,
    }


@router.post(
    "/audit-retention/run",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def run_audit_retention_route(request: Request) -> dict:
    """Manually trigger an audit-log purge for the caller's tenant.

    Same tenant scoping rules as the scheduled job. Rows in other
    tenants cannot be touched by this call even when the caller has
    admin role. Tenants on a legal hold are skipped and the response
    reports ``held=true``.
    """
    tenant_id = _tenant(request)
    result = purge_expired_audit_for_tenant(tenant_id)
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


# ---------------------------------------------------------------------------
# Per-tenant max upload byte cap (classify routes)
# ---------------------------------------------------------------------------


@router.get("/upload-size", dependencies=[require_role("admin")])
def get_upload_size_route(request: Request) -> dict:
    """Return the tenant's per-upload byte cap (or null = no policy)."""
    tenant_id = _tenant(request)
    return get_upload_size_policy(tenant_id).to_dict()


@router.put(
    "/upload-size",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_upload_size_route(
    request: Request,
    payload: dict = Body(...),
) -> dict:
    """Set or clear the per-tenant max upload size in bytes.

    Body: ``{"max_upload_bytes": int|null}``. ``null`` clears the policy
    and the tenant falls back to the deployment-wide global limit. When
    set, every ``POST /v1/classify``, ``POST /v1/classify/batch``, and
    ``POST /v1/queue`` upload whose declared or buffered size exceeds
    the cap is rejected with HTTP 413 ``upload_too_large`` before the
    bytes hit disk or the model.
    """
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "JSON object body required.")
    if "max_upload_bytes" not in payload:
        raise HTTPException(
            422, "Field 'max_upload_bytes' is required (int or null)."
        )
    raw = payload["max_upload_bytes"]
    if raw is not None and (isinstance(raw, bool) or not isinstance(raw, int)):
        raise HTTPException(422, "max_upload_bytes must be an integer or null.")
    actor = getattr(request.state, "principal", None)
    try:
        cfg = set_upload_size_policy(
            tenant_id, max_upload_bytes=raw, updated_by=actor
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return cfg.to_dict()


# ---------------------------------------------------------------------------
# Per-tenant allowed upload content types (classify routes)
# ---------------------------------------------------------------------------


@router.get("/upload-content-types", dependencies=[require_role("admin")])
def get_upload_content_types_route(request: Request) -> dict:
    """Return the tenant's allow-list of upload Content-Type values.

    An empty list means no policy: the classify routes accept any
    ``image/*`` MIME (legacy behaviour). A non-empty list locks the
    upload surface to exactly those types.
    """
    tenant_id = _tenant(request)
    return get_allowed_content_types(tenant_id).to_dict()


@router.put(
    "/upload-content-types",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_upload_content_types_route(
    request: Request,
    payload: dict = Body(...),
) -> dict:
    """Replace the per-tenant allow-list of upload Content-Type values.

    Body: ``{"types": ["image/png", "image/jpeg"]}`` or
    ``{"types": []}`` / ``{"types": null}`` to clear the policy.
    Each entry is normalised (lower-cased, MIME parameters stripped)
    and validated as a basic ``type/subtype`` token; duplicates are
    collapsed; the persisted list is sorted for stable diffs in the
    audit log. Tenant-scoped: the value never affects another
    workspace's classify route.
    """
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "JSON object body required.")
    if "types" not in payload:
        raise HTTPException(422, "Field 'types' is required (list or null).")
    raw = payload["types"]
    if raw is not None and not isinstance(raw, list):
        raise HTTPException(422, "types must be a list of strings or null.")
    actor = getattr(request.state, "principal", None)
    try:
        cfg = set_allowed_content_types(
            tenant_id, types=raw, updated_by=actor
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return cfg.to_dict()


# ---------------------------------------------------------------------------
# Per-tenant Customer-Managed Encryption Key (CMEK) reference
# ---------------------------------------------------------------------------


@router.get("/cmek", dependencies=[require_role("admin")])
def get_cmek_route(request: Request) -> dict:
    """Return the workspace CMEK declaration.

    Procurement and security reviewers use this to confirm which key in
    which customer KMS encrypts the workspace's data at rest and which
    enforcement mode is active.
    """
    tenant_id = _tenant(request)
    return get_cmek_reference(tenant_id).to_dict()


@router.put(
    "/cmek",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_cmek_route(
    request: Request,
    payload: dict = Body(...),
) -> dict:
    """Update the workspace Customer-Managed Encryption Key declaration.

    Body: ``{"provider": str|null, "key_uri": str|null, "mode": str}``.
    ``mode`` is one of ``disabled``, ``advisory``, ``required``. When
    ``mode != "disabled"`` both ``provider`` and ``key_uri`` are
    required; the URI prefix is sanity-checked against the provider
    (e.g. ``arn:aws:kms:`` for ``aws-kms``). The change is recorded by
    the audit middleware with the actor, IP, user agent, and request
    id; admin role and a fresh MFA step-up are mandatory because this
    declaration is what the buyer's auditor will inspect.
    """
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "JSON object body required.")
    if "mode" not in payload:
        raise HTTPException(
            422,
            "Field 'mode' is required (one of "
            f"{list(CMEK_MODES)}).",
        )
    actor = getattr(request.state, "principal", None)
    try:
        cfg = set_cmek_reference(
            tenant_id,
            provider=payload.get("provider"),
            key_uri=payload.get("key_uri"),
            mode=payload.get("mode"),
            updated_by=actor,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return cfg.to_dict()


# Emergency write lockdown (\"freeze\"). One toggle a workspace owner pulls
# during a suspected incident: leaked admin token, departing insider,
# anomalous traffic. While engaged, ``FreezeMiddleware`` rejects every
# state-changing request scoped to this tenant with HTTP 423
# ``tenant_frozen``. Reads stay open so investigators and exporters
# keep working. Engaging *and* lifting require admin role + a fresh
# MFA step-up so a stolen session cookie cannot silently flip the
# switch in either direction.
@router.get("/freeze", dependencies=[require_role("admin")])
def get_freeze_route(request: Request) -> dict:
    """Return the current freeze state for the caller's tenant."""
    from shotclassify_store import get_freeze_state

    tenant_id = _tenant(request)
    return get_freeze_state(tenant_id).to_dict()


@router.post(
    "/freeze",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def engage_freeze_route(
    request: Request,
    payload: dict = Body(...),
) -> dict:
    """Engage the freeze. Body: ``{\"reason\": str}``.

    ``reason`` is mandatory, surfaced in the 423 error body so every
    blocked caller knows why their write failed, and shown in the
    dashboard banner. Idempotent: re-engaging while already frozen
    refreshes the reason and ``engaged_at``.
    """
    from shotclassify_store import engage_freeze

    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "JSON object body required.")
    reason = payload.get("reason")
    actor = getattr(request.state, "principal", None)
    try:
        state = engage_freeze(tenant_id, reason, engaged_by=actor)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return state.to_dict()


@router.delete(
    "/freeze",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def lift_freeze_route(request: Request) -> dict:
    """Lift the freeze for the caller's tenant.

    Clears the reason and ``engaged_at`` so the banner returns to the
    not-engaged copy. Idempotent against a tenant that is not frozen.
    """
    from shotclassify_store import lift_freeze

    tenant_id = _tenant(request)
    actor = getattr(request.state, "principal", None)
    state = lift_freeze(tenant_id, lifted_by=actor)
    return state.to_dict()


@router.get("/invite-domains", dependencies=[require_role("admin")])
def get_invite_domains_route(request: Request) -> dict:
    """Return the per-tenant allowed-email-domains policy.

    Empty list means no policy: any email may be invited or auto-joined
    via SSO / SCIM. When non-empty, every invite, SSO auto-join, and
    SCIM provision is gated by domain match.
    """
    tenant_id = _tenant(request)
    return {
        "tenant_id": tenant_id,
        "allowed_domains": get_allowed_invite_domains(tenant_id),
        "max_entries": ALLOWED_INVITE_DOMAINS_MAX,
    }


@router.put(
    "/invite-domains",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_invite_domains_route(
    request: Request,
    payload: dict = Body(...),
) -> dict:
    """Replace the allowed-email-domains policy for the caller's tenant.

    Send ``{"allowed_domains": []}`` to disable enforcement and accept
    any email again. Entries beginning with a leading dot match every
    sub-domain (``.acme.com`` matches ``ops.acme.com``).
    """
    tenant_id = _tenant(request)
    raw = payload.get("allowed_domains")
    if not isinstance(raw, list):
        raise HTTPException(
            422,
            "Field 'allowed_domains' must be a list of email domain strings.",
        )
    if len(raw) > ALLOWED_INVITE_DOMAINS_MAX:
        raise HTTPException(
            422,
            f"At most {ALLOWED_INVITE_DOMAINS_MAX} allowed-invite domains are supported per tenant.",
        )
    actor = getattr(request.state, "principal", None)
    try:
        normalized = set_allowed_invite_domains(tenant_id, raw, updated_by=actor)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "tenant_id": tenant_id,
        "allowed_domains": normalized,
        "max_entries": ALLOWED_INVITE_DOMAINS_MAX,
    }


# ---------------------------------------------------------------------------
# Per-tenant webhook auto-disable threshold (circuit breaker)
# ---------------------------------------------------------------------------


@router.get(
    "/webhook-autodisable",
    dependencies=[require_role("admin")],
)
def get_webhook_autodisable_route(request: Request) -> dict:
    """Return the tenant's webhook auto-disable threshold.

    ``threshold = null`` means no policy: the dispatcher will keep
    retrying a failing subscription forever (legacy behaviour). When
    set, the dispatcher pauses any subscription whose consecutive
    failed deliveries reach the threshold.
    """
    tenant_id = _tenant(request)
    return get_webhook_autodisable_policy(tenant_id).to_dict()


@router.put(
    "/webhook-autodisable",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_webhook_autodisable_route(
    request: Request,
    payload: dict = Body(...),
) -> dict:
    """Set or clear the tenant's webhook auto-disable threshold.

    Send ``{"threshold": null}`` to disable the breaker entirely.
    A positive integer enables it: after that many consecutive failed
    deliveries on the same subscription, the dispatcher pauses the
    subscription so it stops hammering a downstream receiver that is
    clearly down. Operators resume manually once the receiver is back.
    Bounds are enforced server-side; out-of-range values return 422.
    """
    tenant_id = _tenant(request)
    raw = payload.get("threshold", "__missing__")
    if raw == "__missing__":
        raise HTTPException(
            422,
            "Field 'threshold' is required (integer or null).",
        )
    if raw is not None and (isinstance(raw, bool) or not isinstance(raw, int)):
        raise HTTPException(
            422,
            "Field 'threshold' must be an integer or null.",
        )
    actor = getattr(request.state, "principal", None)
    try:
        policy = set_webhook_autodisable_policy(
            tenant_id, threshold=raw, updated_by=actor
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return policy.to_dict()


# ---------------------------------------------------------------------------
# Per-tenant allowed API key scopes (migration 0044)
# ---------------------------------------------------------------------------


@router.get("/api-key-scopes", dependencies=[require_role("admin")])
def get_api_key_scopes_policy_route(request: Request) -> dict:
    """Return the per-tenant allowed API key scopes policy.

    Empty list means no policy: every catalog-valid scope may be granted.
    When non-empty, ``POST /v1/api-keys`` and the rotate endpoint reject
    any request whose scope set is not a subset of the policy.
    """
    from shotclassify_store.api_keys import VALID_SCOPES

    tenant_id = _tenant(request)
    return {
        "tenant_id": tenant_id,
        "allowed_scopes": get_allowed_api_key_scopes(tenant_id),
        "available_scopes": sorted(VALID_SCOPES),
        "max_entries": ALLOWED_API_KEY_SCOPES_MAX,
    }


@router.put(
    "/api-key-scopes",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_api_key_scopes_policy_route(
    request: Request,
    payload: dict = Body(...),
) -> dict:
    """Replace the allowed API key scopes policy for the caller's tenant.

    Send ``{"allowed_scopes": []}`` to disable enforcement and accept any
    catalog-valid scope again. Unknown scope strings are rejected with
    HTTP 422 so an admin cannot persist a typo.
    """
    from shotclassify_store.api_keys import VALID_SCOPES

    tenant_id = _tenant(request)
    raw = payload.get("allowed_scopes")
    if not isinstance(raw, list):
        raise HTTPException(
            422,
            "Field 'allowed_scopes' must be a list of scope id strings.",
        )
    if len(raw) > ALLOWED_API_KEY_SCOPES_MAX:
        raise HTTPException(
            422,
            f"At most {ALLOWED_API_KEY_SCOPES_MAX} allowed scopes are supported per tenant.",
        )
    actor = getattr(request.state, "principal", None)
    try:
        normalized = set_allowed_api_key_scopes(tenant_id, raw, updated_by=actor)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "tenant_id": tenant_id,
        "allowed_scopes": normalized,
        "available_scopes": sorted(VALID_SCOPES),
        "max_entries": ALLOWED_API_KEY_SCOPES_MAX,
    }


# ---------------------------------------------------------------- dual control

from shotclassify_store import dual_control_store as _dual_control


@router.get("/dual-control", dependencies=[require_role("admin")])
def get_dual_control_route(request: Request) -> dict:
    """Return the dual-control (two-person rule) policy for the caller's tenant."""
    tenant_id = _tenant(request)
    return {
        "tenant_id": tenant_id,
        "enabled": _dual_control.get_policy(tenant_id),
        "protected_scopes": sorted(_dual_control.PROTECTED_SCOPES),
        "request_ttl_hours": _dual_control.DEFAULT_TTL_HOURS,
    }


@router.put(
    "/dual-control",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_dual_control_route(request: Request, payload: dict = Body(...)) -> dict:
    """Toggle the dual-control policy.

    Body: ``{"enabled": bool}``. When enabled, every new API key request
    that includes a protected scope (today: ``admin``) lands in the
    issuance queue and must be approved by a different admin before the
    plaintext token is minted. Existing keys are unaffected; rotation
    flows through the same gate.
    """
    if not isinstance(payload, dict):
        raise HTTPException(422, "Body must be a JSON object.")
    if "enabled" not in payload or not isinstance(payload["enabled"], bool):
        raise HTTPException(422, "Field 'enabled' must be a boolean.")
    tenant_id = _tenant(request)
    actor = getattr(request.state, "principal", None)
    new_value = _dual_control.set_policy(
        tenant_id, enabled=payload["enabled"], updated_by=actor
    )
    return {
        "tenant_id": tenant_id,
        "enabled": new_value,
        "protected_scopes": sorted(_dual_control.PROTECTED_SCOPES),
        "request_ttl_hours": _dual_control.DEFAULT_TTL_HOURS,
    }
