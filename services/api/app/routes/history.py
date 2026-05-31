"""History endpoints."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from shotclassify_common import Category, ClassificationRecord
from shotclassify_store import Repository

from ..middleware.rbac import require_role

router = APIRouter(prefix="/v1/history", tags=["history"])

EXPORT_MAX = 5000
EXPORT_COLUMNS = [
    "id",
    "created_at",
    "filename",
    "primary_category",
    "confidence",
    "user_corrected_to",
    "ocr_text",
    "image_path",
]


def _record_to_row(rec: ClassificationRecord) -> dict:
    return {
        "id": rec.id,
        "created_at": rec.created_at.isoformat() if rec.created_at else "",
        "filename": rec.filename,
        "primary_category": (
            rec.primary_category.value
            if hasattr(rec.primary_category, "value")
            else str(rec.primary_category)
        ),
        "confidence": f"{rec.confidence:.6f}",
        "user_corrected_to": (
            rec.user_corrected_to.value
            if rec.user_corrected_to and hasattr(rec.user_corrected_to, "value")
            else (str(rec.user_corrected_to) if rec.user_corrected_to else "")
        ),
        "ocr_text": (rec.ocr_text or "").replace("\r", " ").replace("\n", " "),
        "image_path": rec.image_path or "",
    }


@router.get("/export", dependencies=[require_role("viewer")])
def export_history(
    request: Request,
    format: str = Query("csv", pattern="^(csv|json)$"),
    limit: int = Query(1000, ge=1, le=EXPORT_MAX),
    category: Category | None = Query(None),
    q: str | None = Query(None, description="Full-text query over OCR text and filename"),
):
    """Stream classification history as CSV or JSON for download."""
    tenant_id = getattr(request.state, "tenant_id", None)
    records = Repository().list(limit=limit, category=category, query=q, tenant_id=tenant_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if format == "json":
        payload = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "count": len(records),
            "filters": {
                "category": category.value if category else None,
                "q": q,
                "limit": limit,
            },
            "records": [json.loads(r.model_dump_json()) for r in records],
        }
        body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        return StreamingResponse(
            iter([body]),
            media_type="application/json",
            headers={
                "content-disposition": f'attachment; filename="shotclassify-history-{stamp}.json"',
                "x-record-count": str(len(records)),
            },
        )

    def _csv_iter():
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        yield buf.getvalue()
        for rec in records:
            buf.seek(0)
            buf.truncate(0)
            writer.writerow(_record_to_row(rec))
            yield buf.getvalue()

    return StreamingResponse(
        _csv_iter(),
        media_type="text/csv; charset=utf-8",
        headers={
            "content-disposition": f'attachment; filename="shotclassify-history-{stamp}.csv"',
            "x-record-count": str(len(records)),
        },
    )


@router.get("", response_model=list[ClassificationRecord], dependencies=[require_role("viewer")])
def list_history(
    request: Request,
    response: Response,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0, le=100_000),
    category: Category | None = Query(None),
    q: str | None = Query(None, description="Full-text query over OCR text and filename"),
    since: datetime | None = Query(None, description="Include records at or after this UTC timestamp"),
    until: datetime | None = Query(None, description="Include records at or before this UTC timestamp"),
    min_conf: float | None = Query(None, ge=0.0, le=1.0),
    max_conf: float | None = Query(None, ge=0.0, le=1.0),
    sort: str = Query("new", pattern="^(new|old|conf_asc|conf_desc)$"),
) -> list[ClassificationRecord]:
    tenant_id = getattr(request.state, "tenant_id", None)
    repo = Repository()
    items = repo.list(
        limit=limit,
        offset=offset,
        category=category,
        query=q,
        tenant_id=tenant_id,
        since=since,
        until=until,
        min_conf=min_conf,
        max_conf=max_conf,
        sort=sort,
    )
    total = repo.count_filtered(
        category=category,
        query=q,
        tenant_id=tenant_id,
        since=since,
        until=until,
        min_conf=min_conf,
        max_conf=max_conf,
    )
    response.headers["x-total-count"] = str(total)
    response.headers["x-offset"] = str(offset)
    response.headers["x-limit"] = str(limit)
    response.headers["access-control-expose-headers"] = "x-total-count, x-offset, x-limit"
    return items


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
