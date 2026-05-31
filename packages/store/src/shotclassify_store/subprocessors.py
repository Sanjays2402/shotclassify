"""Sub-processor catalog and per-tenant acknowledgements (Trust Center).

Enterprise procurement teams require the vendor to publish the list of
third-party data processors (cloud, model, observability, billing,
support) and to obtain prior written notice + customer acknowledgement
when the list changes. This module owns:

* the *vendor-managed* catalog (read-only, defined in code so it ships
  with the binary and survives DB resets), and
* the *tenant-managed* acknowledgements: which catalog version the
  workspace owner accepted, by whom, when, from what IP.

The catalog version is a deterministic SHA-256 over the canonicalized
catalog body so any code change to a processor automatically re-arms the
unacknowledged banner; we never trust an operator to bump a string by
hand.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from .db import SubprocessorAckRow, get_session, init_db


@dataclass(frozen=True)
class Subprocessor:
    name: str
    purpose: str
    location: str
    data_categories: tuple[str, ...]
    website: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "purpose": self.purpose,
            "location": self.location,
            "data_categories": list(self.data_categories),
            "website": self.website,
        }


# Vendor-owned list. Edit this list to change the catalog; the version
# hash is recomputed automatically so every workspace re-acknowledges.
CATALOG: tuple[Subprocessor, ...] = (
    Subprocessor(
        name="Amazon Web Services",
        purpose="Compute, object storage, managed Postgres for application data.",
        location="us-west-2, eu-west-1 (per workspace data residency setting)",
        data_categories=("Account metadata", "Uploaded screenshots", "Classification results"),
        website="https://aws.amazon.com/compliance/",
    ),
    Subprocessor(
        name="OpenAI",
        purpose="Vision LLM inference for screenshot classification.",
        location="United States",
        data_categories=("Uploaded screenshots", "OCR-extracted text"),
        website="https://openai.com/enterprise-privacy",
    ),
    Subprocessor(
        name="Cloudflare",
        purpose="Edge TLS termination, DDoS mitigation, WAF.",
        location="Global (anycast)",
        data_categories=("IP address", "Request metadata"),
        website="https://www.cloudflare.com/trust-hub/",
    ),
    Subprocessor(
        name="Sentry",
        purpose="Application error tracking with PII scrubbing.",
        location="United States",
        data_categories=("Error stack traces", "Request id", "Sanitized request metadata"),
        website="https://sentry.io/trust/",
    ),
    Subprocessor(
        name="Stripe",
        purpose="Billing, invoicing, payment processing.",
        location="United States",
        data_categories=("Billing contact", "Payment method", "Workspace name"),
        website="https://stripe.com/privacy",
    ),
)


def _canonical_catalog(catalog: tuple[Subprocessor, ...]) -> str:
    return json.dumps(
        [sp.to_dict() for sp in catalog],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def catalog_version(catalog: tuple[Subprocessor, ...] = CATALOG) -> str:
    """Deterministic SHA-256 over the catalog body, first 16 hex chars."""
    body = _canonical_catalog(catalog).encode("utf-8")
    return hashlib.sha256(body).hexdigest()[:16]


def list_catalog() -> dict:
    return {
        "version": catalog_version(),
        "processors": [sp.to_dict() for sp in CATALOG],
        "count": len(CATALOG),
    }


@dataclass(frozen=True)
class Acknowledgement:
    tenant_id: str
    version: str
    acknowledged_by: str
    acknowledged_at: datetime
    acknowledged_ip: str | None
    user_agent: str | None

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "version": self.version,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at.isoformat(),
            "acknowledged_ip": self.acknowledged_ip,
            "user_agent": self.user_agent,
        }


def _row_to_ack(row: SubprocessorAckRow) -> Acknowledgement:
    return Acknowledgement(
        tenant_id=row.tenant_id,
        version=row.version,
        acknowledged_by=row.acknowledged_by,
        acknowledged_at=row.acknowledged_at,
        acknowledged_ip=row.acknowledged_ip,
        user_agent=row.user_agent,
    )


def get_ack(tenant_id: str) -> Acknowledgement | None:
    init_db()
    with get_session() as s:
        row = s.execute(
            select(SubprocessorAckRow).where(SubprocessorAckRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        return _row_to_ack(row) if row else None


MAX_ACTOR_LEN = 256
MAX_UA_LEN = 512
MAX_IP_LEN = 64


def acknowledge(
    tenant_id: str,
    version: str,
    *,
    acknowledged_by: str,
    acknowledged_ip: str | None = None,
    user_agent: str | None = None,
) -> Acknowledgement:
    """Record (or replace) the workspace acknowledgement for ``version``.

    Raises ``ValueError`` when the submitted version does not match the
    currently-published catalog so a stale browser tab cannot accept a
    list the buyer did not actually see.
    """
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id is required")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("version is required")
    if not isinstance(acknowledged_by, str) or not acknowledged_by.strip():
        raise ValueError("acknowledged_by is required")
    current = catalog_version()
    if version != current:
        raise ValueError(
            f"submitted catalog version {version!r} no longer current "
            f"(expected {current!r}); reload the page and review again"
        )
    actor = acknowledged_by.strip()[:MAX_ACTOR_LEN]
    ip = (acknowledged_ip or None)
    if ip is not None:
        ip = ip[:MAX_IP_LEN]
    ua = (user_agent or None)
    if ua is not None:
        ua = ua[:MAX_UA_LEN]
    init_db()
    now = datetime.now(UTC)
    with get_session() as s:
        existing = s.execute(
            select(SubprocessorAckRow).where(SubprocessorAckRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if existing is None:
            row = SubprocessorAckRow(
                tenant_id=tenant_id,
                version=version,
                acknowledged_by=actor,
                acknowledged_at=now,
                acknowledged_ip=ip,
                user_agent=ua,
            )
            s.add(row)
        else:
            existing.version = version
            existing.acknowledged_by = actor
            existing.acknowledged_at = now
            existing.acknowledged_ip = ip
            existing.user_agent = ua
            row = existing
        s.commit()
        s.refresh(row)
        return _row_to_ack(row)


def status_for(tenant_id: str) -> dict:
    """Combined view used by the settings page and API: catalog + ack state."""
    current = catalog_version()
    ack = get_ack(tenant_id)
    is_current = ack is not None and ack.version == current
    return {
        "catalog": list_catalog(),
        "acknowledgement": ack.to_dict() if ack else None,
        "acknowledged": is_current,
        "stale": ack is not None and not is_current,
    }
