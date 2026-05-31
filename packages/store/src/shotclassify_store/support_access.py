"""Support access grants store.

A grant is the tenant's explicit, time-boxed consent for a vendor-side
admin to scope into their workspace via ``X-Tenant``. The middleware
calls :func:`find_active` on every cross-tenant admin request; absence
of a row (or expired/revoked) means 403. Every successful use bumps
:meth:`mark_used` so the customer can see which grants were actually
exercised.

All queries are tenant-scoped. Listing grants requires the caller's own
tenant id; we never serve grants belonging to other workspaces. The
vendor-side cross-tenant overview lives on a separate admin endpoint
that intentionally scans all tenants.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from .db import SupportAccessGrantRow, get_session, init_db

# Hard ceiling so a tenant cannot grant indefinite access.
MAX_GRANT_HOURS = 7 * 24
MIN_GRANT_MINUTES = 5


class GrantValidationError(ValueError):
    """Raised when grant input is malformed or violates policy."""


@dataclass(frozen=True)
class SupportAccessGrant:
    id: str
    tenant_id: str
    reason: str
    allowed_admin: str | None
    created_by: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    revoked_by: str | None
    last_used_at: datetime | None
    use_count: int

    @property
    def active(self) -> bool:
        now = datetime.now(UTC)
        if self.revoked_at is not None:
            return False
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return expires > now

    def to_dict(self) -> dict[str, Any]:
        def _iso(dt: datetime | None) -> str | None:
            if dt is None:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.isoformat()

        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "reason": self.reason,
            "allowed_admin": self.allowed_admin,
            "created_by": self.created_by,
            "created_at": _iso(self.created_at),
            "expires_at": _iso(self.expires_at),
            "revoked_at": _iso(self.revoked_at),
            "revoked_by": self.revoked_by,
            "last_used_at": _iso(self.last_used_at),
            "use_count": self.use_count,
            "active": self.active,
        }


def _row_to_grant(row: SupportAccessGrantRow) -> SupportAccessGrant:
    return SupportAccessGrant(
        id=row.id,
        tenant_id=row.tenant_id,
        reason=row.reason,
        allowed_admin=row.allowed_admin,
        created_by=row.created_by,
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        revoked_by=row.revoked_by,
        last_used_at=row.last_used_at,
        use_count=row.use_count,
    )


def create_grant(
    *,
    tenant_id: str,
    reason: str,
    created_by: str,
    duration_minutes: int,
    allowed_admin: str | None = None,
) -> SupportAccessGrant:
    """Create a new grant. Raises :class:`GrantValidationError` on bad input."""
    init_db()
    if not tenant_id:
        raise GrantValidationError("tenant_id is required")
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise GrantValidationError("reason must be at least 3 characters")
    if len(reason) > 1024:
        raise GrantValidationError("reason must be 1024 characters or fewer")
    if duration_minutes < MIN_GRANT_MINUTES:
        raise GrantValidationError(
            f"duration_minutes must be at least {MIN_GRANT_MINUTES}"
        )
    if duration_minutes > MAX_GRANT_HOURS * 60:
        raise GrantValidationError(
            f"duration_minutes must be at most {MAX_GRANT_HOURS * 60}"
        )
    if allowed_admin is not None:
        allowed_admin = allowed_admin.strip() or None
        if allowed_admin and len(allowed_admin) > 256:
            raise GrantValidationError("allowed_admin must be 256 characters or fewer")
    grant_id = "sag_" + secrets.token_urlsafe(16)
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=duration_minutes)
    with get_session() as s:
        row = SupportAccessGrantRow(
            id=grant_id,
            tenant_id=tenant_id,
            reason=reason,
            allowed_admin=allowed_admin,
            created_by=created_by,
            created_at=now,
            expires_at=expires,
            revoked_at=None,
            revoked_by=None,
            last_used_at=None,
            use_count=0,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return _row_to_grant(row)


def list_for_tenant(tenant_id: str, *, include_inactive: bool = True, limit: int = 100) -> list[SupportAccessGrant]:
    init_db()
    with get_session() as s:
        stmt = (
            select(SupportAccessGrantRow)
            .where(SupportAccessGrantRow.tenant_id == tenant_id)
            .order_by(SupportAccessGrantRow.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
        rows = s.execute(stmt).scalars().all()
    grants = [_row_to_grant(r) for r in rows]
    if not include_inactive:
        grants = [g for g in grants if g.active]
    return grants


def list_all_active(limit: int = 200) -> list[SupportAccessGrant]:
    """Vendor-side cross-tenant view of currently-active grants."""
    init_db()
    now = datetime.now(UTC)
    with get_session() as s:
        stmt = (
            select(SupportAccessGrantRow)
            .where(SupportAccessGrantRow.revoked_at.is_(None))
            .where(SupportAccessGrantRow.expires_at > now)
            .order_by(SupportAccessGrantRow.expires_at.asc())
            .limit(max(1, min(limit, 1000)))
        )
        rows = s.execute(stmt).scalars().all()
    return [_row_to_grant(r) for r in rows]


def get_grant(grant_id: str, *, tenant_id: str | None = None) -> SupportAccessGrant | None:
    init_db()
    with get_session() as s:
        stmt = select(SupportAccessGrantRow).where(SupportAccessGrantRow.id == grant_id)
        if tenant_id is not None:
            stmt = stmt.where(SupportAccessGrantRow.tenant_id == tenant_id)
        row = s.execute(stmt).scalar_one_or_none()
    return _row_to_grant(row) if row else None


def revoke_grant(
    grant_id: str, *, tenant_id: str, revoked_by: str
) -> SupportAccessGrant | None:
    init_db()
    with get_session() as s:
        row = s.execute(
            select(SupportAccessGrantRow).where(
                SupportAccessGrantRow.id == grant_id,
                SupportAccessGrantRow.tenant_id == tenant_id,
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            row.revoked_by = revoked_by
            s.commit()
            s.refresh(row)
        return _row_to_grant(row)


def find_active(
    tenant_id: str, *, admin_login: str | None = None
) -> SupportAccessGrant | None:
    """Return the active grant that authorizes ``admin_login`` for ``tenant_id``.

    If a grant pins an ``allowed_admin``, the caller's login must match.
    Open grants (``allowed_admin IS NULL``) authorize any admin.
    """
    init_db()
    now = datetime.now(UTC)
    with get_session() as s:
        stmt = (
            select(SupportAccessGrantRow)
            .where(SupportAccessGrantRow.tenant_id == tenant_id)
            .where(SupportAccessGrantRow.revoked_at.is_(None))
            .where(SupportAccessGrantRow.expires_at > now)
            .order_by(SupportAccessGrantRow.expires_at.desc())
        )
        rows = s.execute(stmt).scalars().all()
    for row in rows:
        if row.allowed_admin and admin_login and row.allowed_admin != admin_login:
            continue
        if row.allowed_admin and not admin_login:
            continue
        return _row_to_grant(row)
    return None


def mark_used(grant_id: str) -> None:
    init_db()
    with get_session() as s:
        row = s.execute(
            select(SupportAccessGrantRow).where(SupportAccessGrantRow.id == grant_id)
        ).scalar_one_or_none()
        if row is None:
            return
        row.last_used_at = datetime.now(UTC)
        row.use_count = (row.use_count or 0) + 1
        s.commit()
