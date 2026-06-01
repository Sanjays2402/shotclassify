"""Classification endpoints."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from shotclassify_common import Category, ProcessResult, get_settings
from shotclassify_common.pipeline import process_image
from shotclassify_common.utils import ensure_dir, new_id
from shotclassify_store import (
    Repository,
    get_allowed_content_types,
    get_upload_size_policy,
    webhooks_store,
)

from ..middleware.rbac import require_role, require_scope
from .usage import enforce_quota

router = APIRouter(
    prefix="/v1",
    tags=["classify"],
    dependencies=[require_role("operator"), require_scope("write:classifications")],
)


def _dispatch_classify_event(
    result: ProcessResult,
    *,
    tenant_id: str | None,
    principal: str | None,
    request_id: str | None,
) -> None:
    """Background-task entry point: ship the classify.completed event.

    No-ops cleanly when there is no tenant context or no matching active
    subscription, so unauthenticated dev runs and legacy single-tenant
    deployments pay zero cost. Each delivery records its own row in
    ``webhook_deliveries``; failures are swallowed here because the
    request handler has already returned a success to the caller.
    """
    if not tenant_id:
        return
    try:
        webhooks_store.dispatch_event(
            tenant_id=tenant_id,
            event="classify.completed",
            payload={
                "event": "classify.completed",
                "tenant_id": tenant_id,
                "principal": principal,
                "id": result.id,
                "filename": result.filename,
                "created_at": result.created_at.isoformat(),
                "primary_category": result.classification.primary.value,
                "confidence": result.classification.confidence_of(
                    result.classification.primary
                ),
                "elapsed_ms": result.elapsed_ms,
            },
            request_id=request_id,
        )
    except Exception:  # noqa: BLE001
        # Webhook delivery must never leak back to the request path.
        pass


def _enforce_content_type(upload: UploadFile, tenant_id: str | None) -> None:
    """Reject an upload whose Content-Type is not permitted.

    Per-tenant allow-list takes precedence: if the workspace has
    registered an explicit list (DLP control) the upload must match
    exactly. Otherwise the legacy gate (any ``image/*``) is applied so
    existing single-tenant deployments keep working unchanged.
    Rejected with HTTP 415 *before* the bytes are buffered or routed
    to the model so a hostile or buggy client cannot spend tenant
    resources on a payload that will be discarded.
    """
    policy = get_allowed_content_types(tenant_id)
    if policy.accepts(upload.content_type):
        return
    raise HTTPException(
        415,
        {
            "error": "content_type_not_allowed",
            "content_type": upload.content_type,
            "filename": upload.filename,
            "allowed": list(policy.types) if policy.enforced else None,
            "policy_enforced": policy.enforced,
        },
    )


def _resolve_upload_cap(tenant_id: str | None) -> int | None:
    """Return the byte cap that applies to a single upload for this tenant.

    Per-tenant policy takes precedence. When no per-tenant policy is set
    we return ``None`` so existing deployments keep their legacy
    behaviour (gated only by the reverse proxy / global body size).
    """
    if not tenant_id:
        return None
    pol = get_upload_size_policy(tenant_id)
    return pol.max_upload_bytes


def _enforce_upload_cap(upload: UploadFile, cap: int | None) -> None:
    """Reject an upload that already announces a size beyond ``cap``.

    Multipart uploads carry a ``Content-Length`` / ``size`` hint long
    before the bytes are buffered to disk. Catching the violation here
    keeps a hostile or buggy client from spending tenant disk and
    pipeline time on a payload that will be discarded anyway. The
    streaming reader in ``_save_upload`` re-checks the actual buffered
    length so a missing or lying header cannot bypass the cap.
    """
    if cap is None:
        return
    declared = getattr(upload, "size", None)
    if isinstance(declared, int) and declared > cap:
        raise HTTPException(
            413,
            {
                "error": "upload_too_large",
                "max_upload_bytes": cap,
                "declared_bytes": declared,
                "filename": upload.filename,
            },
        )


def _save_upload(upload: UploadFile, cap: int | None = None) -> tuple[str, str]:
    s = get_settings()
    rid = new_id()
    upload_dir = ensure_dir(Path(s.storage_local_dir) / "uploads")
    suffix = Path(upload.filename or "image.png").suffix or ".png"
    dest = upload_dir / f"{rid}{suffix}"
    chunk_size = 1024 * 1024
    written = 0
    with dest.open("wb") as f:
        while True:
            chunk = upload.file.read(chunk_size)
            if not chunk:
                break
            written += len(chunk)
            if cap is not None and written > cap:
                # Stop, drop the partial file, and tell the caller why
                # before the model ever sees the payload.
                f.close()
                try:
                    dest.unlink()
                except OSError:
                    pass
                raise HTTPException(
                    413,
                    {
                        "error": "upload_too_large",
                        "max_upload_bytes": cap,
                        "buffered_bytes": written,
                        "filename": upload.filename,
                    },
                )
            f.write(chunk)
    return rid, str(dest)


@router.post("/classify", response_model=ProcessResult)
async def classify(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    note: str | None = Form(None),
) -> ProcessResult:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(415, "Upload must be an image.")
    principal = getattr(request.state, "principal", None)
    tenant_id = getattr(request.state, "tenant_id", None)
    request_id = getattr(request.state, "request_id", None)
    _enforce_content_type(file, tenant_id)
    enforce_quota(principal, tenant_id=tenant_id)
    cap = _resolve_upload_cap(tenant_id)
    _enforce_upload_cap(file, cap)
    rid, path = _save_upload(file, cap)
    result = await asyncio.to_thread(
        process_image, path, note, True, rid, principal, tenant_id
    )
    background.add_task(
        _dispatch_classify_event,
        result,
        tenant_id=tenant_id,
        principal=principal,
        request_id=request_id,
    )
    return result


@router.post("/classify/batch", response_model=list[ProcessResult])
async def classify_batch(
    request: Request,
    background: BackgroundTasks,
    files: list[UploadFile] = File(...),
    note: str | None = Form(None),
) -> list[ProcessResult]:
    if not files:
        raise HTTPException(400, "No files.")
    principal = getattr(request.state, "principal", None)
    tenant_id = getattr(request.state, "tenant_id", None)
    request_id = getattr(request.state, "request_id", None)
    for f in files:
        _enforce_content_type(f, tenant_id)
    enforce_quota(principal, tenant_id=tenant_id)
    cap = _resolve_upload_cap(tenant_id)
    for f in files:
        _enforce_upload_cap(f, cap)
    saved = [_save_upload(f, cap) for f in files]
    tasks = [
        asyncio.to_thread(process_image, p, note, True, rid, principal, tenant_id)
        for rid, p in saved
    ]
    results = await asyncio.gather(*tasks)
    for result in results:
        background.add_task(
            _dispatch_classify_event,
            result,
            tenant_id=tenant_id,
            principal=principal,
            request_id=request_id,
        )
    return results


@router.post("/classify/{item_id}/reclassify", response_model=ProcessResult)
async def reclassify(
    item_id: str,
    request: Request,
    background: BackgroundTasks,
    note: str | None = Form(None),
) -> ProcessResult:
    repo = Repository()
    tenant_id = getattr(request.state, "tenant_id", None)
    record = repo.get(item_id, tenant_id=tenant_id)
    if not record or not record.image_path or not Path(record.image_path).exists():
        raise HTTPException(404, "Original image not available for reclassification.")
    principal = getattr(request.state, "principal", None)
    request_id = getattr(request.state, "request_id", None)
    result = await asyncio.to_thread(
        process_image, record.image_path, note, True, item_id, principal, tenant_id
    )
    background.add_task(
        _dispatch_classify_event,
        result,
        tenant_id=tenant_id,
        principal=principal,
        request_id=request_id,
    )
    return result


@router.post("/classify/{item_id}/correct")
async def correct(item_id: str, request: Request, category: str = Form(...)):
    repo = Repository()
    try:
        cat = Category(category)
    except ValueError as e:
        raise HTTPException(422, f"Invalid category: {e}")
    tenant_id = getattr(request.state, "tenant_id", None)
    record = repo.correct(item_id, cat, tenant_id=tenant_id)
    if not record:
        raise HTTPException(404, "Not found.")
    return {"ok": True, "id": item_id, "user_corrected_to": cat.value}


@router.post("/queue", response_model=dict)
async def enqueue(request: Request, file: UploadFile = File(...), background: BackgroundTasks = None):
    """Enqueue via Redis RQ if available; otherwise run inline as background task."""
    tenant_id = getattr(request.state, "tenant_id", None)
    _enforce_content_type(file, tenant_id)
    cap = _resolve_upload_cap(tenant_id)
    _enforce_upload_cap(file, cap)
    rid, path = _save_upload(file, cap)
    try:
        from redis import Redis  # type: ignore
        from rq import Queue  # type: ignore

        s = get_settings()
        q = Queue(s.queue_name, connection=Redis.from_url(s.redis_url))
        job = q.enqueue("services.worker.app.jobs.process_image_job", path, None, rid)
        return {"id": rid, "job_id": job.id, "queued": True}
    except Exception:
        if background is not None:
            background.add_task(process_image, path, None, True, rid)
        return {"id": rid, "queued": False, "inline": True}
