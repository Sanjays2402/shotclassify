"""Workspace memberships and email invitations.

Admins of a tenant use this surface to invite teammates, assign roles,
demote, and revoke. Membership rows are the authoritative source of
role assignment once any row exists for a (tenant, principal) pair (see
``APIKeyAndSessionAuth`` for the wiring).

Every endpoint is tenant-scoped: list, invite, revoke, and remove all
filter by ``request.state.tenant_id`` so cross-tenant enumeration is
impossible even with a forged route id. Accept is an exception: the
invite token itself is the proof of authorization and the route binds
the membership to the tenant recorded on the invitation row.

Mutations are audited by the global audit middleware. Role changes also
require MFA step-up so a stolen session cookie cannot silently promote
an attacker to admin.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from shotclassify_store import memberships_store

from ..dryrun import dry_run_query, mark_dry_run
from ..middleware.mfa import require_mfa_step_up
from ..middleware.rbac import require_role

router = APIRouter(prefix="/v1", tags=["memberships"])

Role = Literal["admin", "operator", "viewer"]


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=422,
            detail="A tenant context is required. Pass X-Tenant or sign in to a workspace.",
        )
    return tenant_id


# ---------------------------------------------------------------- members


class UpdateRoleRequest(BaseModel):
    role: Role


@router.get("/members", dependencies=[require_role("admin")])
def list_members(request: Request) -> dict:
    tenant_id = _require_tenant(request)
    members = memberships_store.list_members(tenant_id)
    return {
        "tenant_id": tenant_id,
        "members": [m.to_dict() for m in members],
        "roles": list(memberships_store.VALID_ROLES),
    }


@router.put(
    "/members/{principal}",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def update_member_role(
    principal: str, payload: UpdateRoleRequest, request: Request
) -> dict:
    tenant_id = _require_tenant(request)
    caller = getattr(request.state, "principal", None)
    if payload.role != "admin":
        existing_role = memberships_store.role_for_member(tenant_id, principal)
        if existing_role == "admin":
            remaining = memberships_store.count_admins(
                tenant_id, exclude_principal=principal
            )
            if remaining == 0:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot demote the last admin of this workspace.",
                )
    try:
        record = memberships_store.upsert_member(
            tenant_id=tenant_id,
            principal=principal,
            role=payload.role,
            invited_by=caller,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    request.state.audit_target_id = record.id
    return {"member": record.to_dict()}


@router.delete(
    "/members/{principal}",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def remove_member(principal: str, request: Request, dry_run: bool = dry_run_query()):
    tenant_id = _require_tenant(request)
    caller = getattr(request.state, "principal", None)
    if principal == caller:
        raise HTTPException(
            status_code=409,
            detail="Use the leave-workspace flow to remove yourself.",
        )
    existing_role = memberships_store.role_for_member(tenant_id, principal)
    if existing_role == "admin":
        remaining = memberships_store.count_admins(
            tenant_id, exclude_principal=principal
        )
        if remaining == 0:
            raise HTTPException(
                status_code=409,
                detail="Cannot remove the last admin of this workspace.",
            )
    if dry_run:
        request.state.audit_target_id = principal
        if existing_role is None:
            return mark_dry_run(request, would_remove=None)
        return mark_dry_run(
            request,
            would_remove={"principal": principal, "role": existing_role},
        )
    removed = memberships_store.remove_member(tenant_id, principal)
    if not removed:
        raise HTTPException(404, "Member not found.")
    request.state.audit_target_id = principal
    return {"removed": True, "principal": principal}


# ---------------------------------------------------------------- invitations


class CreateInvitationRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: Role
    ttl_days: int = Field(default=7, ge=1, le=90)


@router.get("/invitations", dependencies=[require_role("admin")])
def list_invitations(
    request: Request,
    include_inactive: bool = Query(False),
) -> dict:
    tenant_id = _require_tenant(request)
    records = memberships_store.list_invitations(
        tenant_id, include_inactive=include_inactive
    )
    return {
        "tenant_id": tenant_id,
        "invitations": [r.to_dict() for r in records],
    }


@router.post(
    "/invitations",
    status_code=201,
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def create_invitation(payload: CreateInvitationRequest, request: Request) -> dict:
    tenant_id = _require_tenant(request)
    caller = getattr(request.state, "principal", None)
    try:
        record, token = memberships_store.create_invitation(
            tenant_id=tenant_id,
            email=payload.email,
            role=payload.role,
            invited_by=caller,
            ttl_days=payload.ttl_days,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    body = record.to_dict()
    body["token"] = token
    body["token_display_once"] = True
    request.state.audit_target_id = record.id
    return body


@router.delete(
    "/invitations/{invitation_id}",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def revoke_invitation(invitation_id: str, request: Request, dry_run: bool = dry_run_query()):
    tenant_id = _require_tenant(request)
    if dry_run:
        records = memberships_store.list_invitations(tenant_id, include_inactive=False)
        match = next((r for r in records if r.id == invitation_id), None)
        if match is None:
            return mark_dry_run(request, would_revoke=None)
        request.state.audit_target_id = match.id
        return mark_dry_run(
            request,
            would_revoke={"id": match.id, "email": getattr(match, "email", None)},
        )
    record = memberships_store.revoke_invitation(invitation_id, tenant_id=tenant_id)
    if record is None:
        raise HTTPException(404, "Invitation not found.")
    request.state.audit_target_id = record.id
    return {"invitation": record.to_dict()}


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=8, max_length=128)


@router.post("/invitations/accept")
def accept_invitation(payload: AcceptInvitationRequest, request: Request) -> dict:
    """Accept an invitation. The signed-in principal becomes a member of the
    tenant recorded on the invitation row. Tokens are single-use; expired or
    revoked tokens return 404 to avoid leaking which workspaces exist."""
    principal = getattr(request.state, "principal", None)
    if not principal:
        raise HTTPException(401, "Sign in before accepting an invitation.")
    result = memberships_store.accept_invitation(payload.token, principal=principal)
    if result is None:
        raise HTTPException(404, "Invitation is invalid, expired, or already used.")
    invitation, membership = result
    request.state.audit_target_id = invitation.id
    return {
        "invitation": invitation.to_dict(),
        "membership": membership.to_dict(),
    }
