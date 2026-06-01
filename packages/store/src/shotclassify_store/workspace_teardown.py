"""Per-workspace scheduled teardown with cooling-off period.

Enterprise procurement and GDPR Article 17 ("right to erasure") both
require a way for a workspace owner to delete the **entire** workspace,
not just per-subject DSARs or the partial purge in
``/v1/workspace/data``. SOC 2 CC6.5 also expects a documented,
auditable process for decommissioning a tenant.

A naive ``DELETE /workspace`` is too easy to misfire. This module
implements the boring control every enterprise security questionnaire
asks for:

1. ``schedule_teardown`` records an intent to destroy the workspace
   with a mandatory cooling-off period (default 7 days). The caller
   must repeat the workspace tenant id back as a confirmation phrase,
   identical to the GitHub / Stripe / AWS pattern for destructive
   admin actions.
2. ``cancel_teardown`` clears the schedule any time before execution.
3. ``execute_teardown`` is only allowed after the cool-off has
   elapsed and removes every tenant-scoped row across the database
   (classifications, audit log, saved views, sessions, memberships,
   invitations, API keys and their monthly usage, webhooks and
   deliveries, audit sinks, legal holds, subprocessor acks, legal
   acceptances, incident subscriptions, support access grants, auth
   failures and lockouts, access reviews, DSAR rows, API-key
   issuance requests, and the tenant settings row itself).

MFA credentials and recovery codes are intentionally NOT touched
because they are keyed by ``principal`` and shared across workspaces
(a user can belong to many tenants); wiping them would break the
user's other memberships. RBAC + MFA enforcement live at the route
layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from .db import (
    AccessReviewItemRow,
    AccessReviewRow,
    ApiKeyIssuanceRequestRow,
    ApiKeyMonthlyUsageRow,
    ApiKeyRow,
    AuditLogRow,
    AuditSinkRow,
    AuthFailureRow,
    AuthLockoutRow,
    ClassificationRow,
    DataSubjectRequestRow,
    IncidentSubscriptionRow,
    InvitationRow,
    LegalAgreementAcceptanceRow,
    LegalEnforcementRow,
    LegalHoldRow,
    MembershipRow,
    SavedViewRow,
    SessionRow,
    SubprocessorAckRow,
    SupportAccessGrantRow,
    TenantSettingsRow,
    WebhookDeliveryRow,
    WebhookSubscriptionRow,
    get_session,
    init_db,
)

# Minimum cooling-off period. Operators can request longer, never shorter.
MIN_COOLOFF_HOURS = 1
DEFAULT_COOLOFF_HOURS = 24 * 7  # 7 days
MAX_COOLOFF_HOURS = 24 * 30  # 30 days


@dataclass(frozen=True)
class TeardownState:
    tenant_id: str
    scheduled: bool
    scheduled_at: Optional[datetime]
    scheduled_by: Optional[str]
    execute_after: Optional[datetime]
    reason: Optional[str]
    status: str  # "none" | "scheduled" | "executed"

    @property
    def ready_to_execute(self) -> bool:
        if not self.scheduled or self.execute_after is None:
            return False
        after = self.execute_after
        if after.tzinfo is None:
            after = after.replace(tzinfo=UTC)
        return datetime.now(UTC) >= after

    def _iso(self, dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.isoformat()

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "scheduled": self.scheduled,
            "scheduled_at": self._iso(self.scheduled_at),
            "scheduled_by": self.scheduled_by,
            "execute_after": self._iso(self.execute_after),
            "reason": self.reason,
            "status": self.status,
            "ready_to_execute": self.ready_to_execute,
        }


def _empty(tenant_id: str) -> TeardownState:
    return TeardownState(
        tenant_id=tenant_id,
        scheduled=False,
        scheduled_at=None,
        scheduled_by=None,
        execute_after=None,
        reason=None,
        status="none",
    )


def _from_row(row: TenantSettingsRow) -> TeardownState:
    if not row.teardown_scheduled_at:
        return _empty(row.tenant_id)
    return TeardownState(
        tenant_id=row.tenant_id,
        scheduled=True,
        scheduled_at=row.teardown_scheduled_at,
        scheduled_by=row.teardown_scheduled_by,
        execute_after=row.teardown_execute_after,
        reason=row.teardown_reason,
        status="scheduled",
    )


def get_teardown_state(tenant_id: str) -> TeardownState:
    if not tenant_id:
        return _empty("")
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(
                TenantSettingsRow.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
        if row is None or row.teardown_scheduled_at is None:
            return _empty(tenant_id)
        return _from_row(row)


def schedule_teardown(
    tenant_id: str,
    *,
    scheduled_by: str,
    cooloff_hours: int = DEFAULT_COOLOFF_HOURS,
    reason: Optional[str] = None,
) -> TeardownState:
    """Record an intent to destroy ``tenant_id`` after a cooling-off period.

    Idempotent on the (tenant, scheduled_by) tuple: re-scheduling refreshes
    ``scheduled_at`` and ``execute_after`` so the owner can extend the
    window. Returns the new state.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    if not scheduled_by:
        raise ValueError("scheduled_by is required")
    cooloff = int(cooloff_hours)
    if cooloff < MIN_COOLOFF_HOURS or cooloff > MAX_COOLOFF_HOURS:
        raise ValueError(
            f"cooloff_hours must be between {MIN_COOLOFF_HOURS} and {MAX_COOLOFF_HOURS}"
        )
    if reason is not None:
        reason = " ".join(reason.split())
        if len(reason) > 256:
            raise ValueError("reason must be 256 characters or fewer")
    init_db()
    now = datetime.now(UTC)
    execute_after = now + timedelta(hours=cooloff)
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(
                TenantSettingsRow.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
        if row is None:
            row = TenantSettingsRow(tenant_id=tenant_id)
            s.add(row)
        row.teardown_scheduled_at = now
        row.teardown_scheduled_by = scheduled_by
        row.teardown_execute_after = execute_after
        row.teardown_reason = reason or None
        row.updated_at = now
        row.updated_by = scheduled_by
        s.commit()
        s.refresh(row)
        return _from_row(row)


def cancel_teardown(tenant_id: str, *, cancelled_by: str) -> TeardownState:
    """Clear a pending teardown. No-op if nothing scheduled."""
    if not tenant_id:
        raise ValueError("tenant_id is required")
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(
                TenantSettingsRow.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
        if row is None or row.teardown_scheduled_at is None:
            return _empty(tenant_id)
        row.teardown_scheduled_at = None
        row.teardown_scheduled_by = None
        row.teardown_execute_after = None
        row.teardown_reason = None
        row.updated_at = datetime.now(UTC)
        row.updated_by = cancelled_by
        s.commit()
    return _empty(tenant_id)


_TENANT_SCOPED_TABLES = (
    ClassificationRow,
    SavedViewRow,
    SessionRow,
    InvitationRow,
    MembershipRow,
    WebhookDeliveryRow,
    WebhookSubscriptionRow,
    AuditSinkRow,
    LegalHoldRow,
    LegalAgreementAcceptanceRow,
    LegalEnforcementRow,
    SubprocessorAckRow,
    SupportAccessGrantRow,
    AuthFailureRow,
    AuthLockoutRow,
    IncidentSubscriptionRow,
    DataSubjectRequestRow,
    ApiKeyIssuanceRequestRow,
    AccessReviewItemRow,
    AccessReviewRow,
    AuditLogRow,
)


def execute_teardown(tenant_id: str) -> dict:
    """Hard-delete every tenant-scoped row for ``tenant_id``.

    Caller MUST verify ``get_teardown_state(tenant_id).ready_to_execute``
    first; this function trusts that the route layer enforced the
    cool-off period, RBAC, MFA, and dry-run gating.

    Returns a dict of ``{table_name: rows_deleted}`` for the receipt the
    admin sees in the UI and the audit row that records the action.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    init_db()
    deleted: dict[str, int] = {}
    with get_session() as s:
        for model in _TENANT_SCOPED_TABLES:
            tenant_col = getattr(model, "tenant_id", None)
            if tenant_col is None:
                continue
            result = s.execute(
                sa_delete(model).where(tenant_col == tenant_id)
            )
            deleted[model.__tablename__] = int(result.rowcount or 0)
        # API key monthly usage rows are scoped via key_id -> api_keys.tenant_id.
        # Delete usage rows for this tenant's keys, then drop the keys.
        tenant_key_ids = [
            r.id
            for r in s.execute(
                select(ApiKeyRow).where(ApiKeyRow.tenant_id == tenant_id)
            )
            .scalars()
            .all()
        ]
        if tenant_key_ids:
            usage_result = s.execute(
                sa_delete(ApiKeyMonthlyUsageRow).where(
                    ApiKeyMonthlyUsageRow.key_id.in_(tenant_key_ids)
                )
            )
            deleted[ApiKeyMonthlyUsageRow.__tablename__] = int(
                usage_result.rowcount or 0
            )
        else:
            deleted[ApiKeyMonthlyUsageRow.__tablename__] = 0
        keys_result = s.execute(
            sa_delete(ApiKeyRow).where(ApiKeyRow.tenant_id == tenant_id)
        )
        deleted[ApiKeyRow.__tablename__] = int(keys_result.rowcount or 0)
        # Drop the tenant_settings row last so a subsequent
        # get_teardown_state() returns the empty default.
        result = s.execute(
            sa_delete(TenantSettingsRow).where(
                TenantSettingsRow.tenant_id == tenant_id
            )
        )
        deleted[TenantSettingsRow.__tablename__] = int(result.rowcount or 0)
        s.commit()
    return deleted


__all__ = [
    "DEFAULT_COOLOFF_HOURS",
    "MAX_COOLOFF_HOURS",
    "MIN_COOLOFF_HOURS",
    "TeardownState",
    "cancel_teardown",
    "execute_teardown",
    "get_teardown_state",
    "schedule_teardown",
]
