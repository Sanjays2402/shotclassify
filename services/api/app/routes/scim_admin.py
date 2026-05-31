"""Admin endpoints for managing the per-tenant SCIM provisioning config.

The SCIM bearer token rotation lives here, not in /scim/v2/*. Putting it
under the same admin surface as API keys and SSO means it inherits the
existing session-cookie + MFA-step-up + RBAC stack, and the new SCIM
router stays pure RFC 7644.

All endpoints are tenant-scoped and require ``admin`` role plus a fresh
MFA step-up for any operation that mints or revokes a token. Audit log
middleware captures every mutation automatically.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from shotclassify_store import scim_store

from ..middleware.mfa import require_mfa_step_up
from ..middleware.rbac import require_role

router = APIRouter(prefix="/v1/scim", tags=["scim-admin"])


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=422,
            detail="A tenant context is required. Pass X-Tenant or sign in to a workspace.",
        )
    return tenant_id


class ScimEnabledIn(BaseModel):
    enabled: bool


class ScimDefaultRoleIn(BaseModel):
    role: str = Field(..., description="viewer or operator. admin is rejected.")


@router.get("/config", dependencies=[require_role("admin")])
def get_config(request: Request) -> dict:
    tenant_id = _require_tenant(request)
    return scim_store.get_scim_config(tenant_id).to_dict()


@router.put(
    "/config/enabled",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def set_enabled(payload: ScimEnabledIn, request: Request) -> dict:
    tenant_id = _require_tenant(request)
    caller = getattr(request.state, "principal", None)
    cfg = scim_store.set_scim_enabled(tenant_id, payload.enabled, updated_by=caller)
    return cfg.to_dict()


@router.put(
    "/config/default-role",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def set_default_role(payload: ScimDefaultRoleIn, request: Request) -> dict:
    tenant_id = _require_tenant(request)
    caller = getattr(request.state, "principal", None)
    try:
        cfg = scim_store.set_scim_default_role(tenant_id, payload.role, updated_by=caller)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return cfg.to_dict()


@router.post(
    "/token/rotate",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def rotate_token(request: Request) -> dict:
    tenant_id = _require_tenant(request)
    caller = getattr(request.state, "principal", None)
    cfg, token = scim_store.rotate_scim_token(tenant_id, updated_by=caller)
    return {
        "token": token,
        "token_display_once": True,
        "config": cfg.to_dict(),
    }


@router.delete(
    "/token",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def revoke_token(request: Request) -> dict:
    tenant_id = _require_tenant(request)
    caller = getattr(request.state, "principal", None)
    cfg = scim_store.revoke_scim_token(tenant_id, updated_by=caller)
    return cfg.to_dict()
