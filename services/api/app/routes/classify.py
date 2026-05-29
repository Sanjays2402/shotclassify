"""Classification endpoints."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from shotclassify_common import Category, ProcessResult, get_settings
from shotclassify_common.pipeline import process_image
from shotclassify_common.utils import ensure_dir, new_id
from shotclassify_store import Repository

router = APIRouter(prefix="/v1", tags=["classify"])


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
    file: UploadFile = File(...),
    note: str | None = Form(None),
) -> ProcessResult:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(415, "Upload must be an image.")
    rid, path = _save_upload(file)
    return await asyncio.to_thread(process_image, path, note, True, rid)


@router.post("/classify/batch", response_model=list[ProcessResult])
async def classify_batch(
    files: list[UploadFile] = File(...),
    note: str | None = Form(None),
) -> list[ProcessResult]:
    if not files:
        raise HTTPException(400, "No files.")
    saved = [_save_upload(f) for f in files]
    tasks = [asyncio.to_thread(process_image, p, note, True, rid) for rid, p in saved]
    return await asyncio.gather(*tasks)


@router.post("/classify/{item_id}/reclassify", response_model=ProcessResult)
async def reclassify(item_id: str, note: str | None = Form(None)) -> ProcessResult:
    repo = Repository()
    record = repo.get(item_id)
    if not record or not record.image_path or not Path(record.image_path).exists():
        raise HTTPException(404, "Original image not available for reclassification.")
    return await asyncio.to_thread(process_image, record.image_path, note, True, item_id)


@router.post("/classify/{item_id}/correct")
async def correct(item_id: str, category: str = Form(...)):
    repo = Repository()
    try:
        cat = Category(category)
    except ValueError as e:
        raise HTTPException(422, f"Invalid category: {e}")
    record = repo.correct(item_id, cat)
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
