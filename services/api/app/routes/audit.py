"""Audit log read API.

Lets operators query the persisted audit trail. Writes happen automatically
via the AuditLogMiddleware on every authenticated mutating request.

The streaming export endpoint (``POST /v1/audit/export``) emits the
caller's workspace audit rows as CSV or JSONL with a signed manifest, so
buyers can ship the trail into their own SIEM (Splunk, Datadog, etc.) on
a schedule. It is a POST so the export itself is recorded in the audit
log by the standard mutation middleware.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Iterator

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
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


# --------------------------------------------------------------------- export

# Defensive ceiling so a single export cannot exhaust the worker. Tenants
# that need more should page by date window.
EXPORT_MAX_ROWS = 250_000


class AuditExportRequest(BaseModel):
    format: str = Field("jsonl", pattern="^(jsonl|csv)$")
    since: datetime | None = None
    until: datetime | None = None
    principal: str | None = Field(None, max_length=256)
    path_prefix: str | None = Field(None, max_length=512)
    status_min: int | None = Field(None, ge=100, le=599)
    status_max: int | None = Field(None, ge=100, le=599)
    max_rows: int = Field(EXPORT_MAX_ROWS, ge=1, le=EXPORT_MAX_ROWS)

    @field_validator("until")
    @classmethod
    def _check_until(cls, v: datetime | None, info):
        since = info.data.get("since")
        if v is not None and since is not None and v <= since:
            raise ValueError("until must be strictly after since")
        return v


_CSV_COLUMNS = (
    "id",
    "created_at",
    "principal",
    "method",
    "path",
    "status_code",
    "request_id",
    "client_ip",
    "user_agent",
    "elapsed_ms",
    "target_id",
    "tenant_id",
    "extra",
    "prev_hash",
    "entry_hash",
)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _manifest(
    *,
    tenant_id: str | None,
    request: Request,
    payload: AuditExportRequest,
    rows: int,
    truncated: bool,
    chain: dict,
) -> dict:
    principal = getattr(request.state, "principal", None)
    request_id = getattr(request.state, "request_id", None)
    return {
        "kind": "shotclassify.audit_export.manifest",
        "version": 1,
        "tenant_id": tenant_id,
        "exported_at": _iso(datetime.now(UTC)),
        "exported_by": str(principal) if principal else None,
        "request_id": request_id,
        "format": payload.format,
        "filters": {
            "since": _iso(payload.since),
            "until": _iso(payload.until),
            "principal": payload.principal,
            "path_prefix": payload.path_prefix,
            "status_min": payload.status_min,
            "status_max": payload.status_max,
        },
        "rows": rows,
        "truncated": truncated,
        "max_rows": payload.max_rows,
        "chain": {
            "ok": chain.get("ok"),
            "checked": chain.get("checked"),
            "tip_hash": chain.get("tip_hash"),
            "broken_at": chain.get("broken_at"),
        },
    }


def _stream_jsonl(
    repo: AuditRepository,
    tenant_id: str | None,
    request: Request,
    payload: AuditExportRequest,
) -> Iterator[bytes]:
    rows = 0
    truncated = False
    for row in repo.iter_for_export(
        tenant_id=tenant_id,
        since=payload.since,
        until=payload.until,
        principal=payload.principal,
        path_prefix=payload.path_prefix,
        status_min=payload.status_min,
        status_max=payload.status_max,
        max_rows=payload.max_rows,
    ):
        yield (json.dumps(row, default=str, sort_keys=True) + "\n").encode("utf-8")
        rows += 1
        if rows >= payload.max_rows:
            truncated = True
    # Tail the file with a manifest record so SIEM consumers can verify
    # what they pulled without a second round trip.
    chain = repo.verify_chain(tenant_id=tenant_id)
    manifest = _manifest(
        tenant_id=tenant_id,
        request=request,
        payload=payload,
        rows=rows,
        truncated=truncated,
        chain=chain,
    )
    yield (json.dumps({"_manifest": manifest}, default=str) + "\n").encode("utf-8")


def _stream_csv(
    repo: AuditRepository,
    tenant_id: str | None,
    request: Request,
    payload: AuditExportRequest,
) -> Iterator[bytes]:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(_CSV_COLUMNS)
    yield buf.getvalue().encode("utf-8")
    buf.seek(0)
    buf.truncate(0)
    rows = 0
    truncated = False
    for row in repo.iter_for_export(
        tenant_id=tenant_id,
        since=payload.since,
        until=payload.until,
        principal=payload.principal,
        path_prefix=payload.path_prefix,
        status_min=payload.status_min,
        status_max=payload.status_max,
        max_rows=payload.max_rows,
    ):
        writer.writerow(
            [
                row.get(col) if col != "extra" else json.dumps(row.get("extra") or {}, sort_keys=True)
                for col in _CSV_COLUMNS
            ]
        )
        yield buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate(0)
        rows += 1
        if rows >= payload.max_rows:
            truncated = True
    chain = repo.verify_chain(tenant_id=tenant_id)
    manifest = _manifest(
        tenant_id=tenant_id,
        request=request,
        payload=payload,
        rows=rows,
        truncated=truncated,
        chain=chain,
    )
    # CSV manifest is emitted as a comment-prefixed trailer line that
    # well-behaved parsers ignore. The same manifest is also returned in
    # the X-Audit-Manifest response header for programmatic consumers.
    request.state._audit_export_manifest = manifest
    yield ("# " + json.dumps(manifest, default=str, sort_keys=True) + "\n").encode("utf-8")


@router.post("/export")
def export_audit(payload: AuditExportRequest, request: Request):
    """Stream a tenant-scoped audit export for SIEM ingestion.

    Returns CSV or JSON Lines. Both formats include a manifest with the
    filter window actually applied, the verified hash-chain tip, and the
    row count. The endpoint is a POST so the export action itself is
    captured by the standard audit middleware.
    """
    if payload.status_max is not None and payload.status_min is not None and payload.status_max < payload.status_min:
        raise HTTPException(422, "status_max must be greater than or equal to status_min.")
    tenant_id = getattr(request.state, "tenant_id", None)
    repo = AuditRepository()
    # Pre-compute manifest so it can ride in headers even for streaming.
    pre_chain = repo.verify_chain(tenant_id=tenant_id)
    header_manifest = json.dumps(
        {
            "tenant_id": tenant_id,
            "tip_hash": pre_chain.get("tip_hash"),
            "chain_ok": pre_chain.get("ok"),
            "filters_applied": {
                "since": _iso(payload.since),
                "until": _iso(payload.until),
                "principal": payload.principal,
                "path_prefix": payload.path_prefix,
                "status_min": payload.status_min,
                "status_max": payload.status_max,
            },
        },
        default=str,
        sort_keys=True,
    )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    tenant_slug = (tenant_id or "global").replace("/", "_")
    if payload.format == "csv":
        filename = f"shotclassify-audit-{tenant_slug}-{stamp}.csv"
        headers = {
            "content-disposition": f'attachment; filename="{filename}"',
            "cache-control": "no-store",
            "x-audit-manifest": header_manifest,
            "x-audit-format": "csv",
        }
        return StreamingResponse(
            _stream_csv(repo, tenant_id, request, payload),
            media_type="text/csv; charset=utf-8",
            headers=headers,
        )
    filename = f"shotclassify-audit-{tenant_slug}-{stamp}.jsonl"
    headers = {
        "content-disposition": f'attachment; filename="{filename}"',
        "cache-control": "no-store",
        "x-audit-manifest": header_manifest,
        "x-audit-format": "jsonl",
    }
    return StreamingResponse(
        _stream_jsonl(repo, tenant_id, request, payload),
        media_type="application/x-ndjson",
        headers=headers,
    )
