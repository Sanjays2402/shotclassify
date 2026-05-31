"""Security incidents (public registry) + per-tenant notification subscriptions.

Two surfaces share this router because procurement reviewers think of
them as one feature ("how will you notify us of incidents?"):

* ``GET /v1/trust/incidents`` is public so a reviewer with no account
  can verify the vendor's incident history before signing the DPA. It
  matches the pattern used by ``GET /v1/trust/subprocessors``.
* ``GET|POST|PATCH|DELETE /v1/incident-subscriptions`` are tenant-scoped
  contact endpoints. Admin role + MFA step-up are required for mutating
  routes because they bind the workspace to a notification commitment
  that procurement and security teams audit. All mutations are picked up
  automatically by ``AuditLogMiddleware`` so the actor, IP, request id
  and timestamp land in the tamper-evident audit chain.

Every store call passes ``tenant_id`` explicitly. There is no global
query path for incident subscriptions; the only way to enumerate them is
through ``request.state.tenant_id``, which the tenant resolution
middleware sets from the authenticated principal.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from shotclassify_store import incidents_store

from ..dryrun import dry_run_query, mark_dry_run
from shotclassify_store.incidents import (
    IncidentSubscriptionError,
    VALID_SEVERITIES,
)

from ..middleware.mfa import require_mfa_step_up
from ..middleware.rbac import require_role

router = APIRouter(tags=["incidents"])


def _tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            400, "No tenant resolved. Pass X-Tenant header to target a tenant."
        )
    return tenant_id


def _actor(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    if not principal:
        # Should never happen behind require_role, but defend in depth.
        raise HTTPException(401, "Authenticated principal required.")
    return str(principal)


# ---------------------------------------------------------------------------
# Public incident registry
# ---------------------------------------------------------------------------

@router.get("/v1/trust/incidents")
def list_incidents_public() -> dict:
    """Public, append-only incident registry.

    Read-only and tenant-agnostic so procurement reviewers can fetch it
    without credentials, the same way they would download a status page
    or PDF.
    """
    items = incidents_store.list_incidents()
    return {
        "items": items,
        "count": len(items),
        "valid_severities": list(VALID_SEVERITIES),
        "valid_statuses": list(incidents_store.VALID_STATUSES),
    }


# ---------------------------------------------------------------------------
# Per-tenant notification subscriptions
# ---------------------------------------------------------------------------

@router.get(
    "/v1/incident-subscriptions",
    dependencies=[require_role("admin")],
)
def list_subscriptions_route(request: Request) -> dict:
    tenant_id = _tenant(request)
    items = [s.to_dict() for s in incidents_store.list_subscriptions(tenant_id)]
    return {
        "tenant_id": tenant_id,
        "items": items,
        "count": len(items),
        "valid_channels": list(incidents_store.VALID_CHANNELS),
        "valid_severities": list(VALID_SEVERITIES),
    }


@router.post(
    "/v1/incident-subscriptions",
    dependencies=[require_role("admin"), require_mfa_step_up()],
    status_code=201,
)
def create_subscription_route(
    request: Request,
    payload: dict = Body(...),
    dry_run: bool = dry_run_query(),
):
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "Body must be a JSON object.")
    channel = payload.get("channel")
    endpoint = payload.get("endpoint")
    severity_min = payload.get("severity_min", "low")
    label = payload.get("label")
    if not isinstance(channel, str) or not isinstance(endpoint, str):
        raise HTTPException(
            422, "Fields 'channel' and 'endpoint' are required (string)."
        )
    if severity_min is not None and not isinstance(severity_min, str):
        raise HTTPException(422, "'severity_min' must be a string.")
    if label is not None and not isinstance(label, str):
        raise HTTPException(422, "'label' must be a string.")
    if dry_run:
        if channel not in incidents_store.VALID_CHANNELS:
            raise HTTPException(422, f"'channel' must be one of {sorted(incidents_store.VALID_CHANNELS)}.")
        if (severity_min or "low") not in VALID_SEVERITIES:
            raise HTTPException(422, f"'severity_min' must be one of {sorted(VALID_SEVERITIES)}.")
        return mark_dry_run(
            request,
            would_create={
                "tenant_id": tenant_id,
                "channel": channel,
                "endpoint": endpoint,
                "severity_min": severity_min or "low",
                "label": label,
            },
        )
    try:
        sub = incidents_store.create_subscription(
            tenant_id=tenant_id,
            channel=channel,
            endpoint=endpoint,
            severity_min=severity_min or "low",
            label=label,
            created_by=_actor(request),
        )
    except IncidentSubscriptionError as exc:
        raise HTTPException(409, str(exc))
    return {"tenant_id": tenant_id, "subscription": sub.to_dict()}


@router.patch(
    "/v1/incident-subscriptions/{sub_id}",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def update_subscription_route(
    sub_id: str,
    request: Request,
    payload: dict = Body(...),
    dry_run: bool = dry_run_query(),
):
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "Body must be a JSON object.")
    active = payload.get("active")
    severity_min = payload.get("severity_min")
    label = payload.get("label")
    if active is not None and not isinstance(active, bool):
        raise HTTPException(422, "'active' must be a boolean.")
    if severity_min is not None and not isinstance(severity_min, str):
        raise HTTPException(422, "'severity_min' must be a string.")
    if label is not None and not isinstance(label, str):
        raise HTTPException(422, "'label' must be a string.")
    if dry_run:
        existing = next(
            (s for s in incidents_store.list_subscriptions(tenant_id) if s.id == sub_id),
            None,
        )
        if existing is None:
            raise HTTPException(404, "Subscription not found in this tenant.")
        return mark_dry_run(
            request,
            would_update={
                "id": sub_id,
                "active": active,
                "severity_min": severity_min,
                "label": label,
            },
        )
    try:
        sub = incidents_store.update_subscription(
            tenant_id=tenant_id,
            sub_id=sub_id,
            active=active,
            severity_min=severity_min,
            label=label,
        )
    except IncidentSubscriptionError as exc:
        raise HTTPException(409, str(exc))
    if sub is None:
        raise HTTPException(404, "Subscription not found in this tenant.")
    return {"tenant_id": tenant_id, "subscription": sub.to_dict()}


@router.delete(
    "/v1/incident-subscriptions/{sub_id}",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def delete_subscription_route(
    sub_id: str,
    request: Request,
    dry_run: bool = dry_run_query(),
):
    tenant_id = _tenant(request)
    if dry_run:
        existing = next(
            (s for s in incidents_store.list_subscriptions(tenant_id) if s.id == sub_id),
            None,
        )
        if existing is None:
            return mark_dry_run(request, would_delete=None)
        return mark_dry_run(request, would_delete={"id": sub_id})
    ok = incidents_store.delete_subscription(tenant_id=tenant_id, sub_id=sub_id)
    if not ok:
        raise HTTPException(404, "Subscription not found in this tenant.")
    return {"tenant_id": tenant_id, "deleted": sub_id}
