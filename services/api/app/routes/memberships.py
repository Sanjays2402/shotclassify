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
from shotclassify_store.memberships import SeatLimitExceeded

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
    except SeatLimitExceeded as exc:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "seat_limit_exceeded",
                "message": str(exc),
                "seat_limit": exc.limit,
                "seats_in_use": exc.in_use,
            },
        ) from exc
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
    except SeatLimitExceeded as exc:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "seat_limit_exceeded",
                "message": str(exc),
                "seat_limit": exc.limit,
                "seats_in_use": exc.in_use,
            },
        ) from exc
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


# ---------------------------------------------------------------- seats


class SeatLimitUpdate(BaseModel):
    # ``None`` (or the literal JSON ``null``) means unlimited. Any
    # positive integer becomes the new cap. Lowering the cap below the
    # current usage is allowed and blocks new seats; it never evicts
    # existing members.
    seat_limit: int | None = Field(default=None, ge=1, le=memberships_store.SEAT_LIMIT_MAX)


@router.get("/workspace/seats", dependencies=[require_role("admin")])
def get_seats(request: Request) -> dict:
    """Return seat accounting for the current workspace.

    Response shape:

    ``{"tenant_id": ..., "seat_limit": int|null,
       "seats_in_use": {"members": int, "pending_invitations": int, "total": int},
       "seats_available": int|null}``

    ``seats_available`` is ``null`` when the cap is unlimited.
    """
    tenant_id = _require_tenant(request)
    limit = memberships_store.get_seat_limit(tenant_id)
    in_use = memberships_store.count_seats_in_use(tenant_id)
    available: int | None
    if limit is None:
        available = None
    else:
        available = max(0, limit - in_use["total"])
    return {
        "tenant_id": tenant_id,
        "seat_limit": limit,
        "seats_in_use": in_use,
        "seats_available": available,
    }


@router.put(
    "/workspace/seats",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def set_seats(payload: SeatLimitUpdate, request: Request) -> dict:
    tenant_id = _require_tenant(request)
    caller = getattr(request.state, "principal", None)
    try:
        new_limit = memberships_store.set_seat_limit(
            tenant_id, payload.seat_limit, updated_by=caller
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    in_use = memberships_store.count_seats_in_use(tenant_id)
    request.state.audit_target_id = tenant_id
    return {
        "tenant_id": tenant_id,
        "seat_limit": new_limit,
        "seats_in_use": in_use,
        "seats_available": None if new_limit is None else max(0, new_limit - in_use["total"]),
    }


# ---------------------------------------------------------------- suspension


class SuspendMemberRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=512)


@router.post(
    "/members/{principal}/suspension",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def suspend_member_route(
    principal: str,
    payload: SuspendMemberRequest,
    request: Request,
    dry_run: bool = dry_run_query(),
):
    """Offboard a member without deleting the row.

    The membership row is preserved so the audit log still resolves
    historical actions to a recognized name; the auth middleware
    blocks any new tenant-scoped request from the principal with 403
    ``membership_suspended``. Last-active-admin protection prevents
    locking the workspace out of administration.
    """
    tenant_id = _require_tenant(request)
    caller = getattr(request.state, "principal", None)
    if principal == caller:
        raise HTTPException(
            status_code=409,
            detail="Suspending yourself would lock you out of this workspace.",
        )
    existing_role = memberships_store.role_for_member(tenant_id, principal)
    current_status = memberships_store.membership_status(tenant_id, principal)
    if current_status == "none":
        raise HTTPException(404, "Member not found.")
    if existing_role == "admin" and current_status == "active":
        remaining = memberships_store.count_active_admins(
            tenant_id, exclude_principal=principal
        )
        if remaining == 0:
            raise HTTPException(
                status_code=409,
                detail="Cannot suspend the last active admin of this workspace.",
            )
    if dry_run:
        request.state.audit_target_id = principal
        return mark_dry_run(
            request,
            would_suspend={
                "principal": principal,
                "role": existing_role,
                "reason": payload.reason,
            },
        )
    record = memberships_store.suspend_member(
        tenant_id,
        principal,
        suspended_by=caller,
        reason=payload.reason,
    )
    if record is None:
        raise HTTPException(404, "Member not found.")
    request.state.audit_target_id = record.id
    return {"member": record.to_dict()}


@router.delete(
    "/members/{principal}/suspension",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def reinstate_member_route(
    principal: str, request: Request, dry_run: bool = dry_run_query()
):
    """Reinstate a previously-suspended member.

    Idempotent: calling this on an already-active member is a no-op
    that returns the current record.
    """
    tenant_id = _require_tenant(request)
    current_status = memberships_store.membership_status(tenant_id, principal)
    if current_status == "none":
        raise HTTPException(404, "Member not found.")
    if dry_run:
        request.state.audit_target_id = principal
        return mark_dry_run(
            request,
            would_reinstate={
                "principal": principal,
                "was_suspended": current_status == "suspended",
            },
        )
    record = memberships_store.reinstate_member(tenant_id, principal)
    if record is None:
        raise HTTPException(404, "Member not found.")
    request.state.audit_target_id = record.id
    return {"member": record.to_dict()}
