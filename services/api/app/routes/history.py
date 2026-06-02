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


def _normalize_tags_filter(tags: list[str] | None) -> list[str] | None:
    """Normalize a repeatable ``tags`` query filter.

    Trims, lowercases, drops empties and duplicates, and validates each tag
    against the same 32-char cap used on the single ``tag`` filter. Returns
    ``None`` when no usable tags remain so the repo layer can skip the join.
    """
    if not tags:
        return None
    out: list[str] = []
    for t in tags:
        if not isinstance(t, str):
            continue
        norm = t.strip().lower()
        if not norm:
            continue
        if len(norm) > 32:
            raise HTTPException(
                status_code=400,
                detail=f"tag '{t}' exceeds 32 characters.",
            )
        if norm not in out:
            out.append(norm)
    return out or None


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


def _build_link_header(
    request: Request, *, offset: int, limit: int, total: int
) -> str:
    """Build an RFC 5988 ``Link`` header for cursor-free pagination.

    Emits ``first``, ``prev``, ``next``, and ``last`` relations as applicable
    so a script can walk pages without recomputing offsets. Preserves every
    query param the caller sent (filters, sort, etc.) and only rewrites
    ``offset`` and ``limit``.
    """
    if limit <= 0:
        return ""
    # Last page offset is the largest multiple of ``limit`` strictly less
    # than ``total``. When ``total`` is 0 there is no last page.
    last_offset = ((total - 1) // limit) * limit if total > 0 else 0
    # Cap pagination targets at the same upper bound enforced on the query
    # parameter so a generated link is never rejected by FastAPI validation.
    OFFSET_MAX = 100_000
    last_offset = min(last_offset, OFFSET_MAX)

    base_qs = [
        (k, v) for k, v in request.query_params.multi_items()
        if k not in ("offset", "limit")
    ]

    def _url_for(new_offset: int) -> str:
        from urllib.parse import urlencode

        params = base_qs + [("limit", str(limit)), ("offset", str(new_offset))]
        qs = urlencode(params, doseq=True)
        return f"{request.url.path}?{qs}"

    parts: list[str] = []
    parts.append(f'<{_url_for(0)}>; rel="first"')
    if offset > 0:
        prev_offset = max(0, offset - limit)
        parts.append(f'<{_url_for(prev_offset)}>; rel="prev"')
    next_offset = offset + limit
    if next_offset < total and next_offset <= OFFSET_MAX:
        parts.append(f'<{_url_for(next_offset)}>; rel="next"')
    if total > 0:
        parts.append(f'<{_url_for(last_offset)}>; rel="last"')
    return ", ".join(parts)


@router.get("/export", dependencies=[require_role("viewer"), require_scope("read:classifications")])
def export_history(
    request: Request,
    format: str = Query("csv", pattern="^(csv|json|ndjson)$"),
    limit: int = Query(1000, ge=1, le=EXPORT_MAX),
    offset: int = Query(
        0,
        ge=0,
        le=100_000,
        description=(
            "Skip this many matching rows before streaming. Pair with `limit` "
            "to resume a truncated export, e.g. ?limit=5000&offset=5000."
        ),
    ),
    category: Category | None = Query(None),
    q: str | None = Query(None, description="Full-text query over OCR text and filename"),
    since: datetime | None = Query(None, description="Include records at or after this UTC timestamp"),
    until: datetime | None = Query(None, description="Include records at or before this UTC timestamp"),
    min_conf: float | None = Query(None, ge=0.0, le=1.0),
    max_conf: float | None = Query(None, ge=0.0, le=1.0),
    sort: str = Query("new", pattern="^(new|old|conf_asc|conf_desc)$"),
    tag: str | None = Query(None, max_length=32, description="Filter by a single tag (case-insensitive)."),
    tags: list[str] | None = Query(
        None,
        max_length=8,
        description=(
            "Filter by multiple tags (case-insensitive). All supplied tags must "
            "be present on the record (AND match). Repeat the query parameter, "
            "e.g. ?tags=finance&tags=q1. Combines with `tag` if both are given."
        ),
    ),
    pinned: bool | None = Query(None, description="If true, only pinned; if false, only unpinned."),
):
    """Stream classification history as CSV or JSON for download.

    Accepts the same filters as ``GET /v1/history`` so a download from the
    dashboard matches what the user is currently looking at.
    """
    _validate_range_filters(min_conf, max_conf, since, until)
    tags_norm = _normalize_tags_filter(tags)
    tenant_id = getattr(request.state, "tenant_id", None)
    repo = Repository()
    records = repo.list(
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
        tags=tags_norm,
    )
    # Tell the caller how many rows match the filter on the server vs how
    # many fit in this download, so an export capped at ``limit`` does not
    # look like the full dataset. ``x-truncated=true`` is the single bit a
    # script can grep for; ``x-total-matched`` and ``x-record-count`` give
    # the exact numbers.
    total_matched = repo.count_filtered(
        category=category,
        query=q,
        tenant_id=tenant_id,
        since=since,
        until=until,
        min_conf=min_conf,
        max_conf=max_conf,
        tag=tag,
        pinned=pinned,
        tags=tags_norm,
    )
    truncated = (offset + len(records)) < total_matched
    next_offset = offset + len(records) if truncated else None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    common_headers = {
        "x-record-count": str(len(records)),
        "x-total-matched": str(total_matched),
        "x-offset": str(offset),
        "x-truncated": "true" if truncated else "false",
        "access-control-expose-headers": (
            "x-record-count, x-total-matched, x-offset, x-next-offset, x-truncated"
        ),
    }
    if next_offset is not None:
        common_headers["x-next-offset"] = str(next_offset)

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
                **common_headers,
            },
        )

    if format == "json":
        payload = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "count": len(records),
            "total_matched": total_matched,
            "offset": offset,
            "next_offset": next_offset,
            "truncated": truncated,
            "filters": {
                "category": category.value if category else None,
                "q": q,
                "limit": limit,
                "offset": offset,
                "since": since.isoformat() if since else None,
                "until": until.isoformat() if until else None,
                "min_conf": min_conf,
                "max_conf": max_conf,
                "sort": sort,
                "tag": tag,
                "tags": tags_norm,
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
                **common_headers,
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
            'content-disposition': f'attachment; filename="shotclassify-history-{stamp}.csv"',
            **common_headers,
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
    tags: list[str] | None = Query(
        None,
        max_length=8,
        description=(
            "Filter by multiple tags (case-insensitive). All supplied tags must "
            "be present on the record (AND match). Repeat the query parameter, "
            "e.g. ?tags=finance&tags=q1."
        ),
    ),
    pinned: bool | None = Query(None, description="If true, only pinned; if false, only unpinned."),
) -> list[ClassificationRecord]:
    _validate_range_filters(min_conf, max_conf, since, until)
    tags_norm = _normalize_tags_filter(tags)
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
        tags=tags_norm,
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
        tags=tags_norm,
    )
    response.headers["x-total-count"] = str(total)
    response.headers["x-offset"] = str(offset)
    response.headers["x-limit"] = str(limit)
    link_header = _build_link_header(request, offset=offset, limit=limit, total=total)
    if link_header:
        response.headers["link"] = link_header
    response.headers["access-control-expose-headers"] = (
        "x-total-count, x-offset, x-limit, link"
    )
    return items


