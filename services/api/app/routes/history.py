"""History endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from shotclassify_common import Category, ClassificationRecord
from shotclassify_store import Repository

from ..middleware.rbac import require_role

router = APIRouter(prefix="/v1/history", tags=["history"])


@router.get("", response_model=list[ClassificationRecord], dependencies=[require_role("viewer")])
def list_history(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    category: Category | None = Query(None),
    q: str | None = Query(None, description="Full-text query over OCR text and filename"),
) -> list[ClassificationRecord]:
    tenant_id = getattr(request.state, "tenant_id", None)
    return Repository().list(limit=limit, category=category, query=q, tenant_id=tenant_id)


@router.get("/stats", dependencies=[require_role("viewer")])
def stats(request: Request):
    tenant_id = getattr(request.state, "tenant_id", None)
    return {"count": Repository().count(tenant_id=tenant_id)}


@router.get("/aggregate", dependencies=[require_role("viewer")])
def aggregate(request: Request, hours: int = Query(24, ge=1, le=24 * 30)):
    tenant_id = getattr(request.state, "tenant_id", None)
    return Repository().aggregate(tenant_id=tenant_id, hours=hours)


@router.get("/{item_id}", response_model=ClassificationRecord, dependencies=[require_role("viewer")])
def get_one(item_id: str, request: Request) -> ClassificationRecord:
    tenant_id = getattr(request.state, "tenant_id", None)
    rec = Repository().get(item_id, tenant_id=tenant_id)
    if not rec:
        raise HTTPException(404, "Not found.")
    return rec


@router.delete("/{item_id}", dependencies=[require_role("operator")])
def delete(item_id: str, request: Request):
    tenant_id = getattr(request.state, "tenant_id", None)
    if not Repository().delete(item_id, tenant_id=tenant_id):
        raise HTTPException(404, "Not found.")
    return {"ok": True}
