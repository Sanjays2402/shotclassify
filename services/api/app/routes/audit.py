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


@router.get("/verify")
def verify(request: Request):
    """Recompute the tamper-evident hash chain for the caller's workspace.

    Returns ok=true plus the current tip hash when every row in scope hashes
    to its stored ``entry_hash`` and links to the prior row's hash. If any
    row has been edited, deleted out of order, or inserted out of band,
    returns ok=false plus the id of the first row where the chain breaks.

    Owners can pin the returned ``tip_hash`` off-platform (e.g. in a quarterly
    compliance report) so future tampering of historical rows is detectable
    even by an attacker who also controls this endpoint.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    return AuditRepository().verify_chain(tenant_id=tenant_id)
