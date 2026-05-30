"""Audit log read API.

Lets operators query the persisted audit trail. Writes happen automatically
via the AuditLogMiddleware on every authenticated mutating request.
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from shotclassify_store import AuditRepository

from ..middleware.rbac import require_role

router = APIRouter(prefix="/v1/audit", tags=["audit"], dependencies=[require_role("admin")])


@router.get("")
def list_audit(
    limit: int = Query(100, ge=1, le=1000),
    principal: str | None = Query(None, description="Filter by principal (login or 'api-key')"),
    path_prefix: str | None = Query(None, description="Filter by path prefix, e.g. /v1/history"),
):
    return AuditRepository().list(limit=limit, principal=principal, path_prefix=path_prefix)


@router.get("/stats")
def stats():
    return {"count": AuditRepository().count()}
