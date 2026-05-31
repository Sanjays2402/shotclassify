"""Classification endpoints."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from shotclassify_common import Category, ProcessResult, get_settings
from shotclassify_common.pipeline import process_image
from shotclassify_common.utils import ensure_dir, new_id
from shotclassify_store import Repository, webhooks_store

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


def _save_upload(upload: UploadFile) -> tuple[str, str]:
    s = get_settings()
    rid = new_id()
    upload_dir = ensure_dir(Path(s.storage_local_dir) / "uploads")
    suffix = Path(upload.filename or "image.png").suffix or ".png"
    dest = upload_dir / f"{rid}{suffix}"
    with dest.open("wb") as f:
        f.write(upload.file.read())
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
    enforce_quota(principal, tenant_id=tenant_id)
    rid, path = _save_upload(file)
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
    enforce_quota(principal, tenant_id=tenant_id)
    saved = [_save_upload(f) for f in files]
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
async def enqueue(file: UploadFile = File(...), background: BackgroundTasks = None):
    """Enqueue via Redis RQ if available; otherwise run inline as background task."""
    rid, path = _save_upload(file)
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
