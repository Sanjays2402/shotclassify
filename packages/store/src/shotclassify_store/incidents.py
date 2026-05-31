"""Security incident registry + per-tenant notification subscriptions.

Enterprise procurement (master service agreements, DPAs, SOC2 CC7.4)
requires the vendor to (a) publish a verifiable history of security
incidents and (b) commit to a notification channel so customers can be
informed within the contractually agreed window.

This module owns both halves:

* ``INCIDENTS`` is a vendor-owned, append-only registry hardcoded in
  this file. Procurement teams can fetch it without credentials at
  ``GET /v1/trust/incidents`` the same way they'd download a status
  page or PDF.
* ``IncidentSubscriptionRow`` records each workspace's notification
  contacts. Every CRUD path strictly filters by ``tenant_id`` so one
  tenant cannot read or mutate another tenant's contacts.

Severity ordering: ``low < medium < high < critical``. A subscription
with ``severity_min=high`` is matched by incidents at high or critical
severity only.
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy import delete, select

from .db import IncidentSubscriptionRow, get_session


SEVERITY_RANK: dict[str, int] = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}
VALID_SEVERITIES = tuple(SEVERITY_RANK.keys())
VALID_STATUSES = ("investigating", "identified", "monitoring", "resolved")
VALID_CHANNELS = ("email", "webhook")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class IncidentSubscriptionError(ValueError):
    """Raised for validation failures on subscription input."""


@dataclass(frozen=True)
class Incident:
    id: str
    published_at: str  # ISO-8601 UTC string for stable JSON output
    severity: str
    status: str
    title: str
    summary: str
    affected_components: tuple[str, ...]
    advisory_url: str | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "published_at": self.published_at,
            "severity": self.severity,
            "status": self.status,
            "title": self.title,
            "summary": self.summary,
            "affected_components": list(self.affected_components),
            "advisory_url": self.advisory_url,
        }


# Vendor-owned, append-only registry. Newer first.
INCIDENTS: tuple[Incident, ...] = (
    Incident(
        id="SCI-2024-0001",
        published_at="2024-11-14T18:20:00Z",
        severity="low",
        status="resolved",
        title="Elevated 5xx rate on /v1/classify in us-west-2",
        summary=(
            "A bad deploy raised the 5xx rate on the classification "
            "endpoint to 1.2% for 14 minutes. No data was lost. Rolled "
            "back, postmortem complete, deploy gate added."
        ),
        affected_components=("api", "classify"),
        advisory_url=None,
    ),
)


def list_incidents() -> list[dict]:
    """Return the public incident registry as plain dicts."""
    return [i.to_dict() for i in INCIDENTS]


def get_incident(incident_id: str) -> Incident | None:
    for i in INCIDENTS:
        if i.id == incident_id:
            return i
    return None


@dataclass(frozen=True)
class Subscription:
    id: str
    tenant_id: str
    channel: str
    endpoint: str
    severity_min: str
    active: bool
    label: str | None
    created_by: str
    created_at: datetime
    last_notified_at: datetime | None
    last_incident_id: str | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "channel": self.channel,
            "endpoint": self.endpoint,
            "severity_min": self.severity_min,
            "active": self.active,
            "label": self.label,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "last_notified_at": self.last_notified_at.isoformat()
            if self.last_notified_at
            else None,
            "last_incident_id": self.last_incident_id,
        }


def _from_row(row: IncidentSubscriptionRow) -> Subscription:
    return Subscription(
        id=row.id,
        tenant_id=row.tenant_id,
        channel=row.channel,
        endpoint=row.endpoint,
        severity_min=row.severity_min,
        active=bool(row.active),
        label=row.label,
        created_by=row.created_by,
        created_at=row.created_at,
        last_notified_at=row.last_notified_at,
        last_incident_id=row.last_incident_id,
    )


def _validate_channel_endpoint(channel: str, endpoint: str) -> tuple[str, str]:
    channel = (channel or "").strip().lower()
    endpoint = (endpoint or "").strip()
    if channel not in VALID_CHANNELS:
        raise IncidentSubscriptionError(
            f"channel must be one of {VALID_CHANNELS}"
        )
    if not endpoint:
        raise IncidentSubscriptionError("endpoint is required")
    if len(endpoint) > 512:
        raise IncidentSubscriptionError("endpoint too long")
    if channel == "email":
        if not _EMAIL_RE.match(endpoint):
            raise IncidentSubscriptionError("endpoint must be a valid email")
    else:  # webhook
        parsed = urlparse(endpoint)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise IncidentSubscriptionError(
                "endpoint must be an http(s) URL for channel=webhook"
            )
    return channel, endpoint


def _validate_severity(severity: str) -> str:
    severity = (severity or "low").strip().lower()
    if severity not in SEVERITY_RANK:
        raise IncidentSubscriptionError(
            f"severity_min must be one of {VALID_SEVERITIES}"
        )
    return severity


def list_subscriptions(tenant_id: str) -> list[Subscription]:
    if not tenant_id:
        raise IncidentSubscriptionError("tenant_id is required")
    with get_session() as s:
        rows = s.execute(
            select(IncidentSubscriptionRow)
            .where(IncidentSubscriptionRow.tenant_id == tenant_id)
            .order_by(IncidentSubscriptionRow.created_at.desc())
        ).scalars().all()
        return [_from_row(r) for r in rows]


def get_subscription(tenant_id: str, sub_id: str) -> Subscription | None:
    if not tenant_id or not sub_id:
        return None
    with get_session() as s:
        row = s.execute(
            select(IncidentSubscriptionRow).where(
                IncidentSubscriptionRow.tenant_id == tenant_id,
                IncidentSubscriptionRow.id == sub_id,
            )
        ).scalar_one_or_none()
        return _from_row(row) if row else None


def create_subscription(
    *,
    tenant_id: str,
    channel: str,
    endpoint: str,
    severity_min: str = "low",
    label: str | None = None,
    created_by: str,
) -> Subscription:
    if not tenant_id:
        raise IncidentSubscriptionError("tenant_id is required")
    if not created_by:
        raise IncidentSubscriptionError("created_by is required")
    channel, endpoint = _validate_channel_endpoint(channel, endpoint)
    severity_min = _validate_severity(severity_min)
    label_clean = (label or None) and label.strip()[:128]
    new_id = "isub_" + secrets.token_urlsafe(12)
    row = IncidentSubscriptionRow(
        id=new_id,
        tenant_id=tenant_id,
        channel=channel,
        endpoint=endpoint,
        severity_min=severity_min,
        active=True,
        label=label_clean,
        created_by=created_by,
        created_at=datetime.now(UTC),
    )
    with get_session() as s:
        # Reject duplicate (channel, endpoint) per tenant to keep the
        # admin UI clean and prevent accidental double-notification.
        existing = s.execute(
            select(IncidentSubscriptionRow).where(
                IncidentSubscriptionRow.tenant_id == tenant_id,
                IncidentSubscriptionRow.channel == channel,
                IncidentSubscriptionRow.endpoint == endpoint,
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise IncidentSubscriptionError(
                "a subscription with that channel + endpoint already exists"
            )
        s.add(row)
        s.commit()
        s.refresh(row)
        return _from_row(row)


def update_subscription(
    *,
    tenant_id: str,
    sub_id: str,
    active: bool | None = None,
    severity_min: str | None = None,
    label: str | None = None,
) -> Subscription | None:
    if not tenant_id or not sub_id:
        return None
    with get_session() as s:
        row = s.execute(
            select(IncidentSubscriptionRow).where(
                IncidentSubscriptionRow.tenant_id == tenant_id,
                IncidentSubscriptionRow.id == sub_id,
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if active is not None:
            row.active = bool(active)
        if severity_min is not None:
            row.severity_min = _validate_severity(severity_min)
        if label is not None:
            row.label = label.strip()[:128] or None
        s.add(row)
        s.commit()
        s.refresh(row)
        return _from_row(row)


def delete_subscription(*, tenant_id: str, sub_id: str) -> bool:
    if not tenant_id or not sub_id:
        return False
    with get_session() as s:
        result = s.execute(
            delete(IncidentSubscriptionRow).where(
                IncidentSubscriptionRow.tenant_id == tenant_id,
                IncidentSubscriptionRow.id == sub_id,
            )
        )
        s.commit()
        return (result.rowcount or 0) > 0


def matches_incident(subscription: Subscription, incident: Incident) -> bool:
    """Whether ``subscription`` would receive ``incident``.

    Used by the future delivery worker and by the UI preview ("would
    notify N contacts"). Subscription must be active and the incident
    severity must be at or above the subscription threshold.
    """
    if not subscription.active:
        return False
    return SEVERITY_RANK[incident.severity] >= SEVERITY_RANK[
        subscription.severity_min
    ]


def matching_subscription_count(tenant_id: str, severity: str) -> int:
    """How many active subscriptions in ``tenant_id`` match ``severity``.

    Used by the admin UI to show 'this severity would notify N contacts'.
    """
    severity = _validate_severity(severity)
    with get_session() as s:
        rows = s.execute(
            select(IncidentSubscriptionRow).where(
                IncidentSubscriptionRow.tenant_id == tenant_id,
                IncidentSubscriptionRow.active == True,  # noqa: E712
            )
        ).scalars().all()
        return sum(
            1
            for r in rows
            if SEVERITY_RANK[severity] >= SEVERITY_RANK[r.severity_min]
        )
