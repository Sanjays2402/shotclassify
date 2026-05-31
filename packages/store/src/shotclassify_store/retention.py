"""Per-tenant data retention policy.

Stores the policy on ``tenant_settings.retention_days`` and provides a
purge function that hard-deletes classifications older than the
configured window, scoped strictly to a single tenant per call so
cross-tenant data is never touched by another tenant's policy.

Design notes:

* ``retention_days = None`` or ``<= 0`` keeps data indefinitely. New
  deployments and existing tenants stay opt-in.
* Maximum window is ``3650`` days (10 years) to bound input.
* Purge is performed in chunks of 500 to keep transaction size small.
* Blob files are unlinked best-effort, mirroring
  :meth:`Repository.delete_by_principal`.
* Returns the count actually removed plus the cutoff timestamp so the
  caller can emit an audit-grade log entry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from .db import ClassificationRow, TenantSettingsRow, get_session, init_db


MAX_RETENTION_DAYS = 3650
PURGE_CHUNK = 500


@dataclass(frozen=True)
class PurgeResult:
    tenant_id: str
    retention_days: int
    cutoff: datetime
    removed: int
    held: bool = False

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "retention_days": self.retention_days,
            "cutoff": self.cutoff.isoformat(),
            "removed": self.removed,
            "held": self.held,
        }


def _normalize_days(raw: object) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise ValueError("retention_days must be an integer, not a bool")
    if not isinstance(raw, int):
        try:
            raw = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"retention_days must be an integer: {raw!r}") from exc
    if raw < 0:
        raise ValueError("retention_days cannot be negative")
    if raw > MAX_RETENTION_DAYS:
        raise ValueError(
            f"retention_days cannot exceed {MAX_RETENTION_DAYS} (about 10 years)"
        )
    # 0 means "disabled"; store as NULL to be consistent.
    return raw or None


def get_retention_days(tenant_id: str) -> int | None:
    if not tenant_id:
        return None
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            return None
        days = row.retention_days
        if not days or days <= 0:
            return None
        return int(days)


def set_retention_days(
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
                retention_days=normalized,
                updated_at=now,
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.retention_days = normalized
            row.updated_at = now
            row.updated_by = updated_by
        s.commit()
    return normalized


def _storage_root() -> Path:
    from shotclassify_common import get_settings

    return Path(get_settings().storage_local_dir).resolve()


def purge_expired_for_tenant(
    tenant_id: str, *, now: datetime | None = None
) -> PurgeResult:
    """Hard-delete classifications older than the tenant's retention window.

    Returns a ``PurgeResult`` with the cutoff timestamp and row count.
    Returns ``removed=0`` when no policy is set; callers should treat that
    as a no-op rather than an error so the scheduled job can iterate every
    tenant unconditionally.

    Tenant scoping: the DELETE is gated on ``tenant_id == :tenant_id``;
    rows belonging to any other tenant cannot be touched by this call.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    # Legal hold short-circuit: when a workspace is on hold the retention
    # scheduler MUST NOT erase any of its rows, even ones outside the
    # window. We import lazily to avoid an import cycle in older callers.
    from .legal_holds import tenant_has_active_hold

    days = get_retention_days(tenant_id)
    now = now or datetime.now(UTC)
    if tenant_has_active_hold(tenant_id):
        return PurgeResult(
            tenant_id=tenant_id,
            retention_days=days or 0,
            cutoff=now,
            removed=0,
            held=True,
        )
    if not days:
        return PurgeResult(tenant_id=tenant_id, retention_days=0, cutoff=now, removed=0)
    cutoff = now - timedelta(days=days)
    init_db()
    storage_root = _storage_root()
    removed_total = 0
    while True:
        with get_session() as s:
            stmt = (
                select(ClassificationRow)
                .where(ClassificationRow.tenant_id == tenant_id)
                .where(ClassificationRow.created_at < cutoff)
                .limit(PURGE_CHUNK)
            )
            rows = list(s.execute(stmt).scalars())
            if not rows:
                break
            for row in rows:
                if row.image_path:
                    try:
                        p = Path(row.image_path).resolve()
                        if str(p).startswith(str(storage_root)) and p.exists():
                            p.unlink()
                    except OSError:
                        pass
                s.delete(row)
                removed_total += 1
            s.commit()
        if len(rows) < PURGE_CHUNK:
            break
    return PurgeResult(
        tenant_id=tenant_id,
        retention_days=days,
        cutoff=cutoff,
        removed=removed_total,
    )


def list_tenants_with_retention() -> list[str]:
    """Return the tenant_ids that have a positive retention policy set."""
    init_db()
    with get_session() as s:
        rows = s.execute(
            select(TenantSettingsRow.tenant_id).where(
                TenantSettingsRow.retention_days.is_not(None)
            )
        ).all()
    return [r[0] for r in rows if r[0]]


def purge_expired_all_tenants(*, now: datetime | None = None) -> list[PurgeResult]:
    """Run :func:`purge_expired_for_tenant` for every tenant with a policy."""
    out: list[PurgeResult] = []
    for tenant_id in list_tenants_with_retention():
        out.append(purge_expired_for_tenant(tenant_id, now=now))
    return out
