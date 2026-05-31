"""Per-(tenant, source IP) authentication brute-force lockout store.

This module is the durable side of the auth brute-force control. The
auth middleware calls :func:`record_failure` on every rejected
credential (bad API key, bad SCIM bearer, bad session cookie, bad SSO
callback) and :func:`check_locked` before any credential check. When
the count of recent failures for a (tenant, ip) pair crosses the
per-tenant threshold, :func:`record_failure` writes an
``AuthLockoutRow`` whose ``locked_until`` blocks every subsequent
request from that IP for that tenant until the cooldown elapses.

Lockouts are *per (tenant_id, ip)*. A noisy attacker against tenant
``acme`` cannot, by spraying credentials, also lock out the legitimate
operators of tenant ``globex`` coming from the same NAT egress. That
isolation is what the test suite asserts.

The store is intentionally tiny: no Redis dependency, no in-memory
state, and no background sweeper. All decisions are made by a small
indexed SELECT at request time. Old failure rows are pruned lazily
when the lockout policy decides whether the threshold was crossed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from .db import AuthFailureRow, AuthLockoutRow, get_session, init_db
from .tenant_settings import get_auth_lockout_policy


@dataclass(frozen=True, slots=True)
class LockoutStatus:
    """Result of :func:`check_locked`.

    ``locked`` is True when an active, non-cleared, non-expired lockout
    row exists for the (tenant, ip) pair. ``retry_after_seconds`` is
    the integer number of seconds the caller should wait before trying
    again; the auth middleware places that value in the ``Retry-After``
    response header.
    """

    locked: bool
    locked_until: datetime | None
    retry_after_seconds: int
    reason: str | None
    failures_in_window: int


_OK = LockoutStatus(False, None, 0, None, 0)


def _normalize_ip(ip: str | None) -> str:
    """Return a non-empty source-IP string used as the lockout key.

    Empty / missing IPs are coerced to the literal ``"unknown"`` so a
    single bucket absorbs all unattributable traffic instead of
    fragmenting per-row. The middleware only calls in with a real IP
    in practice; this just keeps the schema constraints happy.
    """
    s = (ip or "").strip()
    return s or "unknown"


def check_locked(tenant_id: str, ip: str | None) -> LockoutStatus:
    """Return whether ``(tenant_id, ip)`` is currently locked out."""
    if not tenant_id:
        return _OK
    policy = get_auth_lockout_policy(tenant_id)
    if not policy.enabled:
        return _OK
    addr = _normalize_ip(ip)
    init_db()
    now = datetime.now(UTC)
    with get_session() as s:
        row = s.execute(
            select(AuthLockoutRow)
            .where(
                AuthLockoutRow.tenant_id == tenant_id,
                AuthLockoutRow.ip == addr,
                AuthLockoutRow.cleared_at.is_(None),
                AuthLockoutRow.locked_until > now,
            )
            .order_by(AuthLockoutRow.locked_until.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            return _OK
        # SQLite drops the tzinfo on store; treat naive timestamps as UTC.
        locked_until = row.locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=UTC)
        delta = (locked_until - now).total_seconds()
        retry_after = max(1, int(delta))
        return LockoutStatus(
            locked=True,
            locked_until=locked_until,
            retry_after_seconds=retry_after,
            reason=row.reason,
            failures_in_window=row.failures_in_window,
        )


def record_failure(
    tenant_id: str | None,
    ip: str | None,
    kind: str,
) -> LockoutStatus:
    """Append a failure row and, if the threshold is crossed, lock out.

    Returns the resulting :class:`LockoutStatus`. The caller (the auth
    middleware) uses ``status.locked`` to decide whether the *next*
    request from this IP should be rejected outright; on the current
    request it has already produced a 401, so the status is mostly
    informational for logging.

    No-ops when the tenant has no lockout policy configured.
    """
    if not tenant_id:
        return _OK
    policy = get_auth_lockout_policy(tenant_id)
    if not policy.enabled:
        return _OK
    addr = _normalize_ip(ip)
    init_db()
    now = datetime.now(UTC)
    window_start = now - timedelta(minutes=policy.window_minutes)
    locked_until = now + timedelta(minutes=policy.cooldown_minutes)
    with get_session() as s:
        s.add(
            AuthFailureRow(
                tenant_id=tenant_id, ip=addr, kind=kind[:16], ts=now,
            )
        )
        # Count failures inside the sliding window (including the row we
        # just added). The flush ensures the new row is visible to the
        # count query inside this transaction.
        s.flush()
        # Lazy prune: drop ancient rows for this (tenant, ip) so the
        # ledger does not grow unboundedly even without a sweeper.
        prune_before = now - timedelta(
            minutes=max(policy.window_minutes * 4, 60)
        )
        s.execute(
            delete(AuthFailureRow).where(
                AuthFailureRow.tenant_id == tenant_id,
                AuthFailureRow.ip == addr,
                AuthFailureRow.ts < prune_before,
            )
        )
        count = (
            s.query(AuthFailureRow)
            .filter(
                AuthFailureRow.tenant_id == tenant_id,
                AuthFailureRow.ip == addr,
                AuthFailureRow.ts >= window_start,
            )
            .count()
        )
        s.commit()
        if count < policy.threshold:
            return LockoutStatus(False, None, 0, None, count)
        # Look for an already-active lockout we should *extend* rather
        # than duplicate. This keeps the table tidy under sustained
        # attack.
        existing = s.execute(
            select(AuthLockoutRow).where(
                AuthLockoutRow.tenant_id == tenant_id,
                AuthLockoutRow.ip == addr,
                AuthLockoutRow.cleared_at.is_(None),
                AuthLockoutRow.locked_until > now,
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.locked_until = locked_until
            existing.failures_in_window = count
            existing.reason = kind[:32]
            s.commit()
            row = existing
        else:
            row = AuthLockoutRow(
                tenant_id=tenant_id,
                ip=addr,
                reason=kind[:32],
                failures_in_window=count,
                created_at=now,
                locked_until=locked_until,
            )
            s.add(row)
            s.commit()
        return LockoutStatus(
            locked=True,
            locked_until=locked_until,
            retry_after_seconds=max(1, int((locked_until - now).total_seconds())),
            reason=row.reason,
            failures_in_window=count,
        )


@dataclass(frozen=True, slots=True)
class LockoutView:
    id: int
    tenant_id: str
    ip: str
    reason: str
    failures_in_window: int
    created_at: datetime
    locked_until: datetime
    cleared_at: datetime | None
    cleared_by: str | None
    active: bool


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def list_lockouts(
    tenant_id: str, *, include_inactive: bool = True, limit: int = 100
) -> list[LockoutView]:
    """List lockout rows for ``tenant_id`` newest first.

    Only rows belonging to ``tenant_id`` are returned, ever. That is the
    cross-tenant isolation guarantee the admin UI depends on.
    """
    if not tenant_id:
        return []
    init_db()
    now = datetime.now(UTC)
    with get_session() as s:
        q = (
            select(AuthLockoutRow)
            .where(AuthLockoutRow.tenant_id == tenant_id)
            .order_by(AuthLockoutRow.created_at.desc())
            .limit(max(1, min(int(limit), 500)))
        )
        rows = list(s.execute(q).scalars().all())
    out: list[LockoutView] = []
    for r in rows:
        locked_until = _as_utc(r.locked_until)
        cleared_at = _as_utc(r.cleared_at)
        active = (
            r.cleared_at is None
            and locked_until is not None
            and locked_until > now
        )
        if not include_inactive and not active:
            continue
        out.append(
            LockoutView(
                id=r.id,
                tenant_id=r.tenant_id,
                ip=r.ip,
                reason=r.reason,
                failures_in_window=r.failures_in_window,
                created_at=_as_utc(r.created_at) or now,
                locked_until=locked_until or now,
                cleared_at=cleared_at,
                cleared_by=r.cleared_by,
                active=active,
            )
        )
    return out


def clear_lockout(
    tenant_id: str, lockout_id: int, cleared_by: str | None
) -> bool:
    """Soft-clear an active lockout row; returns True if a row was changed.

    Refuses to touch rows that belong to another tenant. That is the
    cross-tenant write isolation guarantee the admin UI depends on:
    even if an admin presents an id that resolves to another tenant's
    lockout, this function returns False and writes nothing.
    """
    if not tenant_id or not lockout_id:
        return False
    init_db()
    now = datetime.now(UTC)
    with get_session() as s:
        row = s.execute(
            select(AuthLockoutRow).where(
                AuthLockoutRow.id == int(lockout_id),
                AuthLockoutRow.tenant_id == tenant_id,
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        if row.cleared_at is not None:
            return False
        row.cleared_at = now
        row.cleared_by = (cleared_by or "")[:256] or None
        s.commit()
        return True


def recent_failures(tenant_id: str, *, limit: int = 50) -> list[dict]:
    """Return the most recent failure rows for the tenant (for the admin UI)."""
    if not tenant_id:
        return []
    init_db()
    with get_session() as s:
        rows = list(
            s.execute(
                select(AuthFailureRow)
                .where(AuthFailureRow.tenant_id == tenant_id)
                .order_by(AuthFailureRow.ts.desc())
                .limit(max(1, min(int(limit), 500)))
            ).scalars().all()
        )
    return [
        {
            "id": r.id,
            "ip": r.ip,
            "kind": r.kind,
            "ts": (_as_utc(r.ts) or datetime.now(UTC)).isoformat(),
        }
        for r in rows
    ]
