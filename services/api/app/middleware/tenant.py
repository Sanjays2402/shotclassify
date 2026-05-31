"""Tenant resolution and scoping.

Every authenticated request is tagged with a ``tenant_id`` on
``request.state.tenant_id`` so route handlers and the repository layer can
scope reads and writes. The tenant is resolved in this order:

1. ``X-Tenant`` request header, when the caller is an ``admin``. Admins may
   pass ``*`` to opt into a cross-tenant view (returns ``None`` and disables
   scoping) or pass any tenant id to impersonate that tenant for read/write.
2. ``AUTH_TENANT_MAP`` JSON object ``{principal: tenant_id}``.
3. ``AUTH_DEFAULT_TENANT`` (defaults to ``\"default\"``).

The resolver runs as Starlette middleware so it can read settings once and
attach the resolved tenant before any route or audit hook fires.
"""
from __future__ import annotations

import json

import structlog
from shotclassify_common import get_settings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

log = structlog.get_logger(__name__)

# Sentinel used on request.state.tenant_id when an admin opted into a
# cross-tenant view via X-Tenant: *. The repository layer treats ``None`` as
# "do not scope".
CROSS_TENANT = None


def _safe_json_map(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and v}


def tenant_for_principal(principal: str | None) -> str:
    """Resolve the tenant id assigned to ``principal`` from settings."""
    s = get_settings()
    if principal:
        mapping = _safe_json_map(s.auth_tenant_map)
        if principal in mapping:
            return mapping[principal]
    return s.auth_default_tenant or "default"


class TenantResolutionMiddleware(BaseHTTPMiddleware):
    """Attach ``request.state.tenant_id`` after authentication."""

    async def dispatch(self, request: Request, call_next):
        principal = getattr(request.state, "principal", None)
        api_key = getattr(request.state, "auth_api_key", None)
        api_key_tenant = getattr(request.state, "auth_api_key_tenant", None)
        role = getattr(request.state, "role", None)
        s = get_settings()
        # Default tenant for unauthenticated/public paths is still set so any
        # downstream code that reads request.state.tenant_id never crashes.
        # For API key callers, look up by the actual key (the principal is
        # the generic literal "api-key"); for OAuth users, look up by login.
        lookup_key = api_key if api_key else principal
        resolved: str | None = tenant_for_principal(lookup_key)
        # SCIM bearer requests already pinned a tenant in the auth layer.
        # That binding is authoritative and not overridable by X-Tenant so a
        # leaked SCIM token cannot read another workspace by passing a
        # header.
        if getattr(request.state, "scim_authenticated", False):
            return await call_next(request)
        # DB-backed API keys carry a hard tenant binding. This takes
        # precedence over the env-var map and is NOT overridable by
        # X-Tenant, so a leaked key can never read across tenants.
        if api_key_tenant:
            request.state.tenant_id = api_key_tenant
            response = await call_next(request)
            try:
                from shotclassify_store import get_privacy_settings

                residency = get_privacy_settings(api_key_tenant).data_residency
                if residency:
                    response.headers["X-Data-Residency"] = residency
            except Exception:
                pass
            return response
        override = request.headers.get("x-tenant")
        if override and role == "admin":
            if override == "*":
                resolved = CROSS_TENANT
            else:
                target = override.strip()[:64]
                if target:
                    own_tenant = tenant_for_principal(principal)
                    # The legacy single-admin env-var key represents the
                    # owner of this deployment, not a multi-tenant SaaS
                    # support engineer. Preserve their cross-tenant access.
                    legacy_admin = bool(
                        api_key and s.auth_api_key and api_key == s.auth_api_key
                    )
                    if target != own_tenant and not legacy_admin:
                        # Cross-tenant admin scoping requires an active,
                        # tenant-issued support access grant. Without it
                        # we refuse the request rather than silently let
                        # the admin read or mutate the target workspace.
                        from shotclassify_store import support_access_store

                        grant = support_access_store.find_active(
                            target, admin_login=str(principal) if principal else None
                        )
                        if grant is None:
                            return JSONResponse(
                                status_code=403,
                                content={
                                    "detail": (
                                        "Cross-tenant access denied: target "
                                        "workspace has no active support "
                                        "access grant for this admin."
                                    ),
                                    "code": "support_access_required",
                                    "tenant_id": target,
                                },
                            )
                        # Pin the grant on the request so the audit log
                        # records which ticket authorized this action,
                        # and so the route layer can read it back.
                        request.state.support_access_grant_id = grant.id
                        request.state.support_access_grant_expires_at = (
                            grant.expires_at.isoformat()
                            if grant.expires_at
                            else None
                        )
                        # Merge into audit_extra so the audit middleware
                        # writes it to the immutable hash-chained log.
                        prev = getattr(request.state, "audit_extra", None) or {}
                        request.state.audit_extra = {
                            **prev,
                            "support_access_grant_id": grant.id,
                            "support_access_reason": grant.reason,
                            "cross_tenant_target": target,
                        }
                        try:
                            support_access_store.mark_used(grant.id)
                        except Exception as exc:  # pragma: no cover
                            log.warning(
                                "support_access_mark_used_failed",
                                grant_id=grant.id,
                                error=str(exc),
                            )
                    resolved = target
                else:
                    resolved = resolved
        request.state.tenant_id = resolved
        response = await call_next(request)
        # Echo the per-tenant data residency hint so procurement reviewers
        # can curl any endpoint and prove which region label is in effect
        # for their workspace. Empty / lookup failure means no header,
        # which is the same as today's behavior.
        if resolved:
            try:
                from shotclassify_store import get_privacy_settings

                residency = get_privacy_settings(resolved).data_residency
                if residency and "x-data-residency" not in {
                    k.decode().lower() if isinstance(k, bytes) else k.lower()
                    for k, _ in response.raw_headers
                }:
                    response.headers["X-Data-Residency"] = residency
            except Exception:
                pass
        return response
