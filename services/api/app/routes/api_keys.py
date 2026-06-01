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
from shotclassify_store import api_keys_store, get_api_key_ttl_policy, get_api_key_max_active_policy
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
    monthly_quota: int | None = Field(
        default=None,
        ge=1,
        le=1_000_000_000,
        description=(
            "Optional per-API-key monthly call cap. When set, the rate "
            "limit middleware rejects requests with HTTP 429 once the key "
            "reaches this many calls in the current UTC month."
        ),
    )
    owner_email: str = Field(
        min_length=3,
        max_length=254,
        description=(
            "Accountable owner mailbox for this credential. Required so "
            "every active API key has a named human (or distribution "
            "list) the security team can contact when the key leaks, "
            "and so quarterly access reviews can be driven from a "
            "single field instead of a join against the audit log."
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
        "max_active_policy": {
            **get_api_key_max_active_policy(tenant_id).to_dict(),
            "current_active": sum(
                1 for r in records if getattr(r, "revoked_at", None) is None
            ),
        },
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
            monthly_quota=payload.monthly_quota,
            owner_email=payload.owner_email,
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


class MonthlyQuotaRequest(BaseModel):
    quota: int | None = Field(
        default=None,
        ge=1,
        le=1_000_000_000,
        description=(
            "Per-API-key monthly call quota. Pass null to clear the cap and "
            "fall back to unlimited (the legacy default). When set, the "
            "rate limit middleware atomically charges a counter and returns "
            "429 with X-RateLimit-Scope=api_key_month once the cap is hit. "
            "The counter resets at the start of the next UTC month."
        ),
    )


@router.patch(
    "/{key_id}/monthly-quota",
    dependencies=[require_mfa_step_up(), require_scope("admin")],
)
def set_key_monthly_quota(
    key_id: str,
    payload: MonthlyQuotaRequest,
    request: Request,
    dry_run: bool = dry_run_query(),
    _: str = require_role("admin"),
):
    """Set or clear the per-key monthly call quota.

    ``quota=null`` clears the cap so the key falls back to unlimited.
    Returns 404 for unknown ids or keys belonging to another tenant so
    admins cannot probe ids across workspaces. Returns 422 when the
    requested quota is outside the supported range.
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
                "current_monthly_quota": record.monthly_quota,
                "new_monthly_quota": payload.quota,
            },
        )
    try:
        record = api_keys_store.set_monthly_quota(
            key_id, tenant_id=tenant_id, quota=payload.quota
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if record is None:
        raise HTTPException(404, "API key not found.")
    request.state.audit_target_id = record.id
    return {"key": record.to_dict()}


@router.get(
    "/{key_id}/monthly-usage",
    dependencies=[require_scope("admin")],
)
def get_key_monthly_usage(
    key_id: str,
    request: Request,
    _: str = require_role("admin"),
):
    """Return the current month's call count and remaining quota for the key.

    Useful for the admin console and for end-user dashboards that want to
    surface "you have N calls left this month" without making the client
    parse rate-limit headers. Returns 404 for unknown ids or keys in
    another tenant.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    keys = api_keys_store.list_keys(tenant_id=tenant_id, include_revoked=True)
    record = next((k for k in keys if k.id == key_id), None)
    if record is None:
        raise HTTPException(404, "API key not found.")
    usage = api_keys_store.get_monthly_usage(record.id)
    remaining = None
    if record.monthly_quota is not None:
        remaining = max(0, record.monthly_quota - usage)
    return {
        "key_id": record.id,
        "label": record.label,
        "monthly_quota": record.monthly_quota,
        "monthly_usage": usage,
        "remaining": remaining,
    }


class OwnerEmailRequest(BaseModel):
    owner_email: str | None = Field(
        default=None,
        max_length=254,
        description=(
            "Accountable owner mailbox for this credential. Pass null to "
            "clear the owner (which sends the key back to the unowned "
            "bucket and into the next access review). The store rejects "
            "anything that does not parse as a single mailbox."
        ),
    )


@router.patch(
    "/{key_id}/owner",
    dependencies=[require_mfa_step_up(), require_scope("admin")],
)
def set_key_owner(
    key_id: str,
    payload: OwnerEmailRequest,
    request: Request,
    dry_run: bool = dry_run_query(),
    _: str = require_role("admin"),
):
    """Set or clear the accountable owner mailbox for an API key.

    Returns 404 for unknown ids or keys belonging to another tenant so
    admins cannot probe ids across workspaces. Returns 422 when the
    submitted email is not a syntactically valid mailbox.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if dry_run:
        try:
            preview = api_keys_store.normalize_owner_email(
                payload.owner_email, required=False
            )
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
                "current_owner_email": record.owner_email,
                "new_owner_email": preview,
            },
        )
    try:
        record = api_keys_store.set_owner_email(
            key_id, tenant_id=tenant_id, owner_email=payload.owner_email
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if record is None:
        raise HTTPException(404, "API key not found.")
    request.state.audit_target_id = record.id
    return {"key": record.to_dict()}


@router.get("/expiring", dependencies=[require_scope("admin")])
def list_expiring_keys(
    request: Request,
    within_days: int = Query(
        30,
        ge=0,
        le=365,
        description=(
            "Window in days. Active keys whose ``expires_at`` is on or "
            "before ``now + within_days`` are returned, soonest-first. "
            "Already-expired (but not yet revoked) keys are always "
            "included so an overdue rotation cannot be hidden by a "
            "short window."
        ),
    ),
    _: str = require_role("admin"),
):
    """List active keys expiring inside a rolling window.

    Drives the admin console "expiring credentials" widget so security
    teams can plan rotations before a key silently dies in production.
    Tenant-scoped: a workspace admin can never enumerate another
    workspace's credential lifecycle, and a cross-tenant admin
    (``X-Tenant: *``) sees every tenant's expiring keys for the global
    rotation queue.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    records = api_keys_store.list_expiring(
        tenant_id=tenant_id, within_days=within_days
    )
    return {
        "tenant_id": tenant_id,
        "within_days": within_days,
        "count": len(records),
        "keys": [r.to_dict() for r in records],
    }


@router.get("/unowned", dependencies=[require_scope("admin")])
def list_unowned_keys(
    request: Request,
    _: str = require_role("admin"),
):
    """List active keys missing an accountable owner.

    Drives the admin console "unowned credentials" widget that surfaces
    keys created before the ``owner_email`` migration plus any newer
    keys whose owner was explicitly cleared. Tenant-scoped so one
    workspace can never enumerate another workspace's grandfathered
    keys.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    records = api_keys_store.list_unowned(tenant_id=tenant_id)
    return {
        "tenant_id": tenant_id,
        "count": len(records),
        "keys": [r.to_dict() for r in records],
    }
