"""Tenant-scoped CRUD + dispatch helpers for outbound webhooks.

Every read/write here requires an explicit ``tenant_id``; the call sites
get it from ``request.state.tenant_id`` which is set by
``TenantResolutionMiddleware``. There is intentionally no
"admin reads across tenants" helper - the API service must never leak
one workspace's integrations to another.

The dispatcher signs payloads with HMAC-SHA256 over the raw JSON body
using a per-subscription key derived from the stored secret. Failures
back off exponentially (1s, 4s, 16s, 64s) up to four attempts before
being marked permanent. Every attempt - success, retry, or terminal
failure - is recorded in ``webhook_deliveries`` for the admin replay UI.

Signature scheme:
* On create, we return a plaintext ``whsec_...`` secret exactly once.
* The DB stores ``secret_hash = sha256(secret_hex)``.
* The dispatcher signs payloads with HMAC-SHA256 using ``secret_hash``
  as the HMAC key. Receivers re-derive the same key by hashing the
  plaintext secret they were shown at create time. This means a DB
  breach gives an attacker the ability to verify signatures but NOT the
  ability to send new signed payloads from a different endpoint.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx  # noqa: F401  # re-exported for backwards compat

from shotclassify_common import get_settings
from .webhook_egress import EgressBlocked, safe_post, validate_target
import structlog
from sqlalchemy import desc, select

from .db import WebhookDeliveryRow, WebhookSubscriptionRow, get_session, init_db

log = structlog.get_logger(__name__)

MAX_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 1
BACKOFF_MULTIPLIER = 4
DELIVERY_TIMEOUT_SECONDS = 8.0
MAX_PAYLOAD_PREVIEW = 512
ALLOWED_EVENTS = ("classify.completed", "classify.failed", "*")


@dataclass
class SubscriptionRecord:
    id: str
    tenant_id: str
    url: str
    description: str | None
    events: list[str]
    active: bool
    created_at: datetime
    created_by: str | None
    revoked_at: datetime | None
    last_delivery_at: datetime | None
    success_count: int
    failure_count: int
    secret_rotation_pending: bool = False
    secret_rotated_at: datetime | None = None

    @classmethod
    def from_row(cls, row: WebhookSubscriptionRow) -> "SubscriptionRecord":
        return cls(
            id=row.id,
            tenant_id=row.tenant_id,
            url=row.url,
            description=row.description,
            events=list(row.events or []),
            active=bool(row.active and row.revoked_at is None),
            created_at=row.created_at,
            created_by=row.created_by,
            revoked_at=row.revoked_at,
            last_delivery_at=row.last_delivery_at,
            success_count=int(row.success_count or 0),
            failure_count=int(row.failure_count or 0),
            secret_rotation_pending=bool(
                getattr(row, "secret_hash_next", None)
            ),
            secret_rotated_at=getattr(row, "secret_rotated_at", None),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "url": self.url,
            "description": self.description,
            "events": self.events,
            "active": self.active,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "last_delivery_at": (
                self.last_delivery_at.isoformat() if self.last_delivery_at else None
            ),
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "secret_rotation_pending": self.secret_rotation_pending,
            "secret_rotated_at": (
                self.secret_rotated_at.isoformat()
                if self.secret_rotated_at
                else None
            ),
        }


@dataclass
class DeliveryRecord:
    id: str
    tenant_id: str
    subscription_id: str
    event: str
    url: str
    status: str
    attempt: int
    http_status: int | None
    error: str | None
    latency_ms: int | None
    payload_preview: str
    signature: str | None
    request_id: str | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: WebhookDeliveryRow) -> "DeliveryRecord":
        return cls(
            id=row.id,
            tenant_id=row.tenant_id,
            subscription_id=row.subscription_id,
            event=row.event,
            url=row.url,
            status=row.status,
            attempt=int(row.attempt or 1),
            http_status=row.http_status,
            error=row.error,
            latency_ms=row.latency_ms,
            payload_preview=row.payload_preview or "",
            signature=row.signature,
            request_id=row.request_id,
            created_at=row.created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "subscription_id": self.subscription_id,
            "event": self.event,
            "url": self.url,
            "status": self.status,
            "attempt": self.attempt,
            "http_status": self.http_status,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "payload_preview": self.payload_preview,
            "signature": self.signature,
            "request_id": self.request_id,
            "created_at": self.created_at.isoformat(),
        }


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def validate_url(url: str) -> str:
    """Validate a tenant-supplied webhook URL.

    Rejects SSRF-prone targets at subscription create time so tenants
    get an immediate, actionable 400 instead of silent delivery failures
    in the audit log. The dispatcher re-validates at delivery time too
    (DNS records can change between create and fire).
    """
    s = get_settings()
    try:
        validate_target(
            url,
            allow_http=s.webhook_egress_allow_http,
            allow_private=s.webhook_egress_allow_private,
            extra_blocked_cidrs=s.webhook_egress_extra_blocked_cidrs,
        )
    except EgressBlocked as exc:
        raise ValueError(f"URL rejected: {exc}") from exc
    return url


def validate_events(events: list[str]) -> list[str]:
    cleaned = [e.strip() for e in (events or []) if isinstance(e, str) and e.strip()]
    if not cleaned:
        raise ValueError("At least one event is required.")
    bad = [e for e in cleaned if e not in ALLOWED_EVENTS]
    if bad:
        raise ValueError(f"Unknown event(s): {', '.join(bad)}")
    seen: set[str] = set()
    out: list[str] = []
    for e in cleaned:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def create_subscription(
    *,
    tenant_id: str,
    url: str,
    events: list[str],
    description: str | None,
    created_by: str | None,
) -> tuple[SubscriptionRecord, str]:
    """Create a subscription and return (record, plaintext_secret)."""
    init_db()
    if not tenant_id:
        raise ValueError("tenant_id is required.")
    url = validate_url(url)
    events = validate_events(events)
    secret = f"whsec_{secrets.token_urlsafe(32)}"
    row = WebhookSubscriptionRow(
        id=_new_id("wh"),
        tenant_id=tenant_id,
        url=url,
        description=(description or "").strip()[:255] or None,
        secret_hash=hash_secret(secret),
        events=events,
        active=True,
        created_by=created_by,
    )
    session = get_session()
    try:
        session.add(row)
        session.commit()
        session.refresh(row)
        return SubscriptionRecord.from_row(row), secret
    finally:
        session.close()


def list_subscriptions(tenant_id: str) -> list[SubscriptionRecord]:
    init_db()
    if not tenant_id:
        return []
    session = get_session()
    try:
        rows = (
            session.execute(
                select(WebhookSubscriptionRow)
                .where(WebhookSubscriptionRow.tenant_id == tenant_id)
                .order_by(desc(WebhookSubscriptionRow.created_at))
            )
            .scalars()
            .all()
        )
        return [SubscriptionRecord.from_row(r) for r in rows]
    finally:
        session.close()


def get_subscription(
    subscription_id: str, *, tenant_id: str
) -> SubscriptionRecord | None:
    init_db()
    if not tenant_id or not subscription_id:
        return None
    session = get_session()
    try:
        row = (
            session.execute(
                select(WebhookSubscriptionRow).where(
                    WebhookSubscriptionRow.id == subscription_id,
                    WebhookSubscriptionRow.tenant_id == tenant_id,
                )
            )
            .scalars()
            .first()
        )
        return SubscriptionRecord.from_row(row) if row else None
    finally:
        session.close()


def revoke_subscription(subscription_id: str, *, tenant_id: str) -> bool:
    init_db()
    session = get_session()
    try:
        row = (
            session.execute(
                select(WebhookSubscriptionRow).where(
                    WebhookSubscriptionRow.id == subscription_id,
                    WebhookSubscriptionRow.tenant_id == tenant_id,
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


def list_deliveries(
    *,
    tenant_id: str,
    subscription_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[DeliveryRecord]:
    init_db()
    if not tenant_id:
        return []
    limit = max(1, min(int(limit or 100), 500))
    session = get_session()
    try:
        stmt = select(WebhookDeliveryRow).where(
            WebhookDeliveryRow.tenant_id == tenant_id
        )
        if subscription_id:
            stmt = stmt.where(WebhookDeliveryRow.subscription_id == subscription_id)
        if status:
            stmt = stmt.where(WebhookDeliveryRow.status == status)
        stmt = stmt.order_by(desc(WebhookDeliveryRow.created_at)).limit(limit)
        rows = session.execute(stmt).scalars().all()
        return [DeliveryRecord.from_row(r) for r in rows]
    finally:
        session.close()


def get_delivery(delivery_id: str, *, tenant_id: str) -> DeliveryRecord | None:
    init_db()
    session = get_session()
    try:
        row = (
            session.execute(
                select(WebhookDeliveryRow).where(
                    WebhookDeliveryRow.id == delivery_id,
                    WebhookDeliveryRow.tenant_id == tenant_id,
                )
            )
            .scalars()
            .first()
        )
        return DeliveryRecord.from_row(row) if row else None
    finally:
        session.close()


def sign_body(secret_hash: str, body: bytes) -> str:
    return (
        "sha256="
        + hmac.new(secret_hash.encode("utf-8"), body, hashlib.sha256).hexdigest()
    )


def _matches_event(sub_events: list[str], event: str) -> bool:
    if not sub_events:
        return False
    return "*" in sub_events or event in sub_events


def _record_delivery(
    *,
    tenant_id: str,
    subscription_id: str,
    event: str,
    url: str,
    status: str,
    attempt: int,
    http_status: int | None,
    error: str | None,
    latency_ms: int | None,
    payload_preview: str,
    signature: str | None,
    request_id: str | None,
) -> str:
    init_db()
    delivery_id = _new_id("whd")
    now = datetime.now(UTC)
    session = get_session()
    try:
        session.add(
            WebhookDeliveryRow(
                id=delivery_id,
                tenant_id=tenant_id,
                subscription_id=subscription_id,
                event=event,
                url=url,
                status=status,
                attempt=attempt,
                http_status=http_status,
                error=(error[:512] if error else None),
                latency_ms=latency_ms,
                payload_preview=payload_preview[:MAX_PAYLOAD_PREVIEW],
                signature=signature,
                request_id=request_id,
                created_at=now,
            )
        )
        sub = (
            session.execute(
                select(WebhookSubscriptionRow).where(
                    WebhookSubscriptionRow.id == subscription_id,
                    WebhookSubscriptionRow.tenant_id == tenant_id,
                )
            )
            .scalars()
            .first()
        )
        if sub is not None:
            sub.last_delivery_at = now
            if status == "success":
                sub.success_count = int(sub.success_count or 0) + 1
            elif status == "failed":
                sub.failure_count = int(sub.failure_count or 0) + 1
        session.commit()
        return delivery_id
    finally:
        session.close()


def _post_with_retries(
    *,
    url: str,
    body: bytes,
    headers: dict[str, str],
    timeout: float = DELIVERY_TIMEOUT_SECONDS,
    sleep: Any = time.sleep,
) -> tuple[bool, int | None, str | None, int, int]:
    """Attempt delivery with exponential backoff.

    Returns (success, last_http_status, last_error, total_attempts,
    total_latency_ms). ``sleep`` is injectable for tests.
    """
    last_status: int | None = None
    last_error: str | None = None
    total_started = time.perf_counter()
    s = get_settings()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = safe_post(
                url,
                content=body,
                headers=headers,
                timeout=timeout,
                allow_http=s.webhook_egress_allow_http,
                allow_private=s.webhook_egress_allow_private,
                extra_blocked_cidrs=s.webhook_egress_extra_blocked_cidrs,
            )
            last_status = resp.status_code
            if 200 <= resp.status_code < 300:
                elapsed_ms = int((time.perf_counter() - total_started) * 1000)
                return True, last_status, None, attempt, elapsed_ms
            last_error = f"HTTP {resp.status_code}"
        except EgressBlocked as exc:
            # Egress denials are deterministic: a private/loopback/metadata
            # target will not become safe on retry. Record once and abort
            # the backoff loop so we don't burn delivery attempts on a
            # config error.
            elapsed_ms = int((time.perf_counter() - total_started) * 1000)
            return False, None, f"egress blocked: {exc}"[:500], attempt, elapsed_ms
        except Exception as exc:  # noqa: BLE001
            last_status = None
            last_error = (str(exc) or exc.__class__.__name__)[:500]
        if attempt < MAX_ATTEMPTS:
            sleep(BACKOFF_BASE_SECONDS * (BACKOFF_MULTIPLIER ** (attempt - 1)))
    elapsed_ms = int((time.perf_counter() - total_started) * 1000)
    return False, last_status, last_error, MAX_ATTEMPTS, elapsed_ms


def _subscription_signing_key(subscription_id: str, *, tenant_id: str) -> str | None:
    """Return the stored secret_hash for HMAC signing.

    We sign with the SHA-256 of the plaintext secret. Receivers configured
    at create time can re-derive the same value by hashing the secret they
    were shown, so signatures verify without storing a recoverable secret.
    """
    keys = _subscription_signing_keys(subscription_id, tenant_id=tenant_id)
    return keys[0] if keys else None


def _subscription_signing_keys(
    subscription_id: str, *, tenant_id: str
) -> tuple[str | None, str | None]:
    """Return ``(primary_secret_hash, next_secret_hash)`` for a subscription.

    During a rotation overlap window both are non-None and the dispatcher
    signs every outbound payload with both, exposing the old signature in
    ``X-Shotclassify-Signature`` and the new one in
    ``X-Shotclassify-Signature-Next`` so receivers can roll over.
    """
    init_db()
    session = get_session()
    try:
        row = (
            session.execute(
                select(WebhookSubscriptionRow).where(
                    WebhookSubscriptionRow.id == subscription_id,
                    WebhookSubscriptionRow.tenant_id == tenant_id,
                )
            )
            .scalars()
            .first()
        )
        if not row:
            return (None, None)
        return (row.secret_hash, row.secret_hash_next)
    finally:
        session.close()


def rotate_subscription_secret(
    subscription_id: str, *, tenant_id: str
) -> tuple[SubscriptionRecord, str] | None:
    """Mint a new plaintext signing secret and stage it as ``next``.

    The previous secret stays primary until :func:`finalize_subscription_secret_rotation`
    is called, so receivers have an overlap window during which the
    dispatcher signs payloads with both keys.

    Returns ``(record, plaintext_new_secret)`` or ``None`` if the
    subscription does not exist in this tenant or has been revoked.
    Tenant-scoped: callers must pass the verified ``tenant_id`` from
    ``request.state.tenant_id``.
    """
    init_db()
    if not tenant_id or not subscription_id:
        return None
    session = get_session()
    try:
        row = (
            session.execute(
                select(WebhookSubscriptionRow).where(
                    WebhookSubscriptionRow.id == subscription_id,
                    WebhookSubscriptionRow.tenant_id == tenant_id,
                )
            )
            .scalars()
            .first()
        )
        if row is None or row.revoked_at is not None:
            return None
        new_secret = f"whsec_{secrets.token_urlsafe(32)}"
        row.secret_hash_next = hash_secret(new_secret)
        row.secret_rotated_at = datetime.now(UTC)
        session.commit()
        session.refresh(row)
        return SubscriptionRecord.from_row(row), new_secret
    finally:
        session.close()


def finalize_subscription_secret_rotation(
    subscription_id: str, *, tenant_id: str
) -> SubscriptionRecord | None:
    """Promote the staged ``secret_hash_next`` to be the primary key.

    Drops the old secret from the dual-sign overlap. After this call new
    deliveries are signed only with the rotated secret, so any receiver
    that has not yet updated will start failing signature verification.
    """
    init_db()
    if not tenant_id or not subscription_id:
        return None
    session = get_session()
    try:
        row = (
            session.execute(
                select(WebhookSubscriptionRow).where(
                    WebhookSubscriptionRow.id == subscription_id,
                    WebhookSubscriptionRow.tenant_id == tenant_id,
                )
            )
            .scalars()
            .first()
        )
        if row is None or row.secret_hash_next is None:
            return None
        row.secret_hash = row.secret_hash_next
        row.secret_hash_next = None
        # Keep secret_rotated_at as the timestamp the new secret took over.
        row.secret_rotated_at = datetime.now(UTC)
        session.commit()
        session.refresh(row)
        return SubscriptionRecord.from_row(row)
    finally:
        session.close()


def cancel_subscription_secret_rotation(
    subscription_id: str, *, tenant_id: str
) -> SubscriptionRecord | None:
    """Abandon a pending rotation; the original secret stays primary."""
    init_db()
    if not tenant_id or not subscription_id:
        return None
    session = get_session()
    try:
        row = (
            session.execute(
                select(WebhookSubscriptionRow).where(
                    WebhookSubscriptionRow.id == subscription_id,
                    WebhookSubscriptionRow.tenant_id == tenant_id,
                )
            )
            .scalars()
            .first()
        )
        if row is None or row.secret_hash_next is None:
            return None
        row.secret_hash_next = None
        session.commit()
        session.refresh(row)
        return SubscriptionRecord.from_row(row)
    finally:
        session.close()


def dispatch_event(
    *,
    tenant_id: str,
    event: str,
    payload: dict[str, Any],
    request_id: str | None = None,
    sleep: Any = time.sleep,
) -> list[DeliveryRecord]:
    """Synchronously deliver an event to every matching active subscription.

    Returns the list of recorded :class:`DeliveryRecord` (one per
    subscription attempted). Pipeline callers should run this from a
    background thread / task to avoid blocking the request handler on
    backoff sleeps.
    """
    if not tenant_id:
        return []
    subs = [s for s in list_subscriptions(tenant_id) if s.active]
    if not subs:
        return []
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    results: list[DeliveryRecord] = []
    for sub in subs:
        if not _matches_event(sub.events, event):
            continue
        primary_key, next_key = _subscription_signing_keys(
            sub.id, tenant_id=tenant_id
        )
        if not primary_key:
            continue
        signature = sign_body(primary_key, body)
        delivery_id_hint = _new_id("whd")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "shotclassify-webhooks/1",
            "X-Shotclassify-Event": event,
            "X-Shotclassify-Delivery": delivery_id_hint,
            "X-Shotclassify-Signature": signature,
            "X-Shotclassify-Subscription": sub.id,
        }
        if next_key:
            # Dual-sign during a rotation overlap so receivers can roll
            # over to the new secret without dropping events.
            headers["X-Shotclassify-Signature-Next"] = sign_body(next_key, body)
        if request_id:
            headers["X-Request-ID"] = request_id
        ok, http_status, err, attempts, latency_ms = _post_with_retries(
            url=sub.url, body=body, headers=headers, sleep=sleep
        )
        recorded_id = _record_delivery(
            tenant_id=sub.tenant_id,
            subscription_id=sub.id,
            event=event,
            url=sub.url,
            status="success" if ok else "failed",
            attempt=attempts,
            http_status=http_status,
            error=err,
            latency_ms=latency_ms,
            payload_preview=body.decode("utf-8", errors="replace")[
                :MAX_PAYLOAD_PREVIEW
            ],
            signature=signature,
            request_id=request_id,
        )
        log.info(
            "webhook_delivered",
            delivery_id=recorded_id,
            subscription_id=sub.id,
            tenant_id=sub.tenant_id,
            webhook_event=event,
            status="success" if ok else "failed",
            attempts=attempts,
            http_status=http_status,
            latency_ms=latency_ms,
        )
        rec = get_delivery(recorded_id, tenant_id=sub.tenant_id)
        if rec:
            results.append(rec)
    return results


def replay_delivery(
    delivery_id: str,
    *,
    tenant_id: str,
    sleep: Any = time.sleep,
) -> DeliveryRecord | None:
    """Re-send a prior delivery's payload to its subscription.

    Looks up the original delivery row in this tenant, fetches the
    subscription it belonged to (also tenant-scoped), and dispatches the
    same JSON body again. The new attempt is persisted as its own
    ``webhook_deliveries`` row so the audit trail stays append-only.
    """
    init_db()
    original = get_delivery(delivery_id, tenant_id=tenant_id)
    if not original:
        return None
    sub = get_subscription(original.subscription_id, tenant_id=tenant_id)
    if not sub or not sub.active:
        return None
    primary_key, next_key = _subscription_signing_keys(
        sub.id, tenant_id=tenant_id
    )
    if not primary_key:
        return None
    # Reconstruct as much of the original payload as we kept; the preview
    # column is the canonical truth we persisted, capped at 512 bytes.
    # For replay we re-sign the preview verbatim so receivers can verify.
    body = original.payload_preview.encode("utf-8")
    signature = sign_body(primary_key, body)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "shotclassify-webhooks/1",
        "X-Shotclassify-Event": original.event,
        "X-Shotclassify-Delivery": _new_id("whd"),
        "X-Shotclassify-Signature": signature,
        "X-Shotclassify-Subscription": sub.id,
        "X-Shotclassify-Replay-Of": delivery_id,
    }
    if next_key:
        headers["X-Shotclassify-Signature-Next"] = sign_body(next_key, body)
    ok, http_status, err, attempts, latency_ms = _post_with_retries(
        url=sub.url, body=body, headers=headers, sleep=sleep
    )
    new_id = _record_delivery(
        tenant_id=sub.tenant_id,
        subscription_id=sub.id,
        event=original.event,
        url=sub.url,
        status="success" if ok else "failed",
        attempt=attempts,
        http_status=http_status,
        error=err,
        latency_ms=latency_ms,
        payload_preview=original.payload_preview,
        signature=signature,
        request_id=None,
    )
    return get_delivery(new_id, tenant_id=tenant_id)
