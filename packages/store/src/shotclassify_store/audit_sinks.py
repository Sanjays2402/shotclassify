"""Per-tenant audit log SIEM sinks.

Workspace owners register HTTPS endpoints here; the AuditLogMiddleware
fires every persisted audit row at the active sinks for that tenant
with an HMAC-SHA256 signature so the receiving SIEM can verify
authenticity.

Everything is tenant-scoped at the query layer (cross-tenant reads are
impossible). Dispatch is best-effort: a slow or broken SIEM endpoint
must never block, fail, or rewrite an authenticated request, so the
dispatcher hands work to a small background thread pool with a hard
per-attempt timeout and records the outcome (last_status, last_error,
success_count, failure_count) on the sink row.

Signature scheme mirrors webhooks:
    sig = HMAC-SHA256(sha256(secret_plaintext), body_bytes)
sent in the ``X-Shotclassify-Audit-Signature`` header. Receivers verify
by recomputing the same HMAC against the raw body.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import desc, select

from .db import AuditSinkRow, get_session, init_db
from .webhook_egress import EgressBlocked, safe_post

log = logging.getLogger(__name__)

_DISPATCH_POOL: ThreadPoolExecutor | None = None
_DISPATCH_LOCK = threading.Lock()
_DELIVERY_TIMEOUT_SECONDS = 5.0


def _pool() -> ThreadPoolExecutor:
    global _DISPATCH_POOL
    with _DISPATCH_LOCK:
        if _DISPATCH_POOL is None:
            _DISPATCH_POOL = ThreadPoolExecutor(
                max_workers=4, thread_name_prefix="audit-sink"
            )
        return _DISPATCH_POOL


@dataclass(frozen=True)
class SinkRecord:
    id: str
    tenant_id: str
    url: str
    description: str | None
    active: bool
    created_at: datetime | None
    created_by: str | None
    revoked_at: datetime | None
    last_delivery_at: datetime | None
    last_status: str | None
    last_error: str | None
    success_count: int
    failure_count: int

    @classmethod
    def from_row(cls, row: AuditSinkRow) -> "SinkRecord":
        return cls(
            id=row.id,
            tenant_id=row.tenant_id,
            url=row.url,
            description=row.description,
            active=row.active,
            created_at=row.created_at,
            created_by=row.created_by,
            revoked_at=row.revoked_at,
            last_delivery_at=row.last_delivery_at,
            last_status=row.last_status,
            last_error=row.last_error,
            success_count=row.success_count,
            failure_count=row.failure_count,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "url": self.url,
            "description": self.description,
            "active": self.active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "created_by": self.created_by,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "last_delivery_at": (
                self.last_delivery_at.isoformat() if self.last_delivery_at else None
            ),
            "last_status": self.last_status,
            "last_error": self.last_error,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
        }


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _new_id() -> str:
    return f"as_{secrets.token_urlsafe(12)}"


def _validate_url_format(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ValueError("url is required.")
    if len(url) > 1024:
        raise ValueError("url is too long.")
    if not (url.startswith("https://") or url.startswith("http://")):
        raise ValueError("url must start with http:// or https://")
    return url


def create_sink(
    *,
    tenant_id: str,
    url: str,
    description: str | None,
    created_by: str | None,
) -> tuple[SinkRecord, str]:
    """Create a sink. Returns (record, plaintext_secret) shown once."""
    init_db()
    if not tenant_id:
        raise ValueError("tenant_id is required.")
    url = _validate_url_format(url)
    secret = f"assec_{secrets.token_urlsafe(32)}"
    row = AuditSinkRow(
        id=_new_id(),
        tenant_id=tenant_id,
        url=url,
        description=(description or "").strip()[:255] or None,
        secret_hash=_hash_secret(secret),
        active=True,
        created_by=created_by,
    )
    session = get_session()
    try:
        session.add(row)
        session.commit()
        session.refresh(row)
        return SinkRecord.from_row(row), secret
    finally:
        session.close()


def list_sinks(tenant_id: str) -> list[SinkRecord]:
    init_db()
    if not tenant_id:
        return []
    session = get_session()
    try:
        rows = (
            session.execute(
                select(AuditSinkRow)
                .where(AuditSinkRow.tenant_id == tenant_id)
                .order_by(desc(AuditSinkRow.created_at))
            )
            .scalars()
            .all()
        )
        return [SinkRecord.from_row(r) for r in rows]
    finally:
        session.close()


def get_sink(sink_id: str, *, tenant_id: str) -> SinkRecord | None:
    init_db()
    if not tenant_id or not sink_id:
        return None
    session = get_session()
    try:
        row = (
            session.execute(
                select(AuditSinkRow).where(
                    AuditSinkRow.id == sink_id,
                    AuditSinkRow.tenant_id == tenant_id,
                )
            )
            .scalars()
            .first()
        )
        return SinkRecord.from_row(row) if row else None
    finally:
        session.close()


def revoke_sink(sink_id: str, *, tenant_id: str) -> bool:
    init_db()
    session = get_session()
    try:
        row = (
            session.execute(
                select(AuditSinkRow).where(
                    AuditSinkRow.id == sink_id,
                    AuditSinkRow.tenant_id == tenant_id,
                )
            )
            .scalars()
            .first()
        )
        if not row:
            return False
        row.active = False
        row.revoked_at = datetime.now(UTC)
        session.commit()
        return True
    finally:
        session.close()


def _record_outcome(
    sink_id: str,
    *,
    tenant_id: str,
    success: bool,
    status_text: str,
    error: str | None,
) -> None:
    session = get_session()
    try:
        row = (
            session.execute(
                select(AuditSinkRow).where(
                    AuditSinkRow.id == sink_id,
                    AuditSinkRow.tenant_id == tenant_id,
                )
            )
            .scalars()
            .first()
        )
        if not row:
            return
        row.last_delivery_at = datetime.now(UTC)
        row.last_status = status_text[:16]
        row.last_error = (error or None) and error[:512]
        if success:
            row.success_count = (row.success_count or 0) + 1
        else:
            row.failure_count = (row.failure_count or 0) + 1
        session.commit()
    finally:
        session.close()


def _sign(secret_hash: str, body: bytes) -> str:
    return hmac.new(secret_hash.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _deliver_one(
    *,
    sink_id: str,
    tenant_id: str,
    url: str,
    secret_hash: str,
    body: bytes,
    allow_http: bool,
    allow_private: bool,
    extra_blocked_cidrs: str,
) -> None:
    signature = _sign(secret_hash, body)
    headers = {
        "content-type": "application/json",
        "user-agent": "shotclassify-audit-sink/1",
        "x-shotclassify-audit-signature": signature,
        "x-shotclassify-audit-sink-id": sink_id,
    }
    try:
        resp = safe_post(
            url,
            content=body,
            headers=headers,
            timeout=_DELIVERY_TIMEOUT_SECONDS,
            allow_http=allow_http,
            allow_private=allow_private,
            extra_blocked_cidrs=extra_blocked_cidrs,
        )
        ok = 200 <= resp.status_code < 300
        _record_outcome(
            sink_id,
            tenant_id=tenant_id,
            success=ok,
            status_text=str(resp.status_code),
            error=None if ok else f"http {resp.status_code}",
        )
    except EgressBlocked as exc:
        _record_outcome(
            sink_id,
            tenant_id=tenant_id,
            success=False,
            status_text="blocked",
            error=str(exc),
        )
    except httpx.HTTPError as exc:
        _record_outcome(
            sink_id,
            tenant_id=tenant_id,
            success=False,
            status_text="error",
            error=str(exc)[:512],
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("audit sink delivery crashed: %s", exc)
        _record_outcome(
            sink_id,
            tenant_id=tenant_id,
            success=False,
            status_text="error",
            error=str(exc)[:512],
        )


def dispatch_event(
    tenant_id: str | None,
    event: dict[str, Any],
    *,
    allow_http: bool = False,
    allow_private: bool = False,
    extra_blocked_cidrs: str = "",
    sync: bool = False,
) -> int:
    """Fan out one audit event to every active sink for ``tenant_id``.

    Returns the number of sinks the event was queued for. Delivery is
    best-effort and runs on a background pool unless ``sync=True``
    (used by tests and the synchronous ``test_fire`` endpoint).
    """
    if not tenant_id:
        return 0
    try:
        init_db()
    except Exception:  # pragma: no cover - storage misconfig
        return 0
    session = get_session()
    try:
        rows = (
            session.execute(
                select(AuditSinkRow).where(
                    AuditSinkRow.tenant_id == tenant_id,
                    AuditSinkRow.active.is_(True),
                )
            )
            .scalars()
            .all()
        )
        targets = [
            (r.id, r.tenant_id, r.url, r.secret_hash) for r in rows
        ]
    finally:
        session.close()
    if not targets:
        return 0
    try:
        body = json.dumps(event, separators=(",", ":"), default=str).encode("utf-8")
    except Exception:
        return 0
    for sink_id, t_id, url, secret_hash in targets:
        kwargs = dict(
            sink_id=sink_id,
            tenant_id=t_id,
            url=url,
            secret_hash=secret_hash,
            body=body,
            allow_http=allow_http,
            allow_private=allow_private,
            extra_blocked_cidrs=extra_blocked_cidrs,
        )
        if sync:
            _deliver_one(**kwargs)
        else:
            try:
                _pool().submit(_deliver_one, **kwargs)
            except Exception:  # pragma: no cover - pool shutdown race
                _deliver_one(**kwargs)
    return len(targets)


def test_fire(
    sink_id: str,
    *,
    tenant_id: str,
    allow_http: bool = False,
    allow_private: bool = False,
    extra_blocked_cidrs: str = "",
) -> SinkRecord | None:
    """Synchronously send a probe event to one sink and return its updated record."""
    init_db()
    sink = get_sink(sink_id, tenant_id=tenant_id)
    if not sink or not sink.active:
        return sink
    session = get_session()
    try:
        row = (
            session.execute(
                select(AuditSinkRow).where(AuditSinkRow.id == sink_id)
            )
            .scalars()
            .first()
        )
        secret_hash = row.secret_hash if row else None
    finally:
        session.close()
    if not secret_hash:
        return sink
    event = {
        "type": "shotclassify.audit.test",
        "sink_id": sink_id,
        "tenant_id": tenant_id,
        "sent_at": datetime.now(UTC).isoformat(),
    }
    body = json.dumps(event, separators=(",", ":")).encode("utf-8")
    _deliver_one(
        sink_id=sink_id,
        tenant_id=tenant_id,
        url=sink.url,
        secret_hash=secret_hash,
        body=body,
        allow_http=allow_http,
        allow_private=allow_private,
        extra_blocked_cidrs=extra_blocked_cidrs,
    )
    return get_sink(sink_id, tenant_id=tenant_id)
