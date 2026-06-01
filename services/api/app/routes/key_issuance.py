"""Dual-control API key issuance approval queue.

Tenant admins use this surface to list pending issuance requests created
by their peers and to approve or deny them. The route layer enforces the
core rule: an approval *must* come from a different principal than the
one who created the request. When approved, the route mints the API key
on behalf of the requester and returns the plaintext token exactly once
to the approver, who is responsible for handing it back through their
internal credential-distribution channel.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field
from shotclassify_store import (
    api_keys_store,
    dual_control_store,
)
from shotclassify_store.dual_control import DualControlError

from ..middleware.mfa import require_mfa_step_up
from ..middleware.rbac import require_role


router = APIRouter(prefix="/v1/key-issuance-requests", tags=["api-keys"])


def _tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=422,
            detail="A tenant context is required. Pass X-Tenant or sign in to a workspace.",
        )
    return tenant_id


class DecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


@router.get("", dependencies=[require_role("admin")])
def list_requests(
    request: Request,
    include_recent: bool = Query(False, description="Include decided/expired rows."),
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    tenant_id = _tenant(request)
    if include_recent:
        rows = dual_control_store.list_recent(tenant_id, limit=limit)
    else:
        rows = dual_control_store.list_pending(tenant_id)
    return {
        "tenant_id": tenant_id,
        "policy_enabled": dual_control_store.get_policy(tenant_id),
        "protected_scopes": sorted(dual_control_store.PROTECTED_SCOPES),
        "requests": [r.to_dict() for r in rows],
    }


@router.get("/{request_id}", dependencies=[require_role("admin")])
def get_one(request_id: str, request: Request) -> dict:
    tenant_id = _tenant(request)
    req = dual_control_store.get_request(request_id, tenant_id=tenant_id)
    if req is None:
        raise HTTPException(404, "Request not found.")
    return req.to_dict()


@router.post(
    "/{request_id}/approve",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def approve(
    request_id: str,
    request: Request,
    payload: DecisionRequest = Body(default=DecisionRequest()),
) -> dict:
    """Approve a pending request and mint the key in one transaction.

    The plaintext token is returned to the approver exactly once. The
    approver is responsible for delivering it back to the original
    requester through their organization's credential channel.
    """
    tenant_id = _tenant(request)
    approver = getattr(request.state, "principal", None)
    if not approver:
        raise HTTPException(401, "Authenticated principal required to approve.")
    try:
        decided = dual_control_store.approve(
            request_id,
            tenant_id=tenant_id,
            approver=approver,
            note=payload.note,
        )
    except DualControlError as exc:
        # 409 conflict captures "self-approval", "already decided",
        # "expired". The message is safe to surface; it does not leak
        # cross-tenant state because the lookup was already tenant-scoped.
        raise HTTPException(409, str(exc)) from exc
    try:
        record, token = api_keys_store.create_key(
            label=decided.label,
            tenant_id=tenant_id,
            scopes=list(decided.scopes),
            # The audit trail says approver minted, requester asked.
            created_by=approver,
            ttl_days=decided.ttl_days,
            owner_email=decided.owner_email,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    dual_control_store.mark_minted(request_id, tenant_id=tenant_id, key_id=record.id)
    request.state.audit_target_id = record.id
    body = record.to_dict()
    body["token"] = token
    body["token_display_once"] = True
    body["issuance_request_id"] = request_id
    body["requested_by"] = decided.requested_by
    return body


@router.post(
    "/{request_id}/deny",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def deny(
    request_id: str,
    request: Request,
    payload: DecisionRequest = Body(default=DecisionRequest()),
) -> dict:
    tenant_id = _tenant(request)
    decider = getattr(request.state, "principal", None)
    if not decider:
        raise HTTPException(401, "Authenticated principal required to deny.")
    try:
        decided = dual_control_store.deny(
            request_id,
            tenant_id=tenant_id,
            decider=decider,
            note=payload.note,
        )
    except DualControlError as exc:
        raise HTTPException(409, str(exc)) from exc
    request.state.audit_target_id = decided.id
    return decided.to_dict()
