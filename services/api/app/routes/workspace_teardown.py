"""Per-workspace teardown lifecycle (owner / admin only).

Routes:

* ``GET    /v1/workspace/teardown``                      schedule state
* ``POST   /v1/workspace/teardown``                      schedule with cool-off
* ``DELETE /v1/workspace/teardown``                      cancel a pending schedule
* ``POST   /v1/workspace/teardown/execute``              run the destruction

Every route requires the ``admin`` role and TOTP MFA step-up. Mutating
routes are picked up by the global audit middleware so the actor, IP,
user agent, and request id land in the tamper-evident audit chain.

Execute is gated four ways:

1. A schedule must exist (``409 Conflict`` otherwise).
2. The cool-off window must have elapsed (``425 Too Early``).
3. The caller must echo the tenant id back as ``?confirm=<tenant>``
   (``400 Bad Request`` otherwise).
4. No active legal hold may exist on the workspace (``423 Locked``).

``?dry_run=true`` is supported on both POST endpoints so a workspace
owner can see the cool-off date or the destruction receipt without
mutating any state.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field
from shotclassify_store import (
    DEFAULT_COOLOFF_HOURS,
    MAX_COOLOFF_HOURS,
    MIN_COOLOFF_HOURS,
    cancel_teardown,
    execute_teardown,
    get_teardown_state,
    legal_holds_store,
    schedule_teardown,
)

from ..middleware.mfa import require_mfa_step_up
from ..middleware.rbac import require_role

router = APIRouter(prefix="/v1/workspace/teardown", tags=["data-lifecycle"])


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "A tenant context is required. Pass X-Tenant or sign in "
                "to a workspace."
            ),
        )
    return tenant_id


def _principal(request: Request) -> str:
    return getattr(request.state, "principal", None) or "unknown"


class ScheduleBody(BaseModel):
    confirm: str = Field(
        ...,
        description=(
            "Must equal the workspace tenant id. Mirrors the GitHub / "
            "Stripe / AWS pattern for destructive admin actions."
        ),
    )
    cooloff_hours: int = Field(
        DEFAULT_COOLOFF_HOURS,
        ge=MIN_COOLOFF_HOURS,
        le=MAX_COOLOFF_HOURS,
        description=(
            "How long to wait before execute is allowed. "
            f"Between {MIN_COOLOFF_HOURS} and {MAX_COOLOFF_HOURS} hours."
        ),
    )
    reason: Optional[str] = Field(
        None,
        max_length=256,
        description="Free-text reason recorded on the schedule.",
    )


@router.get(
    "",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def get_state(request: Request) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    state = get_teardown_state(tenant_id)
    payload = state.to_dict()
    payload["legal_hold"] = {
        "active": legal_holds_store.tenant_has_active_hold(tenant_id),
    }
    payload["policy"] = {
        "min_cooloff_hours": MIN_COOLOFF_HOURS,
        "default_cooloff_hours": DEFAULT_COOLOFF_HOURS,
        "max_cooloff_hours": MAX_COOLOFF_HOURS,
    }
    return payload


@router.post(
    "",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def schedule(
    request: Request,
    body: ScheduleBody,
    dry_run: bool = Query(
        False,
        description=(
            "When true, validate the request and return the proposed "
            "execute_after timestamp without persisting the schedule."
        ),
    ),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    if body.confirm != tenant_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "confirmation phrase must equal the workspace tenant id "
                "to schedule a teardown."
            ),
        )
    if dry_run:
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        return {
            "dry_run": True,
            "tenant_id": tenant_id,
            "would_schedule_at": now.isoformat(),
            "would_execute_after": (
                now + timedelta(hours=body.cooloff_hours)
            ).isoformat(),
            "cooloff_hours": body.cooloff_hours,
            "reason": body.reason,
        }
    state = schedule_teardown(
        tenant_id,
        scheduled_by=_principal(request),
        cooloff_hours=body.cooloff_hours,
        reason=body.reason,
    )
    return state.to_dict()


@router.delete(
    "",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def cancel(request: Request) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    state = cancel_teardown(tenant_id, cancelled_by=_principal(request))
    return state.to_dict()


@router.post(
    "/execute",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def execute(
    request: Request,
    confirm: str = Query(
        "",
        description=(
            "Must equal the workspace tenant id to acknowledge the "
            "destructive operation."
        ),
    ),
    dry_run: bool = Query(
        False,
        description=(
            "When true, return the per-table row counts that would be "
            "deleted without mutating any state."
        ),
    ),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    if confirm != tenant_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "Pass ?confirm=<tenant-id> to acknowledge the destructive "
                "operation."
            ),
        )
    state = get_teardown_state(tenant_id)
    if not state.scheduled:
        raise HTTPException(
            status_code=409,
            detail=(
                "No teardown is scheduled. POST /v1/workspace/teardown "
                "first to schedule one with a cooling-off period."
            ),
        )
    if not state.ready_to_execute:
        raise HTTPException(
            status_code=425,
            detail={
                "error": "cooloff_not_elapsed",
                "message": (
                    "Cooling-off period has not elapsed yet. "
                    f"Execute is allowed at {state.execute_after.isoformat()}."
                ),
                "execute_after": state.execute_after.isoformat(),
            },
        )
    if legal_holds_store.tenant_has_active_hold(tenant_id):
        matters = legal_holds_store.active_hold_matters(tenant_id)
        raise HTTPException(
            status_code=423,
            detail={
                "error": "legal_hold_active",
                "message": (
                    "Workspace is under legal hold; lift all active "
                    "holds before tearing down."
                ),
                "matters": matters,
            },
        )

    if dry_run:
        from shotclassify_store import (
            AuditRepository,
            Repository,
            SavedViewRepository,
            api_keys_store,
            memberships_store,
        )

        repo = Repository()
        audit = AuditRepository()
        views = SavedViewRepository()
        return {
            "dry_run": True,
            "tenant_id": tenant_id,
            "would_delete_estimates": {
                "classifications": len(repo.list_by_tenant(tenant_id)),
                "audit_log": len(audit.list_for_tenant(tenant_id)),
                "saved_views": len(views.list_by_tenant(tenant_id)),
                "members": len(memberships_store.list_members(tenant_id)),
                "api_keys": len(
                    api_keys_store.list_keys(
                        tenant_id=tenant_id, include_revoked=True
                    )
                ),
            },
            "execute_after": state.execute_after.isoformat(),
        }

    deleted = execute_teardown(tenant_id)
    return {
        "tenant_id": tenant_id,
        "status": "executed",
        "executed": True,
        "deleted": deleted,
        "total_rows_deleted": sum(deleted.values()),
    }
