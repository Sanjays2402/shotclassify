"""Trust Center: sub-processor catalog and per-tenant acknowledgements.

* ``GET /v1/trust/subprocessors`` is public so procurement reviewers can
  inspect the catalog before they have credentials. It returns the full
  vendor-managed list plus the deterministic version hash.
* ``GET /v1/trust/subprocessors/ack`` returns the caller workspace's
  acknowledgement state and whether the published catalog has changed
  since the last ack (a "stale" flag the UI uses to re-prompt the
  owner).
* ``POST /v1/trust/subprocessors/ack`` records the acknowledgement.
  Admin role + MFA step-up required because it is a binding compliance
  attestation; the mutating route is picked up by the audit middleware
  so the actor, IP, user agent, and request id land in the tamper-
  evident audit chain automatically.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from shotclassify_store import subprocessors_store

from ..middleware.mfa import require_mfa_step_up
from ..middleware.rbac import require_role

router = APIRouter(prefix="/v1/trust", tags=["trust"])


def _tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            400, "No tenant resolved. Pass X-Tenant header to target a tenant."
        )
    return tenant_id


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.client.host if request.client else None


@router.get("/subprocessors")
def list_subprocessors_public() -> dict:
    """Public sub-processor catalog. No auth required.

    Procurement teams evaluating the product need to fetch this without
    credentials, the same way they would download a PDF from a vendor's
    trust page. The endpoint is read-only and tenant-agnostic.
    """
    return subprocessors_store.list_catalog()


@router.get(
    "/subprocessors/ack",
    dependencies=[require_role("admin")],
)
def get_ack_route(request: Request) -> dict:
    tenant_id = _tenant(request)
    return {"tenant_id": tenant_id, **subprocessors_store.status_for(tenant_id)}


@router.post(
    "/subprocessors/ack",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def post_ack_route(request: Request, payload: dict = Body(...)) -> dict:
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "Body must be a JSON object.")
    version = payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise HTTPException(422, "Field 'version' is required (string).")
    actor = getattr(request.state, "principal", None)
    if not actor:
        # Should never happen behind require_role, but defend in depth.
        raise HTTPException(401, "Authenticated principal required.")
    try:
        ack = subprocessors_store.acknowledge(
            tenant_id,
            version.strip(),
            acknowledged_by=str(actor),
            acknowledged_ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"tenant_id": tenant_id, **subprocessors_store.status_for(tenant_id), "ack": ack.to_dict()}
