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
from ..middleware.rbac import require_role, require_scope


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


@router.get("", dependencies=[require_scope("read:classifications")])
def list_webhooks(request: Request, _: str = require_role("admin")):
    """List webhook subscriptions for the caller's tenant."""
    tenant_id = _require_tenant(request)
    records = webhooks_store.list_subscriptions(tenant_id)
    return {
        "webhooks": [r.to_dict() for r in records],
        "tenant_id": tenant_id,
        "allowed_events": list(webhooks_store.ALLOWED_EVENTS),
    }


@router.post("", dependencies=[require_mfa_step_up(), require_scope("admin")])
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


@router.get("/{webhook_id}", dependencies=[require_scope("read:classifications")])
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


@router.delete("/{webhook_id}", dependencies=[require_mfa_step_up(), require_scope("admin")])
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


@router.post(
    "/{webhook_id}/pause",
    dependencies=[require_mfa_step_up(), require_scope("admin")],
)
def pause_webhook(
    webhook_id: str,
    request: Request,
    dry_run: bool = dry_run_query(),
    _: str = require_role("admin"),
):
    """Stop delivering events to this subscription without revoking it.

    Paused subscriptions keep their signing secret, event filters, and
    delivery history; the dispatcher and replay paths both skip them.
    Use this during a downstream incident; resume to restart delivery.
    """
    return _set_webhook_active(webhook_id, request, dry_run=dry_run, active=False)


@router.post(
    "/{webhook_id}/resume",
    dependencies=[require_mfa_step_up(), require_scope("admin")],
)
def resume_webhook(
    webhook_id: str,
    request: Request,
    dry_run: bool = dry_run_query(),
    _: str = require_role("admin"),
):
    """Restart event delivery on a previously paused subscription.

    Revoked subscriptions cannot be resumed (409); create a new one.
    """
    return _set_webhook_active(webhook_id, request, dry_run=dry_run, active=True)


