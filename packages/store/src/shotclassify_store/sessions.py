"""Server-side session management.

Wraps the ``sessions`` table with the small surface area the auth
middleware and the admin console need:

* :func:`create` mints a new session row when a user finishes OAuth.
* :func:`touch` validates the session id presented in a cookie, refuses
  expired or revoked rows, and bumps ``last_seen_at``.
* :func:`list_for_principal` powers the "active sessions" panel.
* :func:`revoke` and :func:`revoke_all_for_principal` are the levers an
  end user (or admin) pulls to log a device out, including the
  enterprise-required "force-logout-everywhere" button.

All writes use ``datetime.now(UTC)`` so timestamps are timezone-aware and
comparable across deployments.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from .db import SessionRow, get_session


SESSION_TTL = timedelta(days=30)


@dataclass(frozen=True)
class SessionInfo:
    id: str
    principal: str
    tenant_id: str | None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    client_ip: str | None
    user_agent: str | None
    auth_method: str = "oauth"
    mfa_verified_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "principal": self.principal,
            "tenant_id": self.tenant_id,
            "created_at": self.created_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "client_ip": self.client_ip,
            "user_agent": self.user_agent,
            "auth_method": self.auth_method,
            "mfa_verified_at": self.mfa_verified_at.isoformat() if self.mfa_verified_at else None,
        }


def _to_info(row: SessionRow) -> SessionInfo:
    return SessionInfo(
        id=row.id,
        principal=row.principal,
        tenant_id=row.tenant_id,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        client_ip=row.client_ip,
        user_agent=row.user_agent,
        auth_method=getattr(row, "auth_method", "oauth") or "oauth",
        mfa_verified_at=getattr(row, "mfa_verified_at", None),
    )


def create(
    *,
    principal: str,
    tenant_id: str | None,
    client_ip: str | None,
    user_agent: str | None,
    ttl: timedelta = SESSION_TTL,
    auth_method: str = "oauth",
    max_sessions_per_user: int | None = None,
) -> SessionInfo:
    """Mint a new session row.

    When ``max_sessions_per_user`` is set (per-tenant policy), the oldest
    active sessions for the same ``principal`` inside ``tenant_id`` are
    revoked first so the new row plus surviving active rows never
    exceeds the cap. Oldest is computed by ``last_seen_at`` so the most
    recently used device (typically the active workstation) survives.
    The eviction is bounded to the same tenant: a user's sessions in
    other workspaces are never touched by another workspace's policy.
    """
    now = datetime.now(UTC)
    if (
        max_sessions_per_user is not None
        and max_sessions_per_user >= 1
        and tenant_id
    ):
        keep = max_sessions_per_user - 1
        with get_session() as s:
            active = list(
                s.scalars(
                    select(SessionRow)
                    .where(SessionRow.principal == principal)
                    .where(SessionRow.tenant_id == tenant_id)
                    .where(SessionRow.revoked_at.is_(None))
                    .where(SessionRow.expires_at > now)
                    .order_by(SessionRow.last_seen_at.desc())
                ).all()
            )
            if len(active) > keep:
                for victim in active[keep:]:
                    victim.revoked_at = now
                s.commit()
    row = SessionRow(
        id=secrets.token_urlsafe(24),
        principal=principal,
        tenant_id=tenant_id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + ttl,
        revoked_at=None,
        client_ip=client_ip,
        user_agent=(user_agent or "")[:512] or None,
        auth_method=auth_method,
    )
    with get_session() as s:
        s.add(row)
        s.commit()
        s.refresh(row)
        return _to_info(row)


def touch(sid: str, *, idle_timeout: timedelta | None = None) -> SessionInfo | None:
    """Return the active session for ``sid`` or ``None`` if it is invalid.

    Bumps ``last_seen_at`` as a side effect so the admin console can show
    which devices are currently in use. Expired or revoked sessions are
    treated as invalid and never touched.

    If ``idle_timeout`` is set and the row's previous ``last_seen_at`` is
    older than ``now - idle_timeout``, the session is revoked in place
    and ``None`` is returned. This implements the per-tenant inactivity
    timeout that enterprise security questionnaires (SOC2 CC6.1) require.
    """
    if not sid:
        return None
    now = datetime.now(UTC)
    with get_session() as s:
        row = s.get(SessionRow, sid)
        if row is None:
            return None
        if row.revoked_at is not None:
            return None
        # SQLite returns naive datetimes; coerce so the comparison works.
        exp = row.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        if exp <= now:
            return None
        if idle_timeout is not None and idle_timeout > timedelta(0):
            last = row.last_seen_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            if now - last > idle_timeout:
                row.revoked_at = now
                s.commit()
                return None
        row.last_seen_at = now
        s.commit()
        s.refresh(row)
        return _to_info(row)


def get(sid: str) -> SessionInfo | None:
    with get_session() as s:
        row = s.get(SessionRow, sid)
        return _to_info(row) if row else None


def list_for_principal(principal: str, include_revoked: bool = False) -> list[SessionInfo]:
    stmt = select(SessionRow).where(SessionRow.principal == principal)
    if not include_revoked:
        stmt = stmt.where(SessionRow.revoked_at.is_(None))
    stmt = stmt.order_by(SessionRow.last_seen_at.desc())
    with get_session() as s:
        rows = s.scalars(stmt).all()
        return [_to_info(r) for r in rows]


def list_all(tenant_id: str | None = None) -> list[SessionInfo]:
    """Admin view: every session, optionally scoped to one tenant."""
    stmt = select(SessionRow)
    if tenant_id is not None:
        stmt = stmt.where(SessionRow.tenant_id == tenant_id)
    stmt = stmt.order_by(SessionRow.last_seen_at.desc())
    with get_session() as s:
        rows = s.scalars(stmt).all()
        return [_to_info(r) for r in rows]


def revoke(sid: str) -> bool:
    """Mark a single session revoked. Returns True if it existed and was active."""
    now = datetime.now(UTC)
    with get_session() as s:
        row = s.get(SessionRow, sid)
        if row is None or row.revoked_at is not None:
            return False
        row.revoked_at = now
        s.commit()
        return True


def revoke_all_for_principal(principal: str, *, except_sid: str | None = None) -> int:
    """Revoke every active session belonging to ``principal``.

    Returns the count actually revoked. Pass ``except_sid`` to keep the
    current session alive (so "log out everywhere else" does not kick the
    caller out of the page they pressed the button on).
    """
    now = datetime.now(UTC)
    stmt = (
        update(SessionRow)
        .where(SessionRow.principal == principal)
        .where(SessionRow.revoked_at.is_(None))
    )
    if except_sid:
        stmt = stmt.where(SessionRow.id != except_sid)
    stmt = stmt.values(revoked_at=now)
    with get_session() as s:
        result = s.execute(stmt)
        s.commit()
        return int(result.rowcount or 0)


def clip_active_for_tenant(tenant_id: str, ttl: timedelta) -> int:
    """Shorten ``expires_at`` for every active tenant session that currently
    exceeds ``now + ttl``.

    Called when an admin lowers the per-tenant session TTL so a long-lived
    cookie minted before the policy change cannot outlive the new rule.
    Sessions whose remaining lifetime is already under ``ttl`` are left
    alone. Returns the number of rows updated.
    """
    if not tenant_id:
        return 0
    now = datetime.now(UTC)
    cutoff = now + ttl
    stmt = (
        update(SessionRow)
        .where(SessionRow.tenant_id == tenant_id)
        .where(SessionRow.revoked_at.is_(None))
        .where(SessionRow.expires_at > cutoff)
        .values(expires_at=cutoff)
    )
    with get_session() as s:
        result = s.execute(stmt)
        s.commit()
        return int(result.rowcount or 0)
