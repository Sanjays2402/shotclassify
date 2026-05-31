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
from shotclassify_store import api_keys_store, get_api_key_ttl_policy
from ..dryrun import dry_run_query, mark_dry_run
from ..middleware.mfa import require_mfa_step_up
from ..middleware.rbac import require_role, require_scope


router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])

_SCOPE_VALUES = sorted(api_keys_store.VALID_SCOPES)


class CreateKeyRequest(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    scopes: list[Literal["read:classifications", "write:classifications", "read:audit", "admin"]]
    tenant_id: str | None = Field(default=None, max_length=64)
    ttl_days: int | None = Field(default=None, ge=1, le=3650)
    allowed_cidrs: list[str] | None = Field(
        default=None,
        max_length=64,
        description=(
            "Optional source-IP allowlist. Accepts bare addresses or CIDR "
            "ranges, IPv4 and IPv6. Empty list or omitted means no "
            "restriction. When set, requests with X-API-Key that arrive "
            "from an IP outside the allowlist are rejected with HTTP 403."
        ),
    )


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


@router.get("", dependencies=[require_scope("admin")])
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
        "ttl_policy": get_api_key_ttl_policy(tenant_id).to_dict(),
    }


@router.post("", status_code=201, dependencies=[require_mfa_step_up(), require_scope("admin")])
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
            allowed_cidrs=payload.allowed_cidrs,
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


@router.delete("/{key_id}", dependencies=[require_mfa_step_up(), require_scope("admin")])
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


class RotateKeyRequest(BaseModel):
    grace_minutes: int = Field(
        default=1440,
        ge=0,
        le=10080,
        description=(
            "How long the old key stays valid after rotation, in minutes. "
            "Default 24 hours. 0 revokes immediately. Maximum 7 days."
        ),
    )


@router.post(
    "/{key_id}/rotate",
    status_code=201,
    dependencies=[require_mfa_step_up(), require_scope("admin")],
)
def rotate_my_key(
    key_id: str,
    payload: RotateKeyRequest,
    request: Request,
    dry_run: bool = dry_run_query(),
    _: str = require_role("admin"),
):
    """Rotate an API key without downtime.

    Mints a successor key with the same tenant, scopes, and rpm override,
    then shortens the source key's lifetime to ``grace_minutes`` so callers
    have a finite window to swap the secret in their integrations. The new
    plaintext token is returned exactly once in the ``token`` field; the
    successor's ``id`` is in ``new_key.id``.

    Returns 404 for unknown ids or keys belonging to another tenant so a
    tenant-scoped admin cannot probe ids across workspaces. Returns 409 if
    the source key is already revoked.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if dry_run:
        keys = api_keys_store.list_keys(tenant_id=tenant_id, include_revoked=True)
        record = next((k for k in keys if k.id == key_id), None)
        if record is None or getattr(record, "revoked_at", None) is not None:
            return mark_dry_run(request, would_rotate=None)
        request.state.audit_target_id = record.id
        return mark_dry_run(
            request,
            would_rotate={
                "id": record.id,
                "label": record.label,
                "grace_minutes": payload.grace_minutes,
            },
        )
    actor = getattr(request.state, "principal", None)
    try:
        result = api_keys_store.rotate(
            key_id,
            tenant_id=tenant_id,
            grace_minutes=payload.grace_minutes,
            rotated_by=actor,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "API key not found.")
    old_rec, new_rec, token = result
    request.state.audit_target_id = old_rec.id
    body = new_rec.to_dict()
    body["token"] = token
    return {
        "rotated": True,
        "old_key": old_rec.to_dict(),
        "new_key": body,
        "grace_minutes": payload.grace_minutes,
    }


class RateLimitOverrideRequest(BaseModel):
    rpm: int | None = Field(
        default=None,
        ge=1,
        le=1_000_000,
        description="Requests per minute. Pass null to clear the override.",
    )


@router.patch("/{key_id}/rate-limit", dependencies=[require_mfa_step_up(), require_scope("admin")])
def set_key_rate_limit(
    key_id: str,
    payload: RateLimitOverrideRequest,
    request: Request,
    dry_run: bool = dry_run_query(),
    _: str = require_role("admin"),
):
    """Set or clear the per-key requests/minute override.

    ``rpm=null`` reverts the key to the workspace default. Returns 404 for
    unknown ids or keys belonging to another tenant so admins cannot probe
    ids across workspaces.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if dry_run:
        keys = api_keys_store.list_keys(tenant_id=tenant_id, include_revoked=True)
        record = next((k for k in keys if k.id == key_id), None)
        if record is None:
            return mark_dry_run(request, would_set=None)
        request.state.audit_target_id = record.id
        return mark_dry_run(
            request,
            would_set={
                "id": record.id,
                "label": record.label,
                "current_rpm_override": record.rpm_override,
                "new_rpm_override": payload.rpm,
            },
        )
    try:
        record = api_keys_store.set_rpm_override(
            key_id, tenant_id=tenant_id, rpm=payload.rpm
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if record is None:
        raise HTTPException(404, "API key not found.")
    request.state.audit_target_id = record.id
    return {"key": record.to_dict()}


class AllowedCidrsRequest(BaseModel):
    allowed_cidrs: list[str] = Field(
        default_factory=list,
        max_length=64,
        description=(
            "Replacement source-IP allowlist for this key. Accepts bare "
            "addresses or CIDR ranges, IPv4 and IPv6. An empty list "
            "clears the restriction so the key is again accepted from "
            "any IP."
        ),
    )


@router.patch(
    "/{key_id}/allowed-cidrs",
    dependencies=[require_mfa_step_up(), require_scope("admin")],
)
def set_key_allowed_cidrs(
    key_id: str,
    payload: AllowedCidrsRequest,
    request: Request,
    dry_run: bool = dry_run_query(),
    _: str = require_role("admin"),
):
    """Replace the per-key source-IP allowlist.

    Pass ``allowed_cidrs=[]`` to clear the restriction. Returns 404 for
    unknown ids or keys belonging to another tenant so admins cannot
    probe ids across workspaces. Returns 422 with the offending entry
    when an input is not a parseable IP address or CIDR range.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if dry_run:
        try:
            preview = api_keys_store.normalize_cidrs(payload.allowed_cidrs)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        keys = api_keys_store.list_keys(tenant_id=tenant_id, include_revoked=True)
        record = next((k for k in keys if k.id == key_id), None)
        if record is None:
            return mark_dry_run(request, would_set=None)
        request.state.audit_target_id = record.id
        return mark_dry_run(
            request,
            would_set={
                "id": record.id,
                "label": record.label,
                "current_allowed_cidrs": list(record.allowed_cidrs),
                "new_allowed_cidrs": preview,
            },
        )
    try:
        record = api_keys_store.set_allowed_cidrs(
            key_id, tenant_id=tenant_id, cidrs=payload.allowed_cidrs
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if record is None:
        raise HTTPException(404, "API key not found.")
    request.state.audit_target_id = record.id
    return {"key": record.to_dict()}
