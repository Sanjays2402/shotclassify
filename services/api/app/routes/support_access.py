"""Tenant-controlled support access grants.

Endpoints let a workspace owner explicitly authorize, list, and revoke
time-boxed vendor-side admin access into their tenant. Without an active
grant the tenant resolution middleware refuses any cross-tenant admin
scoping via ``X-Tenant``.

All write paths require admin role + MFA step-up, are audit-logged, and
honor ``?dry_run=true``. The vendor-side cross-tenant overview is a
separate admin-only endpoint at ``/v1/admin/support-access/active``.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from shotclassify_store import (
    SUPPORT_ACCESS_MAX_GRANT_HOURS,
    SUPPORT_ACCESS_MIN_GRANT_MINUTES,
    SupportAccessValidationError,
    support_access_store,
)

from ..dryrun import dry_run_query, mark_dry_run
from ..middleware.mfa import require_mfa_step_up
from ..middleware.rbac import require_role, require_scope


router = APIRouter(prefix="/v1", tags=["support-access"])


class CreateGrantRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1024)
    duration_minutes: int = Field(
        ge=SUPPORT_ACCESS_MIN_GRANT_MINUTES,
        le=SUPPORT_ACCESS_MAX_GRANT_HOURS * 60,
    )
    allowed_admin: str | None = Field(default=None, max_length=256)


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=422,
            detail="A tenant context is required. Pass X-Tenant or sign in to a workspace.",
        )
    return tenant_id


@router.get("/support-access", dependencies=[require_scope("read:audit")])
def list_grants(
    request: Request,
    include_inactive: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
    _: str = require_role("admin"),
):
    """List support access grants for the caller's workspace."""
    tenant_id = _require_tenant(request)
    grants = support_access_store.list_for_tenant(
        tenant_id, include_inactive=include_inactive, limit=limit
    )
    return {
        "grants": [g.to_dict() for g in grants],
        "tenant_id": tenant_id,
        "policy": {
            "min_minutes": SUPPORT_ACCESS_MIN_GRANT_MINUTES,
            "max_minutes": SUPPORT_ACCESS_MAX_GRANT_HOURS * 60,
        },
    }


@router.post(
    "/support-access",
    dependencies=[require_mfa_step_up(), require_scope("admin")],
)
def create_grant(
    payload: CreateGrantRequest,
    request: Request,
    dry_run: bool = dry_run_query(),
    _: str = require_role("admin"),
):
    """Authorize time-boxed vendor admin access into this workspace."""
    tenant_id = _require_tenant(request)
    created_by = getattr(request.state, "principal", None) or "unknown"
    if dry_run:
        return mark_dry_run(
            request,
            would_create={
                "tenant_id": tenant_id,
                "reason": payload.reason,
                "duration_minutes": payload.duration_minutes,
                "allowed_admin": payload.allowed_admin,
            },
        )
    try:
        grant = support_access_store.create_grant(
            tenant_id=tenant_id,
            reason=payload.reason,
            created_by=str(created_by),
            duration_minutes=payload.duration_minutes,
            allowed_admin=payload.allowed_admin,
        )
    except SupportAccessValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    request.state.audit_target_id = grant.id
    return {"grant": grant.to_dict()}


@router.get("/support-access/{grant_id}", dependencies=[require_scope("read:audit")])
def get_grant(
    grant_id: str,
    request: Request,
    _: str = require_role("admin"),
):
    tenant_id = _require_tenant(request)
    grant = support_access_store.get_grant(grant_id, tenant_id=tenant_id)
    if grant is None:
        raise HTTPException(404, "Grant not found.")
    return {"grant": grant.to_dict()}


@router.delete(
    "/support-access/{grant_id}",
    dependencies=[require_mfa_step_up(), require_scope("admin")],
)
def revoke_grant(
    grant_id: str,
    request: Request,
    dry_run: bool = dry_run_query(),
    _: str = require_role("admin"),
):
    tenant_id = _require_tenant(request)
    existing = support_access_store.get_grant(grant_id, tenant_id=tenant_id)
    if existing is None:
        raise HTTPException(404, "Grant not found.")
    if dry_run:
        request.state.audit_target_id = grant_id
        return mark_dry_run(
            request,
            would_revoke={
                "id": existing.id,
                "currently_active": existing.active,
                "expires_at": existing.to_dict()["expires_at"],
            },
        )
    revoked = support_access_store.revoke_grant(
        grant_id,
        tenant_id=tenant_id,
        revoked_by=str(getattr(request.state, "principal", None) or "unknown"),
    )
    if revoked is None:
        raise HTTPException(404, "Grant not found.")
    request.state.audit_target_id = grant_id
    return {"grant": revoked.to_dict()}


# Vendor-side cross-tenant overview. Lives under /v1/admin so the existing
# admin console route grouping picks it up. Admin role only; this is the
# operational view of which workspaces currently have vendor access open.
admin_router = APIRouter(prefix="/v1/admin", tags=["support-access"])


@admin_router.get(
    "/support-access/active",
    dependencies=[require_scope("admin")],
)
def list_active_grants(
    request: Request,
    limit: int = Query(200, ge=1, le=1000),
    _: str = require_role("admin"),
):
    """Cross-tenant view of every currently-active grant."""
    grants = support_access_store.list_all_active(limit=limit)
    return {"grants": [g.to_dict() for g in grants], "count": len(grants)}
