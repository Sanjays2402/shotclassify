"""Workspace-admin endpoints for the brute-force lockout subsystem.

Two responsibilities:

1. List and clear active per-(tenant, IP) authentication lockouts so an
   admin can unblock a teammate who tripped the policy.
2. Read and update the per-tenant lockout policy (threshold, window,
   cooldown) without a redeploy.

Both surfaces are admin-only and writes additionally require a fresh
TOTP step-up so a stolen session cookie cannot relax the policy or
clear an active lockout silently. Every mutation is captured by the
audit middleware (actor, IP, request id, status) because they all
flow through normal FastAPI routes; no separate hook is needed.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from shotclassify_store import (
    AUTH_LOCKOUT_COOLDOWN_MAX_MINUTES,
    AUTH_LOCKOUT_COOLDOWN_MIN_MINUTES,
    AUTH_LOCKOUT_THRESHOLD_MAX,
    AUTH_LOCKOUT_THRESHOLD_MIN,
    AUTH_LOCKOUT_WINDOW_MAX_MINUTES,
    AUTH_LOCKOUT_WINDOW_MIN_MINUTES,
    auth_lockouts_store,
    get_auth_lockout_policy,
    set_auth_lockout_policy,
)

from ..dryrun import dry_run_query, mark_dry_run
from ..middleware.mfa import require_mfa_step_up
from ..middleware.rbac import require_role

router = APIRouter(prefix="/v1", tags=["security"])


def _tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            400,
            "No tenant resolved. Pass X-Tenant header to target a specific workspace.",
        )
    return tenant_id


@router.get(
    "/settings/security/auth-lockout",
    dependencies=[require_role("admin")],
)
def get_lockout_policy_route(request: Request) -> dict:
    """Return the current brute-force lockout policy for the caller's tenant."""
    tenant_id = _tenant(request)
    return get_auth_lockout_policy(tenant_id).as_dict()


@router.put(
    "/settings/security/auth-lockout",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_lockout_policy_route(
    request: Request,
    payload: dict = Body(...),
    dry_run: bool = dry_run_query(),
):
    """Replace the lockout policy. Pass three nulls to clear it."""
    tenant_id = _tenant(request)
    actor = getattr(request.state, "principal", None)
    if dry_run:
        return mark_dry_run(
            request,
            would_set={
                "tenant_id": tenant_id,
                "threshold": payload.get("threshold"),
                "window_minutes": payload.get("window_minutes"),
                "cooldown_minutes": payload.get("cooldown_minutes"),
            },
            current=get_auth_lockout_policy(tenant_id).as_dict(),
        )
    try:
        policy = set_auth_lockout_policy(
            tenant_id,
            threshold=payload.get("threshold"),
            window_minutes=payload.get("window_minutes"),
            cooldown_minutes=payload.get("cooldown_minutes"),
            updated_by=actor,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return policy.as_dict()


@router.get(
    "/admin/lockouts",
    dependencies=[require_role("admin")],
)
def list_lockouts_route(request: Request) -> dict:
    """List recent lockout rows (active and historical) for the tenant."""
    tenant_id = _tenant(request)
    rows = auth_lockouts_store.list_lockouts(
        tenant_id, include_inactive=True, limit=200
    )
    return {
        "tenant_id": tenant_id,
        "policy": get_auth_lockout_policy(tenant_id).as_dict(),
        "bounds": {
            "threshold_min": AUTH_LOCKOUT_THRESHOLD_MIN,
            "threshold_max": AUTH_LOCKOUT_THRESHOLD_MAX,
            "window_min_minutes": AUTH_LOCKOUT_WINDOW_MIN_MINUTES,
            "window_max_minutes": AUTH_LOCKOUT_WINDOW_MAX_MINUTES,
            "cooldown_min_minutes": AUTH_LOCKOUT_COOLDOWN_MIN_MINUTES,
            "cooldown_max_minutes": AUTH_LOCKOUT_COOLDOWN_MAX_MINUTES,
        },
        "lockouts": [
            {
                "id": r.id,
                "ip": r.ip,
                "reason": r.reason,
                "failures_in_window": r.failures_in_window,
                "created_at": r.created_at.isoformat(),
                "locked_until": r.locked_until.isoformat(),
                "cleared_at": r.cleared_at.isoformat() if r.cleared_at else None,
                "cleared_by": r.cleared_by,
                "active": r.active,
            }
            for r in rows
        ],
        "recent_failures": auth_lockouts_store.recent_failures(tenant_id, limit=50),
    }


@router.delete(
    "/admin/lockouts/{lockout_id}",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def clear_lockout_route(
    request: Request,
    lockout_id: int,
    dry_run: bool = dry_run_query(),
):
    """Soft-clear a single lockout row scoped to the caller's tenant."""
    tenant_id = _tenant(request)
    actor = getattr(request.state, "principal", None)
    if dry_run:
        rows = auth_lockouts_store.list_lockouts(
            tenant_id, include_inactive=True, limit=1000
        )
        target = next((r for r in rows if r.id == lockout_id), None)
        if target is None or not target.active:
            return mark_dry_run(request, would_clear=None)
        return mark_dry_run(
            request,
            would_clear={
                "id": lockout_id,
                "ip": target.ip,
                "locked_until": target.locked_until.isoformat(),
            },
        )
    cleared = auth_lockouts_store.clear_lockout(tenant_id, lockout_id, cleared_by=actor)
    if not cleared:
        raise HTTPException(404, "Lockout not found or already cleared.")
    return {"tenant_id": tenant_id, "id": lockout_id, "cleared": True}
