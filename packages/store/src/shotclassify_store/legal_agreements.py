"""Vendor-owned legal agreement catalog and per-tenant acceptance ledger.

Enterprise procurement requires the vendor to:

* publish the current Terms of Service, Data Processing Addendum, and
  Acceptable Use Policy in a stable place;
* prove who accepted which version, when, and from where; and
* (optionally) block mutating API traffic from a workspace whose Legal
  team has not yet accepted the current versions.

The catalog itself is *vendor-owned* and lives in code so it ships with
the binary and survives DB resets. Each agreement carries a body whose
SHA-256 (first 16 hex chars) is the deterministic version id. Editing
an agreement body therefore automatically re-arms the
"acceptance required" banner for every workspace; we never trust an
operator to bump a version string by hand.

Acceptances are stored append-only in ``legal_agreement_acceptances``.
The "current" view is the latest row per ``(tenant_id, agreement_id)``;
older rows remain visible to the workspace owner as a tamper-evident
ledger.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from .db import (
    LegalAgreementAcceptanceRow,
    LegalEnforcementRow,
    get_session,
    init_db,
)


# ---------------------------------------------------------------------------
# Vendor-owned catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Agreement:
    """A vendor-owned legal document.

    ``required`` agreements are the ones the enforcement gate checks.
    Optional documents (e.g. an SLA addendum) can still be tracked and
    accepted but do not block writes when missing.
    """

    id: str
    title: str
    summary: str
    body: str
    required: bool = True

    def version(self) -> str:
        h = hashlib.sha256(self.body.encode("utf-8")).hexdigest()
        return h[:16]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "version": self.version(),
            "required": self.required,
            "body": self.body,
        }


# NOTE: bodies are deliberately short, plain text, and review-ready.
# Editing any body bumps that agreement's version and re-arms the gate.
CATALOG: tuple[Agreement, ...] = (
    Agreement(
        id="tos",
        title="Terms of Service",
        summary=(
            "Master commercial terms governing use of the shotclassify "
            "API and dashboard."
        ),
        body=(
            "shotclassify Terms of Service (v1)\n\n"
            "1. The Service is provided by the vendor under a non-exclusive, "
            "non-transferable license for the Customer's internal business use.\n"
            "2. Customer is responsible for the lawfulness of content it submits "
            "for classification.\n"
            "3. The vendor will not use Customer Content to train shared models.\n"
            "4. Either party may terminate for material breach with thirty (30) "
            "days' written notice and an opportunity to cure.\n"
            "5. Liability is capped at fees paid in the trailing twelve months.\n"
            "6. Governing law: State of California, USA."
        ),
        required=True,
    ),
    Agreement(
        id="dpa",
        title="Data Processing Addendum",
        summary=(
            "GDPR Article 28 processor terms covering Customer Personal Data "
            "submitted to the Service."
        ),
        body=(
            "shotclassify Data Processing Addendum (v1)\n\n"
            "1. Roles: Customer is Controller; vendor is Processor for "
            "Customer Personal Data submitted to the Service.\n"
            "2. Processing instructions: vendor processes Personal Data only "
            "to provide the Service and as instructed in writing.\n"
            "3. Sub-processors: vendor maintains a public list under "
            "/v1/trust/subprocessors; Customer is notified before new "
            "sub-processors are engaged.\n"
            "4. Security: vendor maintains SOC2-style controls; data is "
            "encrypted in transit (TLS 1.2+) and at rest (AES-256).\n"
            "5. International transfers: governed by Standard Contractual "
            "Clauses where applicable.\n"
            "6. Breach notification: vendor notifies Customer without undue "
            "delay and no later than 72 hours after becoming aware of a "
            "Personal Data Breach.\n"
            "7. Deletion / return: on termination, Customer may export or "
            "request deletion of Personal Data within thirty (30) days."
        ),
        required=True,
    ),
    Agreement(
        id="aup",
        title="Acceptable Use Policy",
        summary=(
            "What Customer may not submit to the classification pipeline "
            "(CSAM, unlawful surveillance, etc.)."
        ),
        body=(
            "shotclassify Acceptable Use Policy (v1)\n\n"
            "Customer agrees not to submit content that:\n"
            "1. Constitutes Child Sexual Abuse Material (CSAM) under any "
            "jurisdiction.\n"
            "2. Was obtained through unlawful surveillance or in violation of "
            "applicable wiretap, biometric, or privacy laws.\n"
            "3. Is intended to facilitate harassment, doxxing, or stalking of "
            "an identifiable individual.\n"
            "4. Bypasses or attempts to bypass the Service's rate limits, "
            "authentication, or tenant isolation boundaries.\n"
            "Violations may result in immediate suspension of the offending "
            "workspace pending investigation."
        ),
        required=True,
    ),
)


def get_agreement(agreement_id: str) -> Agreement | None:
    for a in CATALOG:
        if a.id == agreement_id:
            return a
    return None


def list_catalog() -> dict:
    return {
        "agreements": [a.to_dict() for a in CATALOG],
        "required_ids": [a.id for a in CATALOG if a.required],
        "count": len(CATALOG),
    }


# ---------------------------------------------------------------------------
# Acceptance ledger (tenant-scoped, append-only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Acceptance:
    id: str
    tenant_id: str
    agreement_id: str
    version: str
    accepted_by: str
    accepted_at: datetime
    accepted_ip: str | None
    user_agent: str | None
    request_id: str | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "agreement_id": self.agreement_id,
            "version": self.version,
            "accepted_by": self.accepted_by,
            "accepted_at": self.accepted_at.isoformat(),
            "accepted_ip": self.accepted_ip,
            "user_agent": self.user_agent,
            "request_id": self.request_id,
        }


def _row_to_acceptance(row: LegalAgreementAcceptanceRow) -> Acceptance:
    return Acceptance(
        id=row.id,
        tenant_id=row.tenant_id,
        agreement_id=row.agreement_id,
        version=row.version,
        accepted_by=row.accepted_by,
        accepted_at=row.accepted_at,
        accepted_ip=row.accepted_ip,
        user_agent=row.user_agent,
        request_id=row.request_id,
    )


MAX_ACTOR_LEN = 256
MAX_UA_LEN = 512
MAX_IP_LEN = 64
MAX_RID_LEN = 64


def list_ledger(tenant_id: str, *, limit: int = 200) -> list[Acceptance]:
    """All acceptances for the tenant, newest first. Strictly tenant-scoped."""
    if not tenant_id:
        raise ValueError("tenant_id is required")
    init_db()
    with get_session() as s:
        rows = (
            s.execute(
                select(LegalAgreementAcceptanceRow)
                .where(LegalAgreementAcceptanceRow.tenant_id == tenant_id)
                .order_by(LegalAgreementAcceptanceRow.accepted_at.desc())
                .limit(max(1, min(limit, 1000)))
            )
            .scalars()
            .all()
        )
        return [_row_to_acceptance(r) for r in rows]


def latest_per_agreement(tenant_id: str) -> dict[str, Acceptance]:
    """Latest acceptance per agreement_id for the given tenant."""
    out: dict[str, Acceptance] = {}
    for a in list_ledger(tenant_id, limit=1000):
        # ledger is newest-first; first hit per agreement_id wins
        if a.agreement_id not in out:
            out[a.agreement_id] = a
    return out


def accept(
    tenant_id: str,
    agreement_id: str,
    version: str,
    *,
    accepted_by: str,
    accepted_ip: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> Acceptance:
    """Append an acceptance row. Raises ``ValueError`` on stale version."""
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id is required")
    agreement = get_agreement(agreement_id)
    if agreement is None:
        raise ValueError(f"unknown agreement id {agreement_id!r}")
    current = agreement.version()
    if version != current:
        raise ValueError(
            f"submitted version {version!r} for {agreement_id!r} is no longer "
            f"current (expected {current!r}); reload the page and review again"
        )
    if not isinstance(accepted_by, str) or not accepted_by.strip():
        raise ValueError("accepted_by is required")
    actor = accepted_by.strip()[:MAX_ACTOR_LEN]
    ip = (accepted_ip or None)
    if ip is not None:
        ip = ip[:MAX_IP_LEN]
    ua = (user_agent or None)
    if ua is not None:
        ua = ua[:MAX_UA_LEN]
    rid = (request_id or None)
    if rid is not None:
        rid = rid[:MAX_RID_LEN]
    init_db()
    now = datetime.now(UTC)
    row = LegalAgreementAcceptanceRow(
        id=secrets.token_hex(12),
        tenant_id=tenant_id.strip(),
        agreement_id=agreement_id,
        version=version,
        accepted_by=actor,
        accepted_at=now,
        accepted_ip=ip,
        user_agent=ua,
        request_id=rid,
    )
    with get_session() as s:
        s.add(row)
        s.commit()
        s.refresh(row)
        return _row_to_acceptance(row)


# ---------------------------------------------------------------------------
# Per-tenant enforcement toggle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnforcementPolicy:
    tenant_id: str
    enforce: bool
    updated_by: str | None
    updated_at: datetime | None

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "enforce": self.enforce,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


def get_enforcement(tenant_id: str) -> EnforcementPolicy:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    init_db()
    with get_session() as s:
        row = s.execute(
            select(LegalEnforcementRow).where(
                LegalEnforcementRow.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
        if row is None:
            return EnforcementPolicy(
                tenant_id=tenant_id,
                enforce=False,
                updated_by=None,
                updated_at=None,
            )
        return EnforcementPolicy(
            tenant_id=row.tenant_id,
            enforce=bool(row.enforce),
            updated_by=row.updated_by,
            updated_at=row.updated_at,
        )


def set_enforcement(
    tenant_id: str, *, enforce: bool, updated_by: str
) -> EnforcementPolicy:
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id is required")
    if not isinstance(updated_by, str) or not updated_by.strip():
        raise ValueError("updated_by is required")
    init_db()
    now = datetime.now(UTC)
    actor = updated_by.strip()[:MAX_ACTOR_LEN]
    with get_session() as s:
        existing = s.execute(
            select(LegalEnforcementRow).where(
                LegalEnforcementRow.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
        if existing is None:
            row = LegalEnforcementRow(
                tenant_id=tenant_id.strip(),
                enforce=bool(enforce),
                updated_by=actor,
                updated_at=now,
            )
            s.add(row)
        else:
            existing.enforce = bool(enforce)
            existing.updated_by = actor
            existing.updated_at = now
            row = existing
        s.commit()
        s.refresh(row)
        return EnforcementPolicy(
            tenant_id=row.tenant_id,
            enforce=bool(row.enforce),
            updated_by=row.updated_by,
            updated_at=row.updated_at,
        )


# ---------------------------------------------------------------------------
# Combined status (used by route + middleware gate)
# ---------------------------------------------------------------------------


def status_for(tenant_id: str) -> dict:
    """Catalog + per-agreement acceptance state + enforcement flag.

    Shape consumed by both the admin UI and the enforcement middleware.
    """
    latest = latest_per_agreement(tenant_id)
    enforcement = get_enforcement(tenant_id)
    items = []
    missing_required: list[str] = []
    for a in CATALOG:
        current_version = a.version()
        ack = latest.get(a.id)
        accepted = ack is not None and ack.version == current_version
        stale = ack is not None and ack.version != current_version
        items.append(
            {
                "id": a.id,
                "title": a.title,
                "summary": a.summary,
                "required": a.required,
                "current_version": current_version,
                "accepted": accepted,
                "stale": stale,
                "latest_acceptance": ack.to_dict() if ack else None,
            }
        )
        if a.required and not accepted:
            missing_required.append(a.id)
    return {
        "tenant_id": tenant_id,
        "enforcement": enforcement.to_dict(),
        "agreements": items,
        "missing_required": missing_required,
        "all_required_accepted": len(missing_required) == 0,
    }


def gate_blocks(tenant_id: str) -> list[str] | None:
    """Return the list of missing required agreement ids when the gate is
    active and acceptances are missing, otherwise ``None``.

    The middleware calls this on every mutating ``/v1`` request. Keep it
    cheap; we already cap ledger reads and the table is per-tenant.
    """
    enforcement = get_enforcement(tenant_id)
    if not enforcement.enforce:
        return None
    latest = latest_per_agreement(tenant_id)
    missing: list[str] = []
    for a in CATALOG:
        if not a.required:
            continue
        ack = latest.get(a.id)
        if ack is None or ack.version != a.version():
            missing.append(a.id)
    return missing or None
