"""Active sessions: list, revoke, force-logout.

End users see their own sessions. Admins (with ``require_role('admin')``)
can list every session in the system and force-logout any principal.
This is the API surface the admin console uses to satisfy "show me every
device that is logged in, and let me kill them" -- a hard requirement in
SOC2 CC6.1 and in essentially every enterprise security questionnaire.

Every mutation hits the audit middleware (it runs against ``/v1/...``
routes) so revocations show up in the audit trail with actor, target,
IP, and timestamp.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from shotclassify_store import session_store

from ..middleware.rbac import require_role

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


def _principal(request: Request) -> str:
    p = getattr(request.state, "principal", None)
    if not p:
        raise HTTPException(401, "Not authenticated.")
    return p


def _session_to_payload(info, current_sid: str | None) -> dict:
    d = info.to_dict()
    d["current"] = current_sid is not None and info.id == current_sid
    return d


@router.get("")
def list_mine(
    request: Request,
    include_revoked: bool = Query(False, description="Include revoked sessions."),
):
    """List the calling principal's sessions.

    API-key callers do not have a session and get an empty list; sessions
    only exist for cookie-authenticated principals.
    """
    principal = _principal(request)
    if principal == "api-key":
        return {"sessions": [], "current": None}
    current_sid = getattr(request.state, "session_id", None)
    rows = session_store.list_for_principal(principal, include_revoked=include_revoked)
    return {
        "sessions": [_session_to_payload(r, current_sid) for r in rows],
        "current": current_sid,
    }


@router.delete("/{session_id}")
def revoke_one(session_id: str, request: Request):
    """Revoke a single session.

    Owners can revoke their own sessions; admins can revoke any session.
    Returns 404 (not 403) for an unknown id so an attacker cannot probe
    which session ids belong to other principals.
    """
    principal = _principal(request)
    info = session_store.get(session_id)
    if info is None:
        raise HTTPException(404, "Session not found.")
    role = getattr(request.state, "role", None)
    if info.principal != principal and role != "admin":
        # Mask existence to prevent cross-principal session id enumeration.
        raise HTTPException(404, "Session not found.")
    revoked = session_store.revoke(session_id)
    return {"revoked": revoked, "id": session_id}


@router.post("/revoke-all")
def revoke_all(
    request: Request,
    keep_current: bool = Query(
        True,
        description="Keep the calling session active so the user is not logged out of this tab.",
    ),
):
    """Force-logout every session for the calling principal.

    With ``keep_current=false`` the caller is logged out too, which is
    the right semantics for "I think my account was compromised".
    """
    principal = _principal(request)
    current_sid = getattr(request.state, "session_id", None) if keep_current else None
    count = session_store.revoke_all_for_principal(principal, except_sid=current_sid)
    return {"revoked": count}


@router.get("/admin")
def list_all(
    request: Request,
    tenant_id: str | None = Query(None, description="Limit to one tenant."),
    _: str = require_role("admin"),
):
    """Admin view of every active session, optionally scoped to one tenant."""
    rows = session_store.list_all(tenant_id=tenant_id)
    current_sid = getattr(request.state, "session_id", None)
    return {
        "sessions": [_session_to_payload(r, current_sid) for r in rows],
        "current": current_sid,
    }


@router.post("/admin/revoke-principal")
def admin_revoke_principal(
    request: Request,
    principal: str = Query(..., description="Principal whose sessions should be revoked."),
    _: str = require_role("admin"),
):
    """Admin force-logout: revoke every session belonging to ``principal``."""
    if not principal.strip():
        raise HTTPException(422, "principal is required.")
    count = session_store.revoke_all_for_principal(principal)
    return {"revoked": count, "principal": principal}
