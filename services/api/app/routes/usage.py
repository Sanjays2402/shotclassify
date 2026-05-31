"""Per-principal usage and quota.

Exposes ``GET /v1/me/usage`` so the UI can render a free-tier meter and an
upgrade CTA, and ``enforce_quota`` so write paths (classify) can refuse
requests once a principal has burned through the monthly allowance.

The monthly free-tier limit is read from the ``SHOTCLASSIFY_FREE_MONTHLY_LIMIT``
env var (default 200) so it stays configurable without a schema change. The
quota window is calendar-month UTC. We count rows in ``classifications``
owned by the request principal (and tenant) created since the start of the
current UTC month.

This is a real meter backed by the same store the rest of the app uses, not
a counter we read out of memory.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from shotclassify_store import Repository

router = APIRouter(prefix="/v1/me", tags=["usage"])


def _free_monthly_limit() -> int:
    raw = os.environ.get("SHOTCLASSIFY_FREE_MONTHLY_LIMIT", "200")
    try:
        n = int(raw)
    except ValueError:
        n = 200
    return max(0, n)


def _period_start(now: datetime | None = None) -> datetime:
    """Return the start of the current UTC calendar month."""
    now = now or datetime.now(UTC)
    return datetime(now.year, now.month, 1, tzinfo=UTC)


def _next_period_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    if now.month == 12:
        return datetime(now.year + 1, 1, 1, tzinfo=UTC)
    return datetime(now.year, now.month + 1, 1, tzinfo=UTC)


def compute_usage(principal: str, tenant_id: str | None = None) -> dict:
    """Pure function so other modules (enforcement, tests) can reuse it."""
    start = _period_start()
    used = Repository().count_by_principal_since(principal, start, tenant_id=tenant_id)
    limit = _free_monthly_limit()
    remaining = max(0, limit - used)
    pct = (used / limit) if limit > 0 else 1.0
    return {
        "principal": principal,
        "tenant_id": tenant_id,
        "plan": "free",
        "period": "month",
        "period_start": start.isoformat(),
        "period_end": _next_period_start().isoformat(),
        "limit": limit,
        "used": used,
        "remaining": remaining,
        "percent": round(min(pct, 1.0), 4),
        "over_limit": used >= limit and limit > 0,
    }


def enforce_quota(principal: str | None, tenant_id: str | None = None) -> None:
    """Raise 402 Payment Required when the caller is past their free tier.

    Unauthenticated callers (no principal) are not gated here; the auth
    middleware handles that. We only enforce when we know who to bill.
    """
    if not principal:
        return
    usage = compute_usage(principal, tenant_id=tenant_id)
    if usage["over_limit"]:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "quota_exceeded",
                "message": (
                    "Monthly free-tier limit reached. "
                    "Upgrade or wait until the period resets."
                ),
                "usage": usage,
            },
        )


@router.get("/usage")
def get_my_usage(request: Request) -> dict:
    principal = getattr(request.state, "principal", None)
    if not principal:
        raise HTTPException(401, "Authenticated principal required.")
    tenant_id = getattr(request.state, "tenant_id", None)
    return compute_usage(principal, tenant_id=tenant_id)