def _set_webhook_active(
    webhook_id: str, request: Request, *, dry_run: bool, active: bool
) -> dict:
    tenant_id = _require_tenant(request)
    record = webhooks_store.get_subscription(webhook_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(404, "Webhook not found.")
    request.state.audit_target_id = webhook_id
    if dry_run:
        next_status = "active" if active else "paused"
        return mark_dry_run(
            request,
            would_set={
                "id": record.id,
                "url": record.url,
                "from_status": record.status,
                "to_status": next_status,
            },
        )
    try:
        updated = webhooks_store.set_subscription_active(
            webhook_id, tenant_id=tenant_id, active=active
        )
    except LookupError:
        raise HTTPException(404, "Webhook not found.")
    except webhooks_store.SubscriptionStateError as exc:
        status_code = 410 if exc.code == "revoked" else 409
        raise HTTPException(status_code, str(exc))
    return {"ok": True, "webhook": updated.to_dict()}


@router.get("/{webhook_id}/deliveries", dependencies=[require_scope("read:audit")])
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


@router.get("/deliveries/recent", dependencies=[require_scope("read:audit")])
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


@router.post("/deliveries/{delivery_id}/replay", dependencies=[require_mfa_step_up(), require_scope("admin")])
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


@router.post(
    "/{webhook_id}/test",
    dependencies=[require_mfa_step_up(), require_scope("admin")],
)
def test_webhook(
    webhook_id: str,
    request: Request,
    dry_run: bool = dry_run_query(),
    _: str = require_role("admin"),
):
    """Fire a signed ``webhook.test`` ping at this subscription.

    Lets a workspace admin verify TLS, signature handling, the tenant
    egress allowlist, and receiver code on a brand-new subscription
    before any real event flows. The ping is delivered regardless of
    the subscription's event filter and is persisted as a normal
    delivery row so it appears in the standard delivery feed and
    audit export. Subject to MFA step-up and admin scope.
    """
    tenant_id = _require_tenant(request)
    record = webhooks_store.get_subscription(webhook_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(404, "Webhook not found.")
    request.state.audit_target_id = webhook_id
    if dry_run:
        return mark_dry_run(
            request,
            would_test={
                "id": record.id,
                "url": record.url,
                "event": webhooks_store.TEST_EVENT,
                "active": record.active,
            },
        )
    if not record.active:
        raise HTTPException(
            409,
            "Cannot test a paused or revoked subscription. Resume it first.",
        )
    actor = getattr(request.state, "principal", None)
    request_id = getattr(request.state, "request_id", None)
    delivery = webhooks_store.dispatch_test_event(
        webhook_id,
        tenant_id=tenant_id,
        actor=actor,
        request_id=request_id,
    )
    if not delivery:
        # Cross-tenant guards or missing signing key. Mirror the 404
        # used elsewhere to avoid leaking existence.
        raise HTTPException(409, "Test event could not be dispatched.")
    return {
        "ok": delivery.status == "success",
        "delivery": delivery.to_dict(),
        "webhook_id": webhook_id,
        "event": webhooks_store.TEST_EVENT,
    }


@router.post(
    "/{webhook_id}/rotate-secret",
    dependencies=[require_mfa_step_up(), require_scope("admin")],
)
def rotate_webhook_secret(
    webhook_id: str,
    request: Request,
    dry_run: bool = dry_run_query(),
    _: str = require_role("admin"),
):
    """Mint a new HMAC signing secret with an overlap window.

    The existing secret stays primary until the rotation is finalised, so
    receivers can update their stored secret while the dispatcher signs
    every outbound payload with BOTH keys: the old one in
    ``X-Shotclassify-Signature`` and the new one in
    ``X-Shotclassify-Signature-Next``. The plaintext new secret is
    returned exactly once.
    """
    tenant_id = _require_tenant(request)
    record = webhooks_store.get_subscription(webhook_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(404, "Webhook not found.")
    if not record.active:
        raise HTTPException(409, "Cannot rotate a revoked subscription.")
    request.state.audit_target_id = webhook_id
    if dry_run:
        return mark_dry_run(
            request,
            would_rotate={
                "id": record.id,
                "url": record.url,
                "already_pending": record.secret_rotation_pending,
            },
        )
    result = webhooks_store.rotate_subscription_secret(
        webhook_id, tenant_id=tenant_id
    )
    if not result:
        raise HTTPException(404, "Webhook not found.")
    rotated, secret = result
    return {
        "webhook": rotated.to_dict(),
        "secret": secret,
        "secret_warning": (
            "Store this secret now. We hash it server-side and cannot show "
            "it again. The previous secret stays valid until you finalise "
            "the rotation."
        ),
    }


@router.post(
    "/{webhook_id}/finalize-secret",
    dependencies=[require_mfa_step_up(), require_scope("admin")],
)
def finalize_webhook_secret(
    webhook_id: str,
    request: Request,
    dry_run: bool = dry_run_query(),
    _: str = require_role("admin"),
):
    """Drop the previous secret from the dual-sign overlap window.

    After this call only the rotated secret is used. Any receiver that
    has not updated yet will start failing signature verification, so
    finalise only after confirming the new secret works end to end.
    """
    tenant_id = _require_tenant(request)
    record = webhooks_store.get_subscription(webhook_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(404, "Webhook not found.")
    if not record.secret_rotation_pending:
        raise HTTPException(409, "No rotation is in progress for this webhook.")
    request.state.audit_target_id = webhook_id
    if dry_run:
        return mark_dry_run(
            request,
            would_finalize={"id": record.id, "url": record.url},
        )
    rotated = webhooks_store.finalize_subscription_secret_rotation(
        webhook_id, tenant_id=tenant_id
    )
    if not rotated:
        raise HTTPException(404, "Webhook not found.")
    return {"webhook": rotated.to_dict(), "finalized": True}


@router.post(
    "/{webhook_id}/cancel-rotation",
    dependencies=[require_mfa_step_up(), require_scope("admin")],
)
def cancel_webhook_rotation(
    webhook_id: str,
    request: Request,
    dry_run: bool = dry_run_query(),
    _: str = require_role("admin"),
):
    """Abandon a pending rotation; the original secret stays primary."""
    tenant_id = _require_tenant(request)
    record = webhooks_store.get_subscription(webhook_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(404, "Webhook not found.")
    if not record.secret_rotation_pending:
        raise HTTPException(409, "No rotation is in progress for this webhook.")
    request.state.audit_target_id = webhook_id
    if dry_run:
        return mark_dry_run(
            request,
            would_cancel={"id": record.id, "url": record.url},
        )
    rotated = webhooks_store.cancel_subscription_secret_rotation(
        webhook_id, tenant_id=tenant_id
    )
    if not rotated:
        raise HTTPException(404, "Webhook not found.")
    return {"webhook": rotated.to_dict(), "canceled": True}
