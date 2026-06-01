"""Data Subject Access Requests (DSAR) -- GDPR Articles 12-22, CCPA 1798.

Enterprise procurement (especially in the EU and California) requires a
vendor to expose a documented, auditable workflow for handling requests
from the people whose data is processed, *whether or not* they have an
account with the vendor. This module owns the durable storage half:

* ``create_request`` ingests a new ticket (public or admin-filed). The
  request is bound to a target tenant from the very first row so cross
  tenant enumeration is impossible at the query layer.
* ``list_for_tenant`` / ``get`` are strictly tenant-scoped reads.
* ``transition`` mutates ``status`` along the lifecycle
  ``received -> verified -> fulfilled -> closed`` (with ``rejected`` as a
  terminal branch off any pre-fulfilled state).
* ``scan_subject_footprint`` enumerates the rows in this database that
  match the data subject.
* ``fulfill_access`` and ``fulfill_erasure`` perform the action and
  persist a structured ``fulfillment_summary`` for the audit trail.

Nothing in this module talks to HTTP; route handlers are responsible
for authn/authz/audit-middleware integration.
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select

from .db import (
    AuditLogRow,
    ClassificationRow,
    DataSubjectRequestRow,
    get_session,
)


VALID_REQUEST_TYPES: tuple[str, ...] = ("access", "erasure", "rectification")
VALID_STATUSES: tuple[str, ...] = (
    "received",
    "verified",
    "fulfilled",
    "rejected",
    "closed",
)
VALID_SUBMITTED_VIA: tuple[str, ...] = ("public", "admin")

# GDPR Article 12(3): respond within one month of receipt.
STATUTORY_DEADLINE_DAYS = 30

_ALLOWED: dict[str, frozenset[str]] = {
    "received": frozenset({"verified", "rejected"}),
    "verified": frozenset({"fulfilled", "rejected"}),
    "fulfilled": frozenset({"closed"}),
    "rejected": frozenset({"closed"}),
    "closed": frozenset(),
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class DsarValidationError(ValueError):
    """Raised for input validation failures."""


class DsarStateError(ValueError):
    """Raised when a requested transition is not allowed."""


class DsarNotFound(LookupError):
    """Raised when a ticket id does not exist *in this tenant*."""


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return "dsr_" + secrets.token_hex(8)


def _normalize_identifier(value: str) -> str:
    return value.strip().lower()


def _validate_email(value: str) -> str:
    v = value.strip()
    if not _EMAIL_RE.match(v):
        raise DsarValidationError("subject_email must be a valid email address.")
    return v


def _validate_type(value: str) -> str:
    if value not in VALID_REQUEST_TYPES:
        raise DsarValidationError(
            f"request_type must be one of {list(VALID_REQUEST_TYPES)}"
        )
    return value


def _validate_tenant(tenant_id: str | None) -> str:
    if not tenant_id or not isinstance(tenant_id, str):
        raise DsarValidationError("tenant_id is required.")
    return tenant_id


def _row_to_dict(row: DataSubjectRequestRow) -> dict[str, Any]:
    received = row.received_at
    if received.tzinfo is None:
        received = received.replace(tzinfo=UTC)
    deadline = received + timedelta(days=STATUTORY_DEADLINE_DAYS)
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "request_type": row.request_type,
        "subject_identifier": row.subject_identifier,
        "subject_email": row.subject_email,
        "subject_name": row.subject_name,
        "description": row.description,
        "submitted_via": row.submitted_via,
        "submitted_ip": row.submitted_ip,
        "status": row.status,
        "received_at": received.isoformat(),
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "fulfilled_at": row.fulfilled_at.isoformat() if row.fulfilled_at else None,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        "assigned_to": row.assigned_to,
        "resolution_note": row.resolution_note,
        "fulfillment_summary": row.fulfillment_summary,
        "state_history": list(row.state_history or []),
        "statutory_deadline": deadline.isoformat(),
        "overdue": (
            row.status not in ("fulfilled", "closed") and _now() > deadline
        ),
    }


def create_request(
    *,
    tenant_id: str,
    request_type: str,
    subject_email: str,
    subject_name: str | None = None,
    description: str | None = None,
    submitted_via: str = "public",
    submitted_ip: str | None = None,
    actor: str = "anonymous",
) -> dict[str, Any]:
    tenant_id = _validate_tenant(tenant_id)
    req_type = _validate_type(request_type)
    email = _validate_email(subject_email)
    if submitted_via not in VALID_SUBMITTED_VIA:
        raise DsarValidationError(
            f"submitted_via must be one of {list(VALID_SUBMITTED_VIA)}"
        )
    if description is not None and len(description) > 4000:
        raise DsarValidationError("description must be 4000 chars or fewer.")
    if subject_name is not None and len(subject_name) > 256:
        raise DsarValidationError("subject_name must be 256 chars or fewer.")
    rid = _new_id()
    now = _now()
    seed = [
        {
            "at": now.isoformat(),
            "actor": actor,
            "from": None,
            "to": "received",
            "note": f"Intake via {submitted_via}.",
        }
    ]
    row = DataSubjectRequestRow(
        id=rid,
        tenant_id=tenant_id,
        request_type=req_type,
        subject_identifier=_normalize_identifier(email),
        subject_email=email,
        subject_name=(subject_name.strip() if subject_name else None),
        description=description,
        submitted_via=submitted_via,
        submitted_ip=submitted_ip,
        status="received",
        received_at=now,
        state_history=seed,
    )
    with get_session() as s:
        s.add(row)
        s.commit()
        s.refresh(row)
        return _row_to_dict(row)


def list_for_tenant(
    tenant_id: str,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    tenant_id = _validate_tenant(tenant_id)
    limit = max(1, min(int(limit or 100), 500))
    stmt = (
        select(DataSubjectRequestRow)
        .where(DataSubjectRequestRow.tenant_id == tenant_id)
        .order_by(DataSubjectRequestRow.received_at.desc())
        .limit(limit)
    )
    if status:
        if status not in VALID_STATUSES:
            raise DsarValidationError(
                f"status must be one of {list(VALID_STATUSES)}"
            )
        stmt = stmt.where(DataSubjectRequestRow.status == status)
    with get_session() as s:
        rows = s.execute(stmt).scalars().all()
        return [_row_to_dict(r) for r in rows]


def get(tenant_id: str, request_id: str) -> dict[str, Any]:
    tenant_id = _validate_tenant(tenant_id)
    with get_session() as s:
        row = s.get(DataSubjectRequestRow, request_id)
        if row is None or row.tenant_id != tenant_id:
            raise DsarNotFound(request_id)
        return _row_to_dict(row)


def _load(s, tenant_id: str, request_id: str) -> DataSubjectRequestRow:
    row = s.get(DataSubjectRequestRow, request_id)
    if row is None or row.tenant_id != tenant_id:
        raise DsarNotFound(request_id)
    return row


def transition(
    *,
    tenant_id: str,
    request_id: str,
    to_status: str,
    actor: str,
    note: str | None = None,
    assigned_to: str | None = None,
) -> dict[str, Any]:
    tenant_id = _validate_tenant(tenant_id)
    if to_status not in VALID_STATUSES:
        raise DsarValidationError(
            f"to_status must be one of {list(VALID_STATUSES)}"
        )
    with get_session() as s:
        row = _load(s, tenant_id, request_id)
        if to_status not in _ALLOWED.get(row.status, frozenset()):
            raise DsarStateError(
                f"Cannot transition from {row.status!r} to {to_status!r}."
            )
        prev = row.status
        now = _now()
        row.status = to_status
        if to_status == "verified":
            row.verified_at = now
        elif to_status == "fulfilled":
            row.fulfilled_at = now
        elif to_status == "closed":
            row.closed_at = now
        elif to_status == "rejected":
            row.resolution_note = note or row.resolution_note
        if assigned_to is not None:
            row.assigned_to = assigned_to or None
        history = list(row.state_history or [])
        history.append(
            {
                "at": now.isoformat(),
                "actor": actor,
                "from": prev,
                "to": to_status,
                "note": note,
            }
        )
        row.state_history = history
        s.add(row)
        s.commit()
        s.refresh(row)
        return _row_to_dict(row)


@dataclass(frozen=True)
class FootprintMatch:
    table: str
    count: int
    sample_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "count": self.count,
            "sample_ids": list(self.sample_ids),
        }


def _matching_classifications(s, tenant_id: str, ident: str):
    return [
        r
        for r in s.execute(
            select(ClassificationRow)
            .where(ClassificationRow.tenant_id == tenant_id)
        ).scalars().all()
        if (r.principal or "").strip().lower() == ident
    ]


def _matching_audit(s, tenant_id: str, ident: str):
    return [
        r
        for r in s.execute(
            select(AuditLogRow).where(AuditLogRow.tenant_id == tenant_id)
        ).scalars().all()
        if (r.principal or "").strip().lower() == ident
    ]


def scan_subject_footprint(
    tenant_id: str, subject_identifier: str
) -> list[FootprintMatch]:
    tenant_id = _validate_tenant(tenant_id)
    ident = _normalize_identifier(subject_identifier)
    with get_session() as s:
        cls = _matching_classifications(s, tenant_id, ident)
        aud = _matching_audit(s, tenant_id, ident)
    return [
        FootprintMatch(
            table="classifications",
            count=len(cls),
            sample_ids=tuple(r.id for r in cls[:10]),
        ),
        FootprintMatch(
            table="audit_log",
            count=len(aud),
            sample_ids=tuple(r.id for r in aud[:10]),
        ),
    ]


def fulfill_access(
    *,
    tenant_id: str,
    request_id: str,
    actor: str,
) -> dict[str, Any]:
    tenant_id = _validate_tenant(tenant_id)
    with get_session() as s:
        row = _load(s, tenant_id, request_id)
        if row.status != "verified":
            raise DsarStateError(
                "Access fulfillment requires status=verified."
            )
        ident = row.subject_identifier
        cls = _matching_classifications(s, tenant_id, ident)
        aud = _matching_audit(s, tenant_id, ident)
        classifications = [
            {
                "id": r.id,
                "filename": r.filename,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "primary_category": r.primary_category,
                "confidence": r.confidence,
                "ocr_text": r.ocr_text,
                "label": r.label,
                "tags": list(r.tags or []),
            }
            for r in cls
        ]
        audit_entries = [
            {
                "id": r.id,
                "at": r.created_at.isoformat() if r.created_at else None,
                "method": r.method,
                "path": r.path,
                "status_code": r.status_code,
                "target_id": r.target_id,
                "client_ip": r.client_ip,
                "request_id": r.request_id,
            }
            for r in aud
        ]
        payload = {
            "tenant_id": tenant_id,
            "subject_identifier": ident,
            "subject_email": row.subject_email,
            "generated_at": _now().isoformat(),
            "classifications": classifications,
            "audit_log": audit_entries,
            "counts": {
                "classifications": len(classifications),
                "audit_log": len(audit_entries),
            },
        }
        summary = {
            "action": "access_export",
            "counts": payload["counts"],
            "generated_at": payload["generated_at"],
        }
        prev = row.status
        now = _now()
        row.status = "fulfilled"
        row.fulfilled_at = now
        row.fulfillment_summary = summary
        history = list(row.state_history or [])
        history.append(
            {
                "at": now.isoformat(),
                "actor": actor,
                "from": prev,
                "to": "fulfilled",
                "note": f"Access export generated: {summary['counts']} records.",
            }
        )
        row.state_history = history
        s.add(row)
        s.commit()
    return payload


def fulfill_erasure(
    *,
    tenant_id: str,
    request_id: str,
    actor: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Hard-delete subject classifications and close out the ticket.

    Audit-log rows are kept on purpose: GDPR Article 17(3)(b) and (e)
    permit retention of records required for legal claims and to comply
    with our own audit obligations.
    """
    tenant_id = _validate_tenant(tenant_id)
    with get_session() as s:
        row = _load(s, tenant_id, request_id)
        if row.status != "verified":
            raise DsarStateError(
                "Erasure fulfillment requires status=verified."
            )
        ident = row.subject_identifier
        targets = _matching_classifications(s, tenant_id, ident)
        retained = _matching_audit(s, tenant_id, ident)
        target_ids = [r.id for r in targets]
        summary = {
            "action": "erasure",
            "dry_run": bool(dry_run),
            "classifications_removed": len(target_ids),
            "audit_rows_retained": len(retained),
            "sample_removed_ids": target_ids[:10],
            "generated_at": _now().isoformat(),
        }
        if dry_run:
            return summary
        if target_ids:
            s.execute(
                delete(ClassificationRow)
                .where(ClassificationRow.tenant_id == tenant_id)
                .where(ClassificationRow.id.in_(target_ids))
            )
        prev = row.status
        now = _now()
        row.status = "fulfilled"
        row.fulfilled_at = now
        row.fulfillment_summary = summary
        history = list(row.state_history or [])
        history.append(
            {
                "at": now.isoformat(),
                "actor": actor,
                "from": prev,
                "to": "fulfilled",
                "note": (
                    f"Erasure executed: removed {len(target_ids)} "
                    f"classifications, retained {len(retained)} "
                    "audit rows under Article 17(3)(b)."
                ),
            }
        )
        row.state_history = history
        s.add(row)
        s.commit()
        return summary


def stats_for_tenant(tenant_id: str) -> dict[str, Any]:
    tenant_id = _validate_tenant(tenant_id)
    counts: dict[str, int] = {s: 0 for s in VALID_STATUSES}
    overdue = 0
    open_count = 0
    now = _now()
    deadline_window = timedelta(days=STATUTORY_DEADLINE_DAYS)
    with get_session() as s:
        rows = s.execute(
            select(DataSubjectRequestRow).where(
                DataSubjectRequestRow.tenant_id == tenant_id
            )
        ).scalars().all()
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
        if r.status not in ("fulfilled", "closed"):
            open_count += 1
            received = r.received_at
            if received and received.tzinfo is None:
                received = received.replace(tzinfo=UTC)
            if received and now > received + deadline_window:
                overdue += 1
    return {
        "tenant_id": tenant_id,
        "counts": counts,
        "open": open_count,
        "overdue": overdue,
        "statutory_deadline_days": STATUTORY_DEADLINE_DAYS,
    }
