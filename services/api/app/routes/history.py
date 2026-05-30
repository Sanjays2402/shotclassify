"""History endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from shotclassify_common import Category, ClassificationRecord
from shotclassify_store import Repository

from ..middleware.rbac import require_role

router = APIRouter(prefix="/v1/history", tags=["history"])


@router.get("", response_model=list[ClassificationRecord], dependencies=[require_role("viewer")])
def list_history(
    limit: int = Query(50, ge=1, le=500),
    category: Category | None = Query(None),
    q: str | None = Query(None, description="Full-text query over OCR text and filename"),
) -> list[ClassificationRecord]:
    return Repository().list(limit=limit, category=category, query=q)


@router.get("/stats", dependencies=[require_role("viewer")])
def stats():
    return {"count": Repository().count()}


@router.get("/{item_id}", response_model=ClassificationRecord, dependencies=[require_role("viewer")])
def get_one(item_id: str) -> ClassificationRecord:
    rec = Repository().get(item_id)
    if not rec:
        raise HTTPException(404, "Not found.")
    return rec


@router.delete("/{item_id}", dependencies=[require_role("operator")])
def delete(item_id: str):
    if not Repository().delete(item_id):
        raise HTTPException(404, "Not found.")
    return {"ok": True}
