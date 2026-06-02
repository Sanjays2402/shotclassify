"""History endpoints."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from shotclassify_common import Category, ClassificationRecord
from shotclassify_store import LegalHoldActive, Repository

from ..dryrun import dry_run_query, mark_dry_run
from ..middleware.rbac import require_role, require_scope

router = APIRouter(prefix="/v1/history", tags=["history"])

EXPORT_MAX = 5000
# Mirror of the per-record tag cap enforced inside
# ``shotclassify_store.repository.update_meta``. Kept in sync here so the
# route can return a clear 400 instead of silently dropping tags on write.
MAX_TAGS_PER_RECORD = 16
EXPORT_COLUMNS = [
    "id",
    "created_at",
    "filename",
    "primary_category",
    "confidence",
    "user_corrected_to",
    "label",
    "tags",
    "pinned",
    "ocr_text",
    "blob_url",
]


def _validate_range_filters(
    min_conf: float | None,
    max_conf: float | None,
    since: datetime | None,
    until: datetime | None,
) -> None:
    """Reject filter ranges that can never match anything.

    Previously the API silently returned an empty list when the caller
    inverted a range (e.g. ``min_conf=0.9&max_conf=0.1`` from a fat-fingered
    slider, or ``since`` after ``until`` from a misconfigured saved view).
    That looks identical to "no results" and burns real debug time.
    """
    if min_conf is not None and max_conf is not None and min_conf > max_conf:
        raise HTTPException(
            status_code=400,
            detail=f"min_conf ({min_conf}) must be <= max_conf ({max_conf}).",
        )
    if since is not None and until is not None:
        # Both params are documented as UTC timestamps but FastAPI happily
        # parses naive ISO strings (no trailing Z/offset) as tz-naive
        # datetimes. Comparing a naive datetime to an aware one raises
        # TypeError and surfaces to the caller as a confusing 500. Normalize
        # naive values to UTC before comparing so a mixed pair (one with Z,
        # one without) still gets the clear 400 the caller expects.
        since_cmp = since if since.tzinfo is not None else since.replace(tzinfo=timezone.utc)
        until_cmp = until if until.tzinfo is not None else until.replace(tzinfo=timezone.utc)
        if since_cmp > until_cmp:
            raise HTTPException(
                status_code=400,
                detail="`since` must be earlier than or equal to `until`.",
            )


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
        "label": rec.label or "",
        "tags": ",".join(rec.tags or []),
        "pinned": "true" if rec.pinned else "false",
        "ocr_text": (rec.ocr_text or "").replace("\r", " ").replace("\n", " "),
        "blob_url": f"/v1/blobs/{rec.id}" if rec.image_path else "",
    }


@router.get("/export", dependencies=[require_role("viewer"), require_scope("read:classifications")])
def export_history(
    request: Request,
    format: str = Query("csv", pattern="^(csv|json|ndjson)$"),
    limit: int = Query(1000, ge=1, le=EXPORT_MAX),
    category: Category | None = Query(None),
    q: str | None = Query(None, description="Full-text query over OCR text and filename"),
    since: datetime | None = Query(None, description="Include records at or after this UTC timestamp"),
    until: datetime | None = Query(None, description="Include records at or before this UTC timestamp"),
    min_conf: float | None = Query(None, ge=0.0, le=1.0),
    max_conf: float | None = Query(None, ge=0.0, le=1.0),
    sort: str = Query("new", pattern="^(new|old|conf_asc|conf_desc)$"),
    tag: str | None = Query(None, max_length=32, description="Filter by a single tag (case-insensitive)."),
    pinned: bool | None = Query(None, description="If true, only pinned; if false, only unpinned."),
):
    """Stream classification history as CSV or JSON for download.

    Accepts the same filters as ``GET /v1/history`` so a download from the
    dashboard matches what the user is currently looking at.
    """
    _validate_range_filters(min_conf, max_conf, since, until)
    tenant_id = getattr(request.state, "tenant_id", None)
    records = Repository().list(
        limit=limit,
        category=category,
        query=q,
        tenant_id=tenant_id,
        since=since,
        until=until,
        min_conf=min_conf,
        max_conf=max_conf,
        sort=sort,
        tag=tag,
        pinned=pinned,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if format == "ndjson":
        # Newline-delimited JSON: one record per line, no wrapper object.
        # Streams cleanly into BigQuery / Snowflake / `jq` / `wc -l` pipelines.
        def _ndjson_iter():
            for rec in records:
                yield rec.model_dump_json() + "\n"

        return StreamingResponse(
            _ndjson_iter(),
            media_type="application/x-ndjson",
            headers={
                "content-disposition": f'attachment; filename="shotclassify-history-{stamp}.ndjson"',
                "x-record-count": str(len(records)),
            },
        )

    if format == "json":
        payload = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "count": len(records),
            "filters": {
                "category": category.value if category else None,
                "q": q,
                "limit": limit,
                "since": since.isoformat() if since else None,
                "until": until.isoformat() if until else None,
                "min_conf": min_conf,
                "max_conf": max_conf,
                "sort": sort,
                "tag": tag,
                "pinned": pinned,
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


@router.get("", response_model=list[ClassificationRecord], dependencies=[require_role("viewer"), require_scope("read:classifications")])
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
    tag: str | None = Query(None, max_length=32, description="Filter by a single tag (case-insensitive)."),
    pinned: bool | None = Query(None, description="If true, only pinned; if false, only unpinned."),
) -> list[ClassificationRecord]:
    _validate_range_filters(min_conf, max_conf, since, until)
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
        tag=tag,
        pinned=pinned,
    )
    total = repo.count_filtered(
        category=category,
        query=q,
        tenant_id=tenant_id,
        since=since,
        until=until,
        min_conf=min_conf,
        max_conf=max_conf,
        tag=tag,
        pinned=pinned,
    )
    response.headers["x-total-count"] = str(total)
    response.headers["x-offset"] = str(offset)
    response.headers["x-limit"] = str(limit)
    response.headers["access-control-expose-headers"] = "x-total-count, x-offset, x-limit"
    return items


@router.get("/stats", dependencies=[require_role("viewer"), require_scope("read:classifications")])
def stats(request: Request):
    tenant_id = getattr(request.state, "tenant_id", None)
    return {"count": Repository().count(tenant_id=tenant_id)}


@router.get("/aggregate", dependencies=[require_role("viewer"), require_scope("read:classifications")])
def aggregate(request: Request, hours: int = Query(24, ge=1, le=24 * 30)):
    tenant_id = getattr(request.state, "tenant_id", None)
    return Repository().aggregate(tenant_id=tenant_id, hours=hours)


@router.get("/{item_id}", response_model=ClassificationRecord, dependencies=[require_role("viewer"), require_scope("read:classifications")])
def get_one(item_id: str, request: Request) -> ClassificationRecord:
    tenant_id = getattr(request.state, "tenant_id", None)
    rec = Repository().get(item_id, tenant_id=tenant_id)
    if not rec:
        raise HTTPException(404, "Not found.")
    return rec


@router.post("/bulk", dependencies=[require_role("operator"), require_scope("write:classifications")])
def bulk(request: Request, payload: dict = Body(...), dry_run: bool = dry_run_query()) -> dict:
    """Apply an action to many saved shots at once.

    Body fields:
      * ``ids`` (list[string], required, 1..500): record ids to act on.
      * ``action`` (string, required): one of ``delete``, ``tag_add``,
        ``tag_remove``.
      * ``tags`` (list[string], required for tag actions): tags to add or
        remove. Each tag is trimmed, lowercased, and capped at 32 chars.

    Returns ``{ok, action, requested, affected, missing}`` where ``affected``
    counts rows that actually changed (or were deleted), and ``missing`` lists
    ids that were not found or belong to another tenant.
    """
    if not isinstance(payload, dict):
        raise HTTPException(400, "Body must be a JSON object.")
    ids_in = payload.get("ids")
    if not isinstance(ids_in, list) or not ids_in:
        raise HTTPException(400, "`ids` must be a non-empty list of strings.")
    if len(ids_in) > 500:
        raise HTTPException(400, "Too many ids (max 500 per request).")
    ids: list[str] = []
    for i in ids_in:
        if not isinstance(i, str) or not i.strip():
            raise HTTPException(400, "`ids` must contain non-empty strings.")
        ids.append(i.strip())
    action = payload.get("action")
    if action not in {"delete", "tag_add", "tag_remove", "pin", "unpin"}:
        raise HTTPException(
            400, "`action` must be one of: delete, tag_add, tag_remove, pin, unpin."
        )
    tags_in: list[str] = []
    if action in {"tag_add", "tag_remove"}:
        raw_tags = payload.get("tags")
        if not isinstance(raw_tags, list) or not raw_tags:
            raise HTTPException(400, "`tags` must be a non-empty list for tag actions.")
        for t in raw_tags:
            if not isinstance(t, str):
                raise HTTPException(400, "`tags` entries must be strings.")
            norm = t.strip().lower()[:32]
            if norm and norm not in tags_in:
                tags_in.append(norm)
        if not tags_in:
            raise HTTPException(400, "`tags` had no usable entries after normalizing.")
        if len(tags_in) > MAX_TAGS_PER_RECORD:
            raise HTTPException(
                400,
                f"Too many tags in one request (max {MAX_TAGS_PER_RECORD}).",
            )

    tenant_id = getattr(request.state, "tenant_id", None)
    repo = Repository()
    affected = 0
    missing: list[str] = []
    if not dry_run and action == "delete":
        from shotclassify_store.legal_holds import tenant_has_active_hold

        if tenant_has_active_hold(tenant_id or ""):
            raise HTTPException(
                status_code=423,
                detail={
                    "error": "legal_hold_active",
                    "message": (
                        "Workspace is under legal hold; bulk deletes are "
                        "blocked until every active hold is lifted."
                    ),
                },
            )
    for rid in ids:
        if action == "delete":
            if dry_run:
                if repo.get(rid, tenant_id=tenant_id) is not None:
                    affected += 1
                else:
                    missing.append(rid)
                continue
            if repo.delete(rid, tenant_id=tenant_id):
                affected += 1
            else:
                missing.append(rid)
            continue
        rec = repo.get(rid, tenant_id=tenant_id)
        if not rec:
            missing.append(rid)
            continue
        if action in {"pin", "unpin"}:
            want = action == "pin"
            if bool(rec.pinned) == want:
                continue
            if dry_run:
                affected += 1
                continue
            updated = repo.update_meta(rid, pinned=want, tenant_id=tenant_id)
            if updated:
                affected += 1
            else:
                missing.append(rid)
            continue
        current = list(rec.tags or [])
        if action == "tag_add":
            new_tags = list(current)
            for t in tags_in:
                if t not in new_tags:
                    new_tags.append(t)
        else:
            remove_set = set(tags_in)
            new_tags = [t for t in current if t not in remove_set]
        if new_tags == current:
            continue
        if dry_run:
            affected += 1
            continue
        updated = repo.update_meta(rid, tags=new_tags, tenant_id=tenant_id)
        if updated:
            affected += 1
        else:
            missing.append(rid)
    if dry_run:
        request.state.dry_run = True
        request.state.audit_extra = {
            **(getattr(request.state, "audit_extra", None) or {}),
            "dry_run": True,
            "bulk_action": action,
        }
        return {
            "ok": True,
            "dry_run": True,
            "applied": False,
            "action": action,
            "requested": len(ids),
            "would_affect": affected,
            "missing": missing,
            "tags": tags_in if action != "delete" else [],
        }
    return {
        "ok": True,
        "action": action,
        "requested": len(ids),
        "affected": affected,
        "missing": missing,
        "tags": tags_in if action != "delete" else [],
    }


@router.delete("/{item_id}", dependencies=[require_role("operator"), require_scope("write:classifications")])
def delete(item_id: str, request: Request, dry_run: bool = dry_run_query()):
    tenant_id = getattr(request.state, "tenant_id", None)
    repo = Repository()
    if dry_run:
        rec = repo.get(item_id, tenant_id=tenant_id)
        if rec is None:
            return mark_dry_run(request, would_delete=None)
        return mark_dry_run(
            request,
            would_delete={"id": item_id, "filename": getattr(rec, "filename", None)},
        )
    try:
        ok = repo.delete(item_id, tenant_id=tenant_id)
    except LegalHoldActive as exc:
        raise HTTPException(
            status_code=423,
            detail={
                "error": "legal_hold_active",
                "message": (
                    "Workspace is under legal hold; this shot cannot be "
                    "deleted until every active hold is lifted."
                ),
                "matters": exc.matters,
            },
        )
    if not ok:
        raise HTTPException(404, "Not found.")
    return {"ok": True}


@router.patch(
    "/{item_id}",
    response_model=ClassificationRecord,
    dependencies=[require_role("operator"), require_scope("write:classifications")],
)
def patch(
    item_id: str,
    request: Request,
    payload: dict = Body(
        ...,
        examples=[{"label": "Q3 receipts", "tags": ["finance", "reviewed"]}],
    ),
) -> ClassificationRecord:
    """Rename a saved shot and/or replace its tag list.

    Body fields (all optional):
      * ``label`` (string|null): rename. ``null`` clears.
      * ``tags`` (list[string]): replaces the full tag list. Empty list clears.
    """
    if not isinstance(payload, dict):
        raise HTTPException(400, "Body must be a JSON object.")
    allowed = {"label", "tags", "pinned"}
    unknown = set(payload) - allowed
    if unknown:
        raise HTTPException(400, f"Unknown field(s): {sorted(unknown)}")
    label_in = payload.get("label", ...)
    tags_in = payload.get("tags", None)
    pinned_in = payload.get("pinned", None)
    if pinned_in is not None and not isinstance(pinned_in, bool):
        raise HTTPException(400, "`pinned` must be a boolean.")
    clear_label = False
    label_val: str | None = None
    if label_in is not ...:
        if label_in is None:
            clear_label = True
        elif isinstance(label_in, str):
            label_val = label_in
        else:
            raise HTTPException(400, "`label` must be a string or null.")
    if tags_in is not None:
        if not isinstance(tags_in, list) or not all(isinstance(t, str) for t in tags_in):
            raise HTTPException(400, "`tags` must be a list of strings.")
        if len(tags_in) > MAX_TAGS_PER_RECORD:
            raise HTTPException(
                400, f"Too many tags (max {MAX_TAGS_PER_RECORD})."
            )
    tenant_id = getattr(request.state, "tenant_id", None)
    rec = Repository().update_meta(
        item_id,
        label=label_val,
        tags=tags_in,
        tenant_id=tenant_id,
        clear_label=clear_label,
        pinned=pinned_in,
    )
    if not rec:
        raise HTTPException(404, "Not found.")
    return rec
