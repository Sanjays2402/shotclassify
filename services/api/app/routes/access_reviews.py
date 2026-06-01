"""Workspace access-review campaigns (SOC2 CC6.3 / ISO 27001 A.9.2.5).

Admins of a tenant use this surface to open a periodic re-certification of
member access, mark each member ``keep`` or ``revoke``, then apply. Apply
removes the revoked memberships and seals the review so the trail of who
certified what becomes immutable compliance evidence.

Every endpoint is tenant-scoped: list, open, decide, apply, cancel, export
all filter by ``request.state.tenant_id``. The store layer enforces the
same scoping at the query layer so a forged review id from tenant B
returns 404 even if route validation is bypassed. Apply and cancel also
require an MFA step-up because they mutate the member roster.

Mutations are picked up by the global audit middleware. Apply also passes
through the dry-run helper so the admin console can preview revocations
before executing them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from shotclassify_store import access_reviews_store
from shotclassify_store.access_reviews import (
    AccessReviewLastAdminError,
    AccessReviewNotFound,
    AccessReviewStateError,
)

from ..dryrun import dry_run_query, mark_dry_run
from ..middleware.mfa import require_mfa_step_up
from ..middleware.rbac import require_role

router = APIRouter(prefix="/v1/access-reviews", tags=["access-reviews"])

Decision = Literal["pending", "keep", "revoke"]


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=422,
            detail="A tenant context is required. Pass X-Tenant or sign in to a workspace.",
        )
    return tenant_id


def _caller(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    if not principal:
        # The auth middleware should already have rejected this, but fall
        # back to a non-empty actor so the audit row is never blank.
        return "unknown"
    return principal


class OpenReviewRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    due_at: datetime | None = None


class DecisionRequest(BaseModel):
    decision: Decision
    note: str | None = Field(default=None, max_length=512)


# ---------------------------------------------------------------- list / get


@router.get("", dependencies=[require_role("admin")])
def list_reviews(request: Request) -> dict:
    tenant_id = _require_tenant(request)
    reviews = access_reviews_store.list_reviews(tenant_id)
    return {
        "tenant_id": tenant_id,
        "reviews": [r.to_dict() for r in reviews],
        "open_in_progress": any(r.status == "open" for r in reviews),
    }


@router.get("/{review_id}", dependencies=[require_role("admin")])
def get_review(review_id: str, request: Request) -> dict:
    tenant_id = _require_tenant(request)
    review = access_reviews_store.get_review(tenant_id=tenant_id, review_id=review_id)
    if review is None:
        # 404 (not 403) so we do not leak that the id exists in another tenant.
        raise HTTPException(404, "Access review not found.")
    items = access_reviews_store.list_items(tenant_id=tenant_id, review_id=review_id)
    return {"review": review.to_dict(), "items": [i.to_dict() for i in items]}


@router.get("/{review_id}/export.csv", dependencies=[require_role("admin")])
def export_review_csv(review_id: str, request: Request) -> PlainTextResponse:
    tenant_id = _require_tenant(request)
    try:
        body = access_reviews_store.export_csv(tenant_id=tenant_id, review_id=review_id)
    except AccessReviewNotFound:
        raise HTTPException(404, "Access review not found.")
    return PlainTextResponse(
        body,
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="access-review-{review_id}.csv"'
            )
        },
    )


# ---------------------------------------------------------------- mutations


@router.post(
    "",
    dependencies=[require_role("admin"), require_mfa_step_up()],
    status_code=201,
)
def open_review(payload: OpenReviewRequest, request: Request) -> dict:
    tenant_id = _require_tenant(request)
    try:
        review = access_reviews_store.open_review(
            tenant_id=tenant_id,
            title=payload.title,
            created_by=_caller(request),
            due_at=payload.due_at,
        )
    except AccessReviewStateError as exc:
        raise HTTPException(409, str(exc))
    items = access_reviews_store.list_items(
        tenant_id=tenant_id, review_id=review.id
    )
    return {"review": review.to_dict(), "items": [i.to_dict() for i in items]}


@router.put(
    "/{review_id}/items/{item_id}",
    dependencies=[require_role("admin")],
)
def decide(
    review_id: str,
    item_id: str,
    payload: DecisionRequest,
    request: Request,
) -> dict:
    tenant_id = _require_tenant(request)
    try:
        item = access_reviews_store.set_decision(
            tenant_id=tenant_id,
            review_id=review_id,
            item_id=item_id,
            decision=payload.decision,
            decided_by=_caller(request),
            note=payload.note,
        )
    except AccessReviewNotFound:
        raise HTTPException(404, "Access review or item not found.")
    except AccessReviewStateError as exc:
        raise HTTPException(409, str(exc))
    return {"item": item.to_dict()}


@router.post(
    "/{review_id}/cancel",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def cancel(review_id: str, request: Request) -> dict:
    tenant_id = _require_tenant(request)
    try:
        review = access_reviews_store.cancel_review(
            tenant_id=tenant_id, review_id=review_id, actor=_caller(request)
        )
    except AccessReviewNotFound:
        raise HTTPException(404, "Access review not found.")
    except AccessReviewStateError as exc:
        raise HTTPException(409, str(exc))
    return {"review": review.to_dict()}


@router.post(
    "/{review_id}/apply",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def apply(
    review_id: str,
    request: Request,
    dry_run: bool = dry_run_query(),
):
    tenant_id = _require_tenant(request)
    try:
        preview = access_reviews_store.preview_apply(
            tenant_id=tenant_id, review_id=review_id
        )
    except AccessReviewNotFound:
        raise HTTPException(404, "Access review not found.")
    except AccessReviewStateError as exc:
        raise HTTPException(409, str(exc))
    if dry_run:
        return mark_dry_run(
            request,
            review_id=review_id,
            would_revoke=preview["would_revoke"],
            would_keep=preview["would_keep"],
            still_pending=preview["still_pending"],
            blocker=preview["blocker"],
        )
    try:
        review = access_reviews_store.apply_review(
            tenant_id=tenant_id, review_id=review_id, actor=_caller(request)
        )
    except AccessReviewNotFound:
        raise HTTPException(404, "Access review not found.")
    except AccessReviewLastAdminError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "access_review_last_admin",
                "message": str(exc),
                "principal": exc.principal,
            },
        )
    except AccessReviewStateError as exc:
        raise HTTPException(409, str(exc))
    return {
        "review": review.to_dict(),
        "revoked": preview["would_revoke"],
        "kept": preview["would_keep"],
    }
