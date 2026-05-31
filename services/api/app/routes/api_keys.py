"""DB-backed API key management.

Workspace admins use this surface to provision, list, and revoke API keys
without a redeploy. Plaintext tokens are returned exactly once at creation
and never persisted; everything else (scopes, tenant binding, expiry,
revocation, last-used) lives in the ``api_keys`` table.

Every mutation is audited by the existing audit middleware. Create and
revoke also require MFA step-up so a stolen session cookie cannot silently
mint a long-lived credential.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from shotclassify_store import api_keys_store

from ..dryrun import dry_run_query, mark_dry_run
from ..middleware.mfa import require_mfa_step_up
from ..middleware.rbac import require_role


router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])

_SCOPE_VALUES = sorted(api_keys_store.VALID_SCOPES)


class CreateKeyRequest(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    scopes: list[Literal["read:classifications", "write:classifications", "read:audit", "admin"]]
    tenant_id: str | None = Field(default=None, max_length=64)
    ttl_days: int | None = Field(default=None, ge=1, le=3650)


def _effective_tenant(request: Request, requested: str | None) -> str | None:
    """Resolve which tenant a newly created key should be bound to.

    Admins acting in cross-tenant mode (``X-Tenant: *``) MUST pass an
    explicit ``tenant_id`` in the body. Otherwise the key inherits the
    caller's resolved tenant so a tenant-scoped admin cannot accidentally
    issue a key against another workspace.
    """
    caller_tenant = getattr(request.state, "tenant_id", None)
    if requested:
        requested = requested.strip()[:64]
        if caller_tenant is None:
            return requested or None
        if requested and requested != caller_tenant:
            raise HTTPException(
                status_code=403,
                detail="Cannot mint a key for a different tenant from this session.",
            )
        return caller_tenant
    if caller_tenant is None:
        raise HTTPException(
            status_code=422,
            detail="tenant_id is required when acting in cross-tenant mode.",
        )
    return caller_tenant


@router.get("")
def list_my_keys(
    request: Request,
    include_revoked: bool = Query(False),
    _: str = require_role("admin"),
):
    """List API keys for the caller's tenant (admin only)."""
    tenant_id = getattr(request.state, "tenant_id", None)
    records = api_keys_store.list_keys(
        tenant_id=tenant_id, include_revoked=include_revoked
    )
    return {
        "keys": [r.to_dict() for r in records],
        "tenant_id": tenant_id,
        "available_scopes": _SCOPE_VALUES,
    }


@router.post("", status_code=201, dependencies=[require_mfa_step_up()])
def create_my_key(
    payload: CreateKeyRequest,
    request: Request,
    _: str = require_role("admin"),
):
    """Mint a new key. The plaintext ``token`` field is returned exactly once."""
    tenant_id = _effective_tenant(request, payload.tenant_id)
    created_by = getattr(request.state, "principal", None)
    try:
        record, token = api_keys_store.create_key(
            label=payload.label,
            tenant_id=tenant_id,
            scopes=payload.scopes,
            created_by=created_by,
            ttl_days=payload.ttl_days,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    body = record.to_dict()
    body["token"] = token
    body["token_display_once"] = True
    # Surface the new key id on request.state so the audit middleware writes
    # it into the ``target_id`` column for forensics.
    request.state.audit_target_id = record.id
    return body


@router.delete("/{key_id}", dependencies=[require_mfa_step_up()])
def revoke_my_key(
    key_id: str,
    request: Request,
    dry_run: bool = dry_run_query(),
    _: str = require_role("admin"),
):
    """Soft-revoke a key. Returns 404 (not 403) for unknown or wrong-tenant ids."""
    tenant_id = getattr(request.state, "tenant_id", None)
    if dry_run:
        keys = api_keys_store.list_keys(tenant_id=tenant_id, include_revoked=True)
        record = next((k for k in keys if k.id == key_id), None)
        if record is None or getattr(record, "revoked_at", None) is not None:
            return mark_dry_run(request, would_revoke=None)
        request.state.audit_target_id = record.id
        return mark_dry_run(
            request,
            would_revoke={"id": record.id, "label": getattr(record, "label", None)},
        )
    record = api_keys_store.revoke(key_id, tenant_id=tenant_id)
    if record is None:
        raise HTTPException(404, "API key not found.")
    request.state.audit_target_id = record.id
    return {"revoked": True, "key": record.to_dict()}
