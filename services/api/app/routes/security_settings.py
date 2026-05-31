"""Per-tenant security settings: read and update the IP allowlist.

These endpoints are admin-only. Reads return the active list for the
caller's resolved tenant. Writes replace the list atomically and the
audit log middleware records the change with the actor, request id,
client IP, and target tenant.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from shotclassify_store import (
    get_ip_allowlist,
    get_privacy_settings,
    get_retention_days,
    get_sso_config,
    purge_expired_for_tenant,
    set_ip_allowlist,
    set_privacy_settings,
    set_retention_days,
    set_sso_config,
)

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
