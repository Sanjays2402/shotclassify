"""GDPR data lifecycle endpoints.

Lets the authenticated principal export everything we hold about them
(``GET /v1/me/data``) and permanently erase it (``DELETE /v1/me/data``).
Scope is the request principal as set by ``APIKeyAndSessionAuth``:
the GitHub login for session users, or the literal string ``api-key`` for
API key callers.

The export bundles:

* identity (principal, request_id)
* every ``classifications`` row tagged with that principal, including the
  full extracted/route JSON blobs and OCR text
* every ``audit_log`` row recorded against that principal

The delete endpoint hard-removes the same rows and unlinks any stored
blobs that live under the configured local storage directory. It is
irreversible; callers must pass ``?confirm=erase`` to proceed.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request
from shotclassify_store import AuditRepository, Repository

router = APIRouter(prefix="/v1/me", tags=["data-lifecycle"])


def _require_principal(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    if not principal:
        # Auth middleware should have blocked this, but guard explicitly so
        # the endpoint never operates without a known subject.
        raise HTTPException(401, "Authenticated principal required.")
    return principal


@router.get("/data")
def export_my_data(request: Request) -> dict:
    principal = _require_principal(request)
    tenant_id = getattr(request.state, "tenant_id", None)
    repo = Repository()
    audit = AuditRepository()
    classifications = [
        r.model_dump(mode="json")
        for r in repo.list_by_principal(principal, tenant_id=tenant_id)
    ]
    audit_rows = audit.list_for_principal(principal, tenant_id=tenant_id)
    return {
        "principal": principal,
        "tenant_id": tenant_id,
        "exported_at": datetime.now(UTC).isoformat(),
        "request_id": getattr(request.state, "request_id", None),
        "counts": {
            "classifications": len(classifications),
            "audit_log": len(audit_rows),
        },
        "classifications": classifications,
        "audit_log": audit_rows,
    }


@router.delete("/data")
def delete_my_data(
    request: Request,
    confirm: str = Query(
        "",
        description="Must equal 'erase' to acknowledge the destructive operation.",
    ),
) -> dict:
    if confirm != "erase":
        raise HTTPException(
            400,
            "Pass ?confirm=erase to permanently delete all stored data for the caller.",
        )
    principal = _require_principal(request)
    tenant_id = getattr(request.state, "tenant_id", None)
    classifications_removed = Repository().delete_by_principal(principal, tenant_id=tenant_id)
    audit_removed = AuditRepository().delete_for_principal(principal, tenant_id=tenant_id)
    return {
        "principal": principal,
        "tenant_id": tenant_id,
        "deleted": {
            "classifications": classifications_removed,
            "audit_log": audit_removed,
        },
    }
