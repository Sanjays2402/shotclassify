"""Per-tenant security settings: read and update the IP allowlist.

These endpoints are admin-only. Reads return the active list for the
caller's resolved tenant. Writes replace the list atomically and the
audit log middleware records the change with the actor, request id,
client IP, and target tenant.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from shotclassify_store import (
    SESSION_TTL_MAX_MINUTES,
    SESSION_TTL_MIN_MINUTES,
    get_ip_allowlist,
    get_privacy_settings,
    get_retention_days,
    get_session_policy,
    get_sso_config,
    purge_expired_for_tenant,
    set_ip_allowlist,
    set_privacy_settings,
    set_retention_days,
    set_session_policy,
    set_sso_config,
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
