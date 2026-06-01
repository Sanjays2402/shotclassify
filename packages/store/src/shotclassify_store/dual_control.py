"""Per-workspace dual-control (two-person rule) for API key issuance.

A workspace owner enables this policy when their procurement contract or
SOC2 control matrix requires separation of duties on credentials with
write or admin authority. Once enabled, a request from an admin to mint
an API key with the ``admin`` scope is held in
``api_key_issuance_requests`` until a *different* admin reviews and
approves it. Self-approval is rejected at the route layer.

The policy bit itself lives on ``TenantSettingsRow.dual_control_enabled``
so it is read by the same fast path as the rest of the security policy
columns. The queue is its own table because the rows have a real
lifecycle (pending -> approved/denied/expired) and need to be enumerated
in the admin console.

Pending rows older than ``DEFAULT_TTL_HOURS`` are considered expired and
filtered out by :func:`list_pending`. They stay in the table so the
audit trail of "who asked, who approved, when" survives forever.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy import select, update

from .db import (
    ApiKeyIssuanceRequestRow,
    TenantSettingsRow,
    get_session,
    init_db,
)

DEFAULT_TTL_HOURS = 72

# Scopes that require dual-control when the policy is enabled. Today
# this is ``admin`` (full mutate on the tenant) but the set is kept here
# so a future migration can extend it without re-wiring callers.
PROTECTED_SCOPES: frozenset[str] = frozenset({"admin"})


class DualControlError(Exception):
    """Raised when an approval would violate the two-person rule."""


@dataclass(frozen=True)
class IssuanceRequest:
    id: str
    tenant_id: str
    requested_by: str
    label: str
    scopes: list[str]
    ttl_days: Optional[int]
    owner_email: Optional[str]
    justification: str
    status: str
    created_at: datetime
    expires_at: datetime
    decided_by: Optional[str]
    decided_at: Optional[datetime]
    decision_note: Optional[str]
    minted_key_id: Optional[str]

    @property
    def is_expired(self) -> bool:
        if self.status != "pending":
            return False
        exp = self.expires_at
        # SQLite drops tzinfo on round-trip; treat naive as UTC.
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        return datetime.now(UTC) >= exp

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "requested_by": self.requested_by,
            "label": self.label,
            "scopes": list(self.scopes),
            "ttl_days": self.ttl_days,
            "owner_email": self.owner_email,
            "justification": self.justification,
            "status": "expired" if self.is_expired else self.status,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "decided_by": self.decided_by,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decision_note": self.decision_note,
            "minted_key_id": self.minted_key_id,
        }


def _row_to_request(row: ApiKeyIssuanceRequestRow) -> IssuanceRequest:
    return IssuanceRequest(
        id=row.id,
        tenant_id=row.tenant_id,
        requested_by=row.requested_by,
        label=row.label,
        scopes=list(row.scopes or []),
        ttl_days=row.ttl_days,
        owner_email=row.owner_email,
        justification=row.justification,
        status=row.status,
        created_at=row.created_at,
        expires_at=row.expires_at,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        decision_note=row.decision_note,
        minted_key_id=row.minted_key_id,
    )


def get_policy(tenant_id: str) -> bool:
    """Return True when dual-control is enabled for ``tenant_id``."""
    if not tenant_id:
        return False
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(
                TenantSettingsRow.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
        return bool(row and row.dual_control_enabled)


def set_policy(
    tenant_id: str,
    *,
    enabled: bool,
    updated_by: Optional[str] = None,
) -> bool:
    """Toggle the policy. Returns the new value."""
    if not tenant_id:
        raise ValueError("tenant_id is required")
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(
                TenantSettingsRow.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
        if row is None:
            row = TenantSettingsRow(tenant_id=tenant_id)
            s.add(row)
        row.dual_control_enabled = bool(enabled)
        row.updated_at = datetime.now(UTC)
        if updated_by:
            row.updated_by = updated_by
        s.commit()
        return bool(row.dual_control_enabled)


def scopes_require_dual_control(scopes: Iterable[str]) -> bool:
    return any(s in PROTECTED_SCOPES for s in scopes or [])


def create_request(
    *,
    tenant_id: str,
    requested_by: str,
    label: str,
    scopes: list[str],
    ttl_days: Optional[int],
    owner_email: Optional[str],
    justification: str,
    request_ttl_hours: int = DEFAULT_TTL_HOURS,
) -> IssuanceRequest:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    if not requested_by:
        raise ValueError("requested_by is required")
    label = (label or "").strip()
    if not label:
        raise ValueError("label is required")
    justification = (justification or "").strip()
    if len(justification) < 20:
        raise ValueError(
            "justification must be at least 20 characters so the second "
            "reviewer has context for the approval decision"
        )
    if not scopes:
        raise ValueError("scopes is required")
    init_db()
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=max(1, int(request_ttl_hours)))
    row = ApiKeyIssuanceRequestRow(
        id=secrets.token_urlsafe(16),
        tenant_id=tenant_id,
        requested_by=requested_by,
        label=label,
        scopes=list(scopes),
        ttl_days=ttl_days,
        owner_email=owner_email,
        justification=justification,
        status="pending",
        created_at=now,
        expires_at=expires_at,
    )
    with get_session() as s:
        s.add(row)
        s.commit()
        s.refresh(row)
        return _row_to_request(row)


def get_request(request_id: str, *, tenant_id: str) -> Optional[IssuanceRequest]:
    if not request_id or not tenant_id:
        return None
    init_db()
    with get_session() as s:
        row = s.execute(
            select(ApiKeyIssuanceRequestRow).where(
                ApiKeyIssuanceRequestRow.id == request_id,
                ApiKeyIssuanceRequestRow.tenant_id == tenant_id,
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return _row_to_request(row)


def list_pending(tenant_id: str) -> list[IssuanceRequest]:
    if not tenant_id:
        return []
    init_db()
    with get_session() as s:
        rows = s.execute(
            select(ApiKeyIssuanceRequestRow)
            .where(
                ApiKeyIssuanceRequestRow.tenant_id == tenant_id,
                ApiKeyIssuanceRequestRow.status == "pending",
            )
            .order_by(ApiKeyIssuanceRequestRow.created_at.desc())
        ).scalars().all()
        out: list[IssuanceRequest] = []
        for r in rows:
            req = _row_to_request(r)
            if not req.is_expired:
                out.append(req)
        return out


def list_recent(tenant_id: str, *, limit: int = 50) -> list[IssuanceRequest]:
    if not tenant_id:
        return []
    init_db()
    limit = max(1, min(500, int(limit)))
    with get_session() as s:
        rows = s.execute(
            select(ApiKeyIssuanceRequestRow)
            .where(ApiKeyIssuanceRequestRow.tenant_id == tenant_id)
            .order_by(ApiKeyIssuanceRequestRow.created_at.desc())
            .limit(limit)
        ).scalars().all()
        return [_row_to_request(r) for r in rows]


def approve(
    request_id: str,
    *,
    tenant_id: str,
    approver: str,
    note: Optional[str] = None,
) -> IssuanceRequest:
    """Mark a request approved by ``approver``.

    Raises :class:`DualControlError` if the approver is the requester
    (self-approval) or if the request is not pending / has expired.
    The caller is responsible for actually minting the key and then
    calling :func:`mark_minted` with the new key id.
    """
    if not approver:
        raise DualControlError("approver is required")
    init_db()
    with get_session() as s:
        row = s.execute(
            select(ApiKeyIssuanceRequestRow).where(
                ApiKeyIssuanceRequestRow.id == request_id,
                ApiKeyIssuanceRequestRow.tenant_id == tenant_id,
            )
        ).scalar_one_or_none()
        if row is None:
            raise DualControlError("request not found")
        if row.status != "pending":
            raise DualControlError(f"request is already {row.status}")
        if datetime.now(UTC) >= (row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)):
            row.status = "expired"
            s.commit()
            raise DualControlError("request has expired")
        if approver == row.requested_by:
            raise DualControlError(
                "self-approval is not allowed under the two-person rule; "
                "a different admin must approve this request"
            )
        row.status = "approved"
        row.decided_by = approver
        row.decided_at = datetime.now(UTC)
        row.decision_note = (note or "").strip() or None
        s.commit()
        s.refresh(row)
        return _row_to_request(row)


def deny(
    request_id: str,
    *,
    tenant_id: str,
    decider: str,
    note: Optional[str] = None,
) -> IssuanceRequest:
    init_db()
    with get_session() as s:
        row = s.execute(
            select(ApiKeyIssuanceRequestRow).where(
                ApiKeyIssuanceRequestRow.id == request_id,
                ApiKeyIssuanceRequestRow.tenant_id == tenant_id,
            )
        ).scalar_one_or_none()
        if row is None:
            raise DualControlError("request not found")
        if row.status != "pending":
            raise DualControlError(f"request is already {row.status}")
        if decider == row.requested_by:
            # Self-deny is allowed (an admin can cancel their own ask)
            # but we record it as "cancelled" not "denied".
            row.status = "cancelled"
        else:
            row.status = "denied"
        row.decided_by = decider
        row.decided_at = datetime.now(UTC)
        row.decision_note = (note or "").strip() or None
        s.commit()
        s.refresh(row)
        return _row_to_request(row)


def mark_minted(request_id: str, *, tenant_id: str, key_id: str) -> None:
    init_db()
    with get_session() as s:
        s.execute(
            update(ApiKeyIssuanceRequestRow)
            .where(
                ApiKeyIssuanceRequestRow.id == request_id,
                ApiKeyIssuanceRequestRow.tenant_id == tenant_id,
            )
            .values(minted_key_id=key_id)
        )
        s.commit()
