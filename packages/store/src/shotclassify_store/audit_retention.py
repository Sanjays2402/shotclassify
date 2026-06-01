"""Per-tenant audit-log retention policy.

Stores the policy on ``tenant_settings.audit_retention_days`` and provides
a purge function that hard-deletes audit-log rows older than the configured
window, scoped strictly to a single tenant per call so cross-tenant data
is never touched by another tenant's policy.

Design notes:

* ``audit_retention_days = None`` or ``<= 0`` keeps audit data indefinitely.
  New deployments and existing tenants stay opt-in.
* Maximum window is ``3650`` days (10 years) to bound input.
* Purge is performed in chunks of ``PURGE_CHUNK`` to keep transaction size
  small.
* Legal hold short-circuit: when a workspace is on hold the purge MUST NOT
  erase any of its rows, even ones outside the window. Mirrors
  :mod:`shotclassify_store.retention`.
* Audit rows are cryptographically chained; deleting them intentionally
  breaks the chain for the affected tenant. The
  :meth:`AuditRepository.verify_chain` verifier reports the break, which
  is the auditable evidence of a retention purge rather than an undisclosed
  mutation.
* The purge is also a useful operator action because some customers ask
  for the *upper bound* on audit retention (GDPR-style data minimisation).
  When the bound is a *lower bound* instead (SOC 2 / HIPAA), the operator
  simply does not configure the policy.

The purge is intentionally a separate routine from
:func:`shotclassify_store.retention.purge_expired_for_tenant` because
audit rows and classification rows are governed by different contract
clauses and different scheduled jobs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from .db import AuditLogRow, TenantSettingsRow, get_session, init_db


MAX_AUDIT_RETENTION_DAYS = 3650
PURGE_CHUNK = 500


@dataclass(frozen=True)
class AuditPurgeResult:
    tenant_id: str
    audit_retention_days: int
    cutoff: datetime
    removed: int
    held: bool = False

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "audit_retention_days": self.audit_retention_days,
            "cutoff": self.cutoff.isoformat(),
            "removed": self.removed,
            "held": self.held,
        }


def _normalize_days(raw: object) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise ValueError("audit_retention_days must be an integer, not a bool")
    if not isinstance(raw, int):
        try:
            raw = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"audit_retention_days must be an integer: {raw!r}"
            ) from exc
    if raw < 0:
        raise ValueError("audit_retention_days cannot be negative")
    if raw > MAX_AUDIT_RETENTION_DAYS:
        raise ValueError(
            f"audit_retention_days cannot exceed {MAX_AUDIT_RETENTION_DAYS} "
            "(about 10 years)"
        )
    # 0 means "disabled"; store as NULL for consistency with retention_days.
    return raw or None


def get_audit_retention_days(tenant_id: str) -> int | None:
    if not tenant_id:
        return None
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            return None
        days = row.audit_retention_days
        if not days or days <= 0:
            return None
        return int(days)


def set_audit_retention_days(
    tenant_id: str, days: object, updated_by: str | None
) -> int | None:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    normalized = _normalize_days(days)
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                audit_retention_days=normalized,
                updated_at=now,
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.audit_retention_days = normalized
            row.updated_at = now
            row.updated_by = updated_by
        s.commit()
    return normalized


def purge_expired_audit_for_tenant(
    tenant_id: str, *, now: datetime | None = None
) -> AuditPurgeResult:
    """Hard-delete audit rows older than the tenant's audit-retention window.

    Tenant scoping: the DELETE is gated on ``tenant_id == :tenant_id`` so
    rows belonging to any other tenant cannot be touched by this call.
    Rows whose ``tenant_id`` is NULL (pre-multi-tenant migration) are
    deliberately left alone: they have no owner and may not legally be
    removed by any single tenant's policy.

    Returns ``removed=0`` when no policy is set; callers should treat that
    as a no-op so a scheduled job can iterate every tenant unconditionally.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    # Legal hold short-circuit: mirror retention.purge_expired_for_tenant.
    from .legal_holds import tenant_has_active_hold

    days = get_audit_retention_days(tenant_id)
    now = now or datetime.now(UTC)
    if tenant_has_active_hold(tenant_id):
        return AuditPurgeResult(
            tenant_id=tenant_id,
            audit_retention_days=days or 0,
            cutoff=now,
            removed=0,
            held=True,
        )
    if not days:
        return AuditPurgeResult(
            tenant_id=tenant_id,
            audit_retention_days=0,
            cutoff=now,
            removed=0,
        )
    cutoff = now - timedelta(days=days)
    init_db()
    removed_total = 0
    while True:
        with get_session() as s:
            # Select a chunk of expired ids, then DELETE by id. SQLite
            # tolerates DELETE ... LIMIT but Postgres does not; the
            # id-list pattern works on both.
            id_stmt = (
                select(AuditLogRow.id)
                .where(AuditLogRow.tenant_id == tenant_id)
                .where(AuditLogRow.created_at < cutoff)
                .limit(PURGE_CHUNK)
            )
            ids = [row[0] for row in s.execute(id_stmt).all()]
            if not ids:
                break
            del_stmt = sa_delete(AuditLogRow).where(
                AuditLogRow.tenant_id == tenant_id,
                AuditLogRow.id.in_(ids),
            )
            result = s.execute(del_stmt)
            s.commit()
            removed_total += int(result.rowcount or 0)
        if len(ids) < PURGE_CHUNK:
            break
    return AuditPurgeResult(
        tenant_id=tenant_id,
        audit_retention_days=days,
        cutoff=cutoff,
        removed=removed_total,
    )


def list_tenants_with_audit_retention() -> list[str]:
    """Return tenant_ids that have a positive audit-retention policy set."""
    init_db()
    with get_session() as s:
        rows = s.execute(
            select(TenantSettingsRow.tenant_id).where(
                TenantSettingsRow.audit_retention_days.is_not(None)
            )
        ).all()
    return [r[0] for r in rows if r[0]]


def purge_expired_audit_all_tenants(
    *, now: datetime | None = None
) -> list[AuditPurgeResult]:
    """Run :func:`purge_expired_audit_for_tenant` for every configured tenant."""
    out: list[AuditPurgeResult] = []
    for tenant_id in list_tenants_with_audit_retention():
        out.append(purge_expired_audit_for_tenant(tenant_id, now=now))
    return out
