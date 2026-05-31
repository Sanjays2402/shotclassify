"""Webhook subscription + delivery routes.

Enterprise integrations register an outbound URL here; the API service
signs every payload with HMAC-SHA256 and POSTs it on matching events,
with exponential-backoff retries and a full delivery log.

Everything is tenant-scoped: the create/list/get/revoke/replay helpers
in :mod:`shotclassify_store.webhooks` all require an explicit
``tenant_id`` which we pull from ``request.state.tenant_id`` (set by the
TenantResolutionMiddleware). Admin-only via :func:`require_role` and
audit-logged by the existing audit middleware. Destructive endpoints
honor ``?dry_run=true``.

Signature scheme is documented in the store module: receivers verify
each request by computing ``HMAC-SHA256(SHA256(secret), body)`` against
the plaintext secret they were shown at create time.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from shotclassify_store import webhooks_store

from ..dryrun import dry_run_query, mark_dry_run
from ..middleware.mfa import require_mfa_step_up
from ..middleware.rbac import require_role


router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


class CreateWebhookRequest(BaseModel):
    url: str = Field(min_length=1, max_length=1024)
    events: list[Literal["classify.completed", "classify.failed", "*"]]
    description: str | None = Field(default=None, max_length=255)


class ReplayRequest(BaseModel):
    delivery_id: str = Field(min_length=1, max_length=64)


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=422,
            detail="A tenant context is required for webhooks. Pass X-Tenant.",
        )
    return tenant_id


@router.get("")
def list_webhooks(request: Request, _: str = require_role("admin")):
    """List webhook subscriptions for the caller's tenant."""
    tenant_id = _require_tenant(request)
    records = webhooks_store.list_subscriptions(tenant_id)
    return {
        "webhooks": [r.to_dict() for r in records],
        "tenant_id": tenant_id,
        "allowed_events": list(webhooks_store.ALLOWED_EVENTS),
    }


@router.post("", dependencies=[require_mfa_step_up()])
def create_webhook(
    payload: CreateWebhookRequest,
    request: Request,
    _: str = require_role("admin"),
):
    """Create a subscription. The signing secret is returned exactly once."""
    tenant_id = _require_tenant(request)
    try:
        record, secret = webhooks_store.create_subscription(
            tenant_id=tenant_id,
            url=payload.url,
            events=list(payload.events),
            description=payload.description,
            created_by=getattr(request.state, "principal", None),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    request.state.audit_target_id = record.id
    return {
        "webhook": record.to_dict(),
        "secret": secret,
        "secret_warning": (
            "Store this secret now. We hash it server-side and cannot show it again."
        ),
    }


@router.get("/{webhook_id}")
def get_webhook(
    webhook_id: str,
    request: Request,
    _: str = require_role("admin"),
):
    tenant_id = _require_tenant(request)
    record = webhooks_store.get_subscription(webhook_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(404, "Webhook not found.")
    return {"webhook": record.to_dict()}


@router.delete("/{webhook_id}", dependencies=[require_mfa_step_up()])
def revoke_webhook(
    webhook_id: str,
    request: Request,
    dry_run: bool = dry_run_query(),
    _: str = require_role("admin"),
):
    tenant_id = _require_tenant(request)
    record = webhooks_store.get_subscription(webhook_id, tenant_id=tenant_id)
    if dry_run:
        if record is None:
            return mark_dry_run(request, would_revoke=None)
        request.state.audit_target_id = record.id
        return mark_dry_run(
            request,
            would_revoke={
                "id": record.id,
                "url": record.url,
                "currently_active": record.active,
            },
        )
    if not record:
        raise HTTPException(404, "Webhook not found.")
    ok = webhooks_store.revoke_subscription(webhook_id, tenant_id=tenant_id)
    if not ok:
        raise HTTPException(404, "Webhook not found.")
    request.state.audit_target_id = webhook_id
    return {"ok": True, "revoked": webhook_id}


@router.get("/{webhook_id}/deliveries")
def list_webhook_deliveries(
    webhook_id: str,
    request: Request,
    status: str | None = Query(None, pattern="^(success|failed)$"),
    limit: int = Query(100, ge=1, le=500),
    _: str = require_role("admin"),
):
    tenant_id = _require_tenant(request)
    # Confirm the subscription belongs to this tenant first; otherwise
    # an admin in tenant A could enumerate delivery ids by guessing.
    sub = webhooks_store.get_subscription(webhook_id, tenant_id=tenant_id)
    if not sub:
        raise HTTPException(404, "Webhook not found.")
    records = webhooks_store.list_deliveries(
        tenant_id=tenant_id,
        subscription_id=webhook_id,
        status=status,
        limit=limit,
    )
    return {
        "deliveries": [r.to_dict() for r in records],
        "webhook_id": webhook_id,
    }


@router.get("/deliveries/recent")
def list_recent_deliveries(
    request: Request,
    status: str | None = Query(None, pattern="^(success|failed)$"),
    limit: int = Query(100, ge=1, le=500),
    _: str = require_role("admin"),
):
    """Tenant-wide delivery feed for the admin console."""
    tenant_id = _require_tenant(request)
    records = webhooks_store.list_deliveries(
        tenant_id=tenant_id, status=status, limit=limit
    )
    return {"deliveries": [r.to_dict() for r in records], "tenant_id": tenant_id}


@router.post("/deliveries/{delivery_id}/replay", dependencies=[require_mfa_step_up()])
def replay_delivery(
    delivery_id: str,
    request: Request,
    dry_run: bool = dry_run_query(),
    _: str = require_role("admin"),
):
    """Re-send a prior delivery's payload to its subscription endpoint."""
    tenant_id = _require_tenant(request)
    original = webhooks_store.get_delivery(delivery_id, tenant_id=tenant_id)
    if not original:
        raise HTTPException(404, "Delivery not found.")
    if dry_run:
        request.state.audit_target_id = delivery_id
        return mark_dry_run(
            request,
            would_replay={
                "delivery_id": delivery_id,
                "subscription_id": original.subscription_id,
                "url": original.url,
                "event": original.event,
                "bytes": len(original.payload_preview.encode("utf-8")),
            },
        )
    new_record = webhooks_store.replay_delivery(delivery_id, tenant_id=tenant_id)
    if not new_record:
        raise HTTPException(
            409,
            "Cannot replay: subscription is missing, revoked, or signing key unavailable.",
        )
    request.state.audit_target_id = new_record.id
    return {"delivery": new_record.to_dict(), "replayed_from": delivery_id}
