"""Per-tenant emergency freeze (write lockdown).

A workspace owner engages a freeze when they suspect compromise (leaked
credential, departing admin, suspicious traffic spike) and need to halt
every state change for their workspace *now*, without waiting for ops
to redeploy. The :class:`FreezeMiddleware` reads the row on every
mutating request and short-circuits with HTTP 423 ``tenant_frozen`` if
the tenant is frozen.

Reads remain open on purpose so incident responders can still pull the
audit log, export data, and read settings while the freeze is engaged.

Both engaging and lifting the freeze require owner role + MFA step-up
at the route layer, so this module only enforces invariants on the
inputs (reason length, normalised whitespace) and writes the row.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import select

from .db import TenantSettingsRow, get_session, init_db


FREEZE_REASON_MAX_LEN = 256


@dataclass(frozen=True)
class FreezeState:
    tenant_id: str
    frozen: bool
    reason: Optional[str]
    engaged_at: Optional[datetime]
    engaged_by: Optional[str]

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "frozen": self.frozen,
            "reason": self.reason,
            "engaged_at": self.engaged_at.isoformat() if self.engaged_at else None,
            "engaged_by": self.engaged_by,
        }


def _empty(tenant_id: str) -> FreezeState:
    return FreezeState(
        tenant_id=tenant_id,
        frozen=False,
        reason=None,
        engaged_at=None,
        engaged_by=None,
    )


def get_freeze_state(tenant_id: str) -> FreezeState:
    """Return the current freeze state for ``tenant_id``.

    Tenants without a settings row are treated as not-frozen so the
    middleware no-ops on first-time deployments.
    """
    if not tenant_id:
        return _empty("")
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(
                TenantSettingsRow.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
        if row is None:
            return _empty(tenant_id)
        return FreezeState(
            tenant_id=tenant_id,
            frozen=bool(row.freeze_mode),
            reason=row.freeze_reason,
            engaged_at=row.freeze_engaged_at,
            engaged_by=row.freeze_engaged_by,
        )


def is_frozen(tenant_id: str) -> bool:
    """Fast path used by the middleware on every mutating request."""
    return get_freeze_state(tenant_id).frozen


def _normalize_reason(raw: Optional[str]) -> str:
    if raw is None:
        raise ValueError("freeze reason is required")
    if not isinstance(raw, str):
        raise ValueError("freeze reason must be a string")
    cleaned = " ".join(raw.split())  # collapse whitespace
    if not cleaned:
        raise ValueError("freeze reason must not be empty")
    if len(cleaned) > FREEZE_REASON_MAX_LEN:
        raise ValueError(
            f"freeze reason must be {FREEZE_REASON_MAX_LEN} characters or fewer"
        )
    return cleaned


def engage_freeze(
    tenant_id: str, reason: str, engaged_by: Optional[str]
) -> FreezeState:
    """Mark ``tenant_id`` as frozen with ``reason`` recorded.

    Idempotent: re-engaging while already frozen refreshes the reason
    and ``engaged_at`` so the dashboard banner reflects the latest
    incident note. Returns the new state.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    normalized = _normalize_reason(reason)
    init_db()
    now = datetime.now(UTC)
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(
                TenantSettingsRow.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                freeze_mode=True,
                freeze_reason=normalized,
                freeze_engaged_at=now,
                freeze_engaged_by=engaged_by,
                updated_at=now,
                updated_by=engaged_by,
            )
            s.add(row)
        else:
            row.freeze_mode = True
            row.freeze_reason = normalized
            row.freeze_engaged_at = now
            row.freeze_engaged_by = engaged_by
            row.updated_at = now
            row.updated_by = engaged_by
        s.commit()
    return FreezeState(
        tenant_id=tenant_id,
        frozen=True,
        reason=normalized,
        engaged_at=now,
        engaged_by=engaged_by,
    )


def lift_freeze(tenant_id: str, lifted_by: Optional[str]) -> FreezeState:
    """Clear the freeze for ``tenant_id``.

    Wipes ``freeze_reason``, ``freeze_engaged_at`` and ``freeze_engaged_by``
    so the next ``get_freeze_state`` reads as never-engaged. Returns the
    new state. No-op (still returns the cleared state) when the tenant
    was not frozen, so the route handler can be naturally idempotent.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    init_db()
    now = datetime.now(UTC)
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(
                TenantSettingsRow.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
        if row is not None:
            row.freeze_mode = False
            row.freeze_reason = None
            row.freeze_engaged_at = None
            row.freeze_engaged_by = None
            row.updated_at = now
            row.updated_by = lifted_by
            s.commit()
    return _empty(tenant_id)
