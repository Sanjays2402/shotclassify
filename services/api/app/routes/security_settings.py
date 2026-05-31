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
    get_retention_days,
    get_sso_config,
    purge_expired_for_tenant,
    set_ip_allowlist,
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
    if domain is not None and not isinstance(domain, str):
        raise HTTPException(422, "'domain' must be a string or null.")
    if provider is not None and not isinstance(provider, str):
        raise HTTPException(422, "'provider' must be a string or null.")
    actor = getattr(request.state, "principal", None)
    try:
        cfg = set_sso_config(
            tenant_id,
            enforced=enforced,
            domain=domain or None,
            provider=provider or None,
            updated_by=actor,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return cfg.to_dict()
