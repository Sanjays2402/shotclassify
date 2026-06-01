"""Unified admin console overview endpoint.

Returns a single read-only payload aggregating the workspace-level state
that an owner or admin needs at a glance: member count by role, active
sessions, API key inventory, recent audit log entries, and classification
volume. Every figure is scoped to ``request.state.tenant_id`` so an admin
of tenant A cannot peek at tenant B even if they fabricate an id.

Admin role is required (enforced via :func:`require_role`). Lower roles
receive 403 from the dependency. Non-authenticated callers are rejected
upstream by :class:`APIKeyAndSessionAuth`.

This route reads only. It does not mutate state and therefore does not
require MFA step-up or write audit entries beyond the standard middleware
access log line.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from shotclassify_store import (
    AuditRepository,
    Repository,
    api_keys_store,
    memberships_store,
    session_store,
)

from ..middleware.rbac import require_role

router = APIRouter(prefix="/v1/admin", tags=["admin"])


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=422,
            detail="A tenant context is required for the admin console.",
        )
    return tenant_id


@router.get("/overview", dependencies=[require_role("admin")])
def overview(request: Request) -> dict[str, Any]:
    tenant_id = _require_tenant(request)

    members = memberships_store.list_members(tenant_id)
    role_counts = Counter(m.role for m in members)

    invitations = memberships_store.list_invitations(tenant_id)
    pending_invites = [
        {"id": inv.id, "email": inv.email, "role": inv.role, "created_at": inv.created_at.isoformat()}
        for inv in invitations
        if inv.accepted_at is None and inv.revoked_at is None
    ]

    sessions = session_store.list_all(tenant_id=tenant_id)
    active_sessions = [s for s in sessions if s.revoked_at is None]

    keys = api_keys_store.list_keys(tenant_id=tenant_id, include_revoked=False)
    unowned_keys = api_keys_store.list_unowned(tenant_id=tenant_id)
    key_summaries = [
        {
            "id": k.id,
            "name": k.name,
            "scopes": list(k.scopes),
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "created_at": k.created_at.isoformat(),
        }
        for k in keys
    ]

    audit = AuditRepository()
    recent_audit = audit.list_for_tenant(tenant_id, limit=10)
    audit_preview = [
        {
            "ts": row.get("ts"),
            "principal": row.get("principal"),
            "method": row.get("method"),
            "path": row.get("path"),
            "status": row.get("status"),
        }
        for row in recent_audit
    ]

    repo = Repository()
    classification_count = repo.count(tenant_id=tenant_id)

    seat_limit = memberships_store.get_seat_limit(tenant_id)
    seat_usage = memberships_store.count_seats_in_use(tenant_id)
    seats_available = (
        None if seat_limit is None else max(0, seat_limit - seat_usage["total"])
    )

    return {
        "tenant_id": tenant_id,
        "members": {
            "total": len(members),
            "by_role": dict(role_counts),
            "list": [
                {"principal": m.principal, "role": m.role, "created_at": m.created_at.isoformat()}
                for m in members
            ],
        },
        "invitations": {
            "pending": len(pending_invites),
            "list": pending_invites,
        },
        "sessions": {
            "active": len(active_sessions),
            "total": len(sessions),
        },
        "api_keys": {
            "active": len(keys),
            "unowned": len(unowned_keys),
            "list": key_summaries,
        },
        "audit": {
            "recent": audit_preview,
        },
        "classifications": {
            "total": classification_count,
        },
        "seats": {
            "limit": seat_limit,
            "in_use": seat_usage,
            "available": seats_available,
        },
    }
