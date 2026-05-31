"""Audit log read API.

Lets operators query the persisted audit trail. Writes happen automatically
via the AuditLogMiddleware on every authenticated mutating request.
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from shotclassify_store import AuditRepository

from ..middleware.rbac import require_role, require_scope

router = APIRouter(prefix="/v1/audit", tags=["audit"], dependencies=[require_role("admin"), require_scope("read:audit")])


@router.get("")
def list_audit(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    principal: str | None = Query(None, description="Filter by principal (login or 'api-key')"),
    path_prefix: str | None = Query(None, description="Filter by path prefix, e.g. /v1/history"),
):
    # Admins are still scoped to their resolved tenant unless they explicitly
    # opt into a cross-tenant view via X-Tenant: *, which sets tenant_id to None.
    tenant_id = getattr(request.state, "tenant_id", None)
    return AuditRepository().list(
        limit=limit, principal=principal, path_prefix=path_prefix, tenant_id=tenant_id
    )


@router.get("/stats")
def stats():
    return {"count": AuditRepository().count()}
