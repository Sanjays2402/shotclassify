"""Authenticated, tenant-scoped blob (screenshot) download.

Replaces an earlier ``/blob/<filename>`` static mount that was served by
``StaticFiles`` with no authentication and no tenant scoping. Under that
mount any caller who could guess or scrape a 16-byte hex id could
download another tenant's screenshot, because uploads were written to a
flat directory keyed only on the random id.

The new endpoint requires:

* a real session or API key (the workspace-wide auth middleware runs
  ahead of this handler),
* the ``read:classifications`` scope (matches /v1/history reads),
* and a classification record with ``id`` belonging to the caller's
  ``tenant_id``. We look the record up via
  ``Repository.get(item_id, tenant_id=...)`` which already enforces
  tenant scoping at the query layer, so a caller from tenant B asking
  for tenant A's record gets a 404, not the image bytes.

The file itself is streamed via :class:`fastapi.responses.FileResponse`
with conservative headers: ``Cache-Control: private, no-store`` so
downstream proxies and shared caches never retain another tenant's
screenshot, and ``Content-Disposition: inline`` with the original
filename so the browser renders it in-place.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from shotclassify_common import get_settings
from shotclassify_store import Repository

from ..middleware.rbac import require_role, require_scope

router = APIRouter(
    prefix="/v1/blobs",
    tags=["blobs"],
    dependencies=[require_role("viewer"), require_scope("read:classifications")],
)


_IMAGE_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}


@router.get("/{item_id}")
def get_blob(item_id: str, request: Request) -> FileResponse:
    """Return the screenshot for ``item_id`` if and only if the caller's
    tenant owns the underlying classification record.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        # Without a resolved tenant we cannot enforce isolation, so refuse
        # rather than fall through to the "tenant_id is None matches any"
        # branch in Repository.get.
        raise HTTPException(status_code=404, detail="blob_not_found")
    record = Repository().get(item_id, tenant_id=tenant_id)
    if record is None or not record.image_path:
        # Same status for "not found" and "found but other tenant" so we
        # do not leak the existence of records across tenants.
        raise HTTPException(status_code=404, detail="blob_not_found")

    # Confine the served path to the configured storage root so a row
    # with a tampered ``image_path`` cannot pull files from elsewhere on
    # disk (defence in depth on top of tenant scoping).
    storage_root = Path(get_settings().storage_local_dir).resolve()
    try:
        candidate = Path(record.image_path).resolve()
    except (OSError, RuntimeError):
        raise HTTPException(status_code=404, detail="blob_not_found")
    try:
        candidate.relative_to(storage_root)
    except ValueError:
        raise HTTPException(status_code=404, detail="blob_not_found")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="blob_not_found")

    media_type = _IMAGE_CONTENT_TYPES.get(
        candidate.suffix.lower(), "application/octet-stream"
    )
    safe_filename = record.filename or candidate.name
    # Strip CR/LF defensively for Content-Disposition header safety.
    safe_filename = safe_filename.replace("\r", "").replace("\n", "")
    response = FileResponse(
        path=str(candidate),
        media_type=media_type,
        filename=safe_filename,
        content_disposition_type="inline",
    )
    # Never let a shared cache hold a tenant's screenshot.
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