@router.get("/tags", dependencies=[require_role("viewer"), require_scope("read:classifications")])
def list_tags(
    request: Request,
    q: str | None = Query(
        None,
        max_length=32,
        description=(
            "Optional case-insensitive substring filter on the tag name. "
            "Whitespace is trimmed; empty/whitespace matches everything. "
            "Tags themselves are already lowercased on write."
        ),
    ),
    limit: int = Query(
        100,
        ge=1,
        le=500,
        description="Maximum number of distinct tags returned. Hard-capped at 500.",
    ),
    min_count: int = Query(
        1,
        ge=1,
        le=1_000_000,
        description=(
            "Only return tags used at least this many times. Defaults to 1 "
            "(everything). Set to 2+ to hide one-off tags from tag clouds "
            "and autocomplete."
        ),
    ),
) -> dict:
    """List distinct tags in the current tenant with their usage counts.

    Backs tag autocomplete on the history filter UI and any tag-cloud
    widget. Sorted by count desc then tag asc so the most-used tags
    surface first, with stable alphabetical tie-breaks.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    items = Repository().list_tags(tenant_id=tenant_id, q=q, limit=limit, min_count=min_count)
    return {"items": items, "count": len(items)}


@router.get(
    "/tags/{tag}/related",
    dependencies=[require_role("viewer"), require_scope("read:classifications")],
)
def related_tags(
    tag: str,
    request: Request,
    limit: int = Query(
        50,
        ge=1,
        le=500,
        description="Maximum number of related tags returned. Hard-capped at 500.",
    ),
    min_count: int = Query(
        1,
        ge=1,
        le=1_000_000,
        description=(
            "Only return related tags that co-occur with the seed at least "
            "this many times. Defaults to 1. Set to 2+ to hide one-off pairs."
        ),
    ),
) -> dict:
    """List tags that co-occur with ``tag`` in the current tenant.

    Backs the "related tags" sidebar on the tag detail UI and helps
    surface merge candidates (typos, near-duplicates, abbreviations)
    when cleaning up a tag taxonomy. ``base_count`` reports how many
    rows carry the seed tag overall so the caller can render "X of N"
    without an extra request. Sorted by count desc, then tag asc.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    try:
        return Repository().related_tags(
            tag=tag, tenant_id=tenant_id, limit=limit, min_count=min_count
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

@router.post("/tags/rename", dependencies=[require_role("operator"), require_scope("write:classifications")])
def rename_tag(
    request: Request,
    payload: dict = Body(
        ...,
        examples=[{"from": "finace", "to": "finance"}],
    ),
    dry_run: bool = dry_run_query(),
) -> dict:
    """Rename a tag across every classification in the current tenant.

    Body fields:
      * ``from`` (string, required): existing tag to rename.
      * ``to`` (string, required): replacement tag. Same write-time
        normalization as ``PATCH /v1/history/{id}`` (trim, lowercase,
        32 char cap).

    If a record already has both the old and new tag, the old one is
    dropped so the new one is not duplicated. Returns the count of
    records that changed. Honours ``dry_run=true``.
    """
    if not isinstance(payload, dict):
        raise HTTPException(400, "Body must be a JSON object.")
    allowed = {"from", "to"}
    unknown = set(payload) - allowed
    if unknown:
        raise HTTPException(400, f"Unknown field(s): {sorted(unknown)}")
    old = payload.get("from")
    new = payload.get("to")
    if not isinstance(old, str) or not isinstance(new, str):
        raise HTTPException(400, "`from` and `to` must be strings.")
    tenant_id = getattr(request.state, "tenant_id", None)
    try:
        result = Repository().rename_tag(
            old=old, new=new, tenant_id=tenant_id, dry_run=dry_run
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    if dry_run:
        return mark_dry_run(
            request,
            would_update=result["updated"],
            old=result["old"],
            new=result["new"],
        )
    return result

@router.post("/tags/merge", dependencies=[require_role("operator"), require_scope("write:classifications")])
def merge_tags(
    request: Request,
    payload: dict = Body(
        ...,
        examples=[{"sources": ["finace", "financ", "fin"], "target": "finance"}],
    ),
    dry_run: bool = dry_run_query(),
) -> dict:
    """Merge several source tags into one target tag in a single call.

    Saves N round trips when collapsing a cluster of near-duplicate tags
    (typos, abbreviations, case variants) into a canonical name. Same
    write-time normalization as ``PATCH /v1/history/{id}`` (trim,
    lowercase, 32 char cap). Sources equal to the target, blanks, and
    duplicates are ignored. If a row already has the target alongside one
    or more sources, the sources are dropped and the target is kept once.

    Body fields:
      * ``sources`` (list[string], required): tags to merge away.
      * ``target`` (string, required): canonical tag to keep.

    Returns the count of records that changed. Honours ``dry_run=true``.
    """
    if not isinstance(payload, dict):
        raise HTTPException(400, "Body must be a JSON object.")
    allowed = {"sources", "target"}
    unknown = set(payload) - allowed
    if unknown:
        raise HTTPException(400, f"Unknown field(s): {sorted(unknown)}")
    sources = payload.get("sources")
    target = payload.get("target")
    if not isinstance(sources, list):
        raise HTTPException(400, "`sources` must be a list of strings.")
    if not isinstance(target, str):
        raise HTTPException(400, "`target` must be a string.")
    tenant_id = getattr(request.state, "tenant_id", None)
    try:
        result = Repository().merge_tags(
            sources=sources, target=target, tenant_id=tenant_id, dry_run=dry_run
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    if dry_run:
        return mark_dry_run(
            request,
            would_update=result["updated"],
            sources=result["sources"],
            target=result["target"],
        )
    return result

@router.post("/tags/delete", dependencies=[require_role("operator"), require_scope("write:classifications")])
def delete_tag(
    request: Request,
    payload: dict = Body(
        ...,
        examples=[{"tag": "obsolete"}],
    ),
    dry_run: bool = dry_run_query(),
) -> dict:
    """Remove a tag from every classification in the current tenant.

    Mirror of ``/v1/history/tags/rename`` for retiring an obsolete tag
    entirely instead of merging it into another. Saves an autocomplete
    cleanup pass when a project ends or a tag taxonomy is reshuffled.

    Body fields:
      * ``tag`` (string, required): tag to remove. Normalized the same way
        as on write (trim, lowercase, 32 char cap).

    Returns the count of records that changed. Honours ``dry_run=true``.
    """
    if not isinstance(payload, dict):
        raise HTTPException(400, "Body must be a JSON object.")
    allowed = {"tag"}
    unknown = set(payload) - allowed
    if unknown:
        raise HTTPException(400, f"Unknown field(s): {sorted(unknown)}")
    tag = payload.get("tag")
    if not isinstance(tag, str):
        raise HTTPException(400, "`tag` must be a string.")
    tenant_id = getattr(request.state, "tenant_id", None)
    try:
        result = Repository().delete_tag(
            tag=tag, tenant_id=tenant_id, dry_run=dry_run
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    if dry_run:
        return mark_dry_run(
            request,
            would_update=result["updated"],
            tag=result["tag"],
        )
    return result

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
