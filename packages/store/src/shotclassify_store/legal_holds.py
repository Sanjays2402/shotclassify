"""Legal hold registry.

Enterprise / regulated buyers require that, when a workspace is under
litigation hold or regulator inquiry, no automated or admin-initiated
delete can remove evidence. This module owns the table and the predicate
(`tenant_has_active_hold`) that every destructive code path consults.

Contract:

* While at least one row exists for a tenant with ``lifted_at IS NULL``
  the tenant is considered "on hold".
* `LegalHoldActive` is raised by any storage operation that would erase
  rows for an on-hold tenant. Callers translate that into HTTP 423
  Locked at the route layer.
* Lifting a hold writes ``lifted_at`` and ``lifted_by`` instead of
  deleting the row so the audit trail survives.
* Every read/write here is tenant-scoped; cross-tenant access at the
  query layer is impossible.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from .db import LegalHoldRow, get_session, init_db


class LegalHoldActive(Exception):
    """Raised when a destructive op is attempted on a tenant under hold.

    Carries the matter names so callers can surface them to operators.
    """

    def __init__(self, tenant_id: str, matters: list[str]):
        self.tenant_id = tenant_id
        self.matters = matters
        super().__init__(
            f"Tenant {tenant_id!r} is under legal hold ({len(matters)} active): "
            + ", ".join(matters)
        )


@dataclass(frozen=True)
class LegalHold:
    id: str
    tenant_id: str
    matter: str
    reason: str
    created_by: str | None
    created_at: datetime
    lifted_at: datetime | None
    lifted_by: str | None
    lifted_reason: str | None

    @property
    def active(self) -> bool:
        return self.lifted_at is None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "matter": self.matter,
            "reason": self.reason,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "lifted_at": self.lifted_at.isoformat() if self.lifted_at else None,
            "lifted_by": self.lifted_by,
            "lifted_reason": self.lifted_reason,
            "active": self.active,
        }


def _row_to_hold(row: LegalHoldRow) -> LegalHold:
    return LegalHold(
        id=row.id,
        tenant_id=row.tenant_id,
        matter=row.matter,
        reason=row.reason or "",
        created_by=row.created_by,
        created_at=row.created_at,
        lifted_at=row.lifted_at,
        lifted_by=row.lifted_by,
        lifted_reason=row.lifted_reason,
    )


MAX_MATTER_LEN = 256
MAX_REASON_LEN = 4000


def _validate_matter(raw: object) -> str:
    if not isinstance(raw, str):
        raise ValueError("matter must be a string")
    matter = raw.strip()
    if not matter:
        raise ValueError("matter is required")
    if len(matter) > MAX_MATTER_LEN:
        raise ValueError(f"matter must be at most {MAX_MATTER_LEN} characters")
    return matter


def _validate_reason(raw: object) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ValueError("reason must be a string")
    reason = raw.strip()
    if len(reason) > MAX_REASON_LEN:
        raise ValueError(f"reason must be at most {MAX_REASON_LEN} characters")
    return reason


def create_hold(
    tenant_id: str, matter: object, reason: object, *, created_by: str | None
) -> LegalHold:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    matter_clean = _validate_matter(matter)
    reason_clean = _validate_reason(reason)
    init_db()
    hold_id = f"hold_{secrets.token_hex(8)}"
    now = datetime.now(UTC)
    with get_session() as s:
        row = LegalHoldRow(
            id=hold_id,
            tenant_id=tenant_id,
            matter=matter_clean,
            reason=reason_clean,
            created_by=created_by,
            created_at=now,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return _row_to_hold(row)


def lift_hold(
    tenant_id: str, hold_id: str, reason: object, *, lifted_by: str | None
) -> LegalHold:
    if not tenant_id or not hold_id:
        raise ValueError("tenant_id and hold_id are required")
    lift_reason = _validate_reason(reason)
    init_db()
    now = datetime.now(UTC)
    with get_session() as s:
        row = s.execute(
            select(LegalHoldRow)
            .where(LegalHoldRow.id == hold_id)
            .where(LegalHoldRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            raise KeyError(hold_id)
        if row.lifted_at is not None:
            return _row_to_hold(row)
        row.lifted_at = now
        row.lifted_by = lifted_by
        row.lifted_reason = lift_reason or None
        s.commit()
        s.refresh(row)
        return _row_to_hold(row)


def list_holds(tenant_id: str, *, active_only: bool = False) -> list[LegalHold]:
    if not tenant_id:
        return []
    init_db()
    with get_session() as s:
        stmt = (
            select(LegalHoldRow)
            .where(LegalHoldRow.tenant_id == tenant_id)
            .order_by(LegalHoldRow.created_at.desc())
        )
        if active_only:
            stmt = stmt.where(LegalHoldRow.lifted_at.is_(None))
        rows = list(s.execute(stmt).scalars())
    return [_row_to_hold(r) for r in rows]


def active_hold_matters(tenant_id: str) -> list[str]:
    """Return matter names of currently active holds for ``tenant_id``."""
    return [h.matter for h in list_holds(tenant_id, active_only=True)]


def tenant_has_active_hold(tenant_id: str) -> bool:
    """Cheap predicate: True when any active hold exists for the tenant."""
    if not tenant_id:
        return False
    init_db()
    with get_session() as s:
        row = s.execute(
            select(LegalHoldRow.id)
            .where(LegalHoldRow.tenant_id == tenant_id)
            .where(LegalHoldRow.lifted_at.is_(None))
            .limit(1)
        ).first()
    return row is not None


def guard_destructive(tenant_id: str | None) -> None:
    """Raise :class:`LegalHoldActive` if ``tenant_id`` has an active hold.

    Pass-through when ``tenant_id`` is falsy so legacy code paths that have
    not yet been tenant-scoped do not crash. The route layer is responsible
    for ensuring a tenant is resolved before invoking destructive ops.
    """
    if not tenant_id:
        return
    matters = active_hold_matters(tenant_id)
    if matters:
        raise LegalHoldActive(tenant_id, matters)
