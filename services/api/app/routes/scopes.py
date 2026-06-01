"""Scope catalog and credential introspection.

Why this exists: enterprise procurement reviewers (and the IAM auditors
they hire) want two things from any API platform:

1. A machine-readable enumeration of *every* permission the API can
   issue, so they can map credentials to risk.
2. An RFC 7662 style introspection endpoint that, given the credential
   you are actually sending, tells you what it can do, who it belongs
   to, and when it expires, so SOC teams can validate "least
   privilege" claims without trusting client-side bookkeeping.

Both routes are tenant-scoped. ``/v1/scopes`` is the same for every
caller (the catalog is static) but it still requires authentication so
unauthenticated probers cannot map the permission surface.
``/v1/auth/introspect`` returns *only* the calling principal; it never
accepts a token parameter because we deliberately do not want a route
that resolves arbitrary tokens (that would itself be a credential
oracle).
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from shotclassify_store import (
    SCOPE_CATALOG,
    api_keys_store,
    describe_scopes,
)


router = APIRouter(tags=["scopes"])


@router.get("/v1/scopes")
def list_scopes(request: Request) -> dict:
    """Return the full permission catalog.

    The response is stable across tenants and is safe to cache for the
    lifetime of an API version. Clients use this to render scope
    pickers, populate access-review reports, and validate that a
    credential they are about to mint actually exists.
    """
    if not getattr(request.state, "principal", None):
        # Auth middleware should already have enforced this, but be
        # explicit so a future routing change cannot accidentally make
        # the catalog anonymous-readable.
        raise HTTPException(401, "Authentication required.")
    return {
        "version": 1,
        "scopes": [s.to_dict() for s in SCOPE_CATALOG],
    }


@router.get("/v1/auth/introspect")
def introspect(request: Request) -> dict:
    """RFC 7662 style introspection for the calling credential.

    Returns the resolved principal, credential type, tenant binding,
    scopes (hydrated against the catalog so unknown legacy scopes are
    flagged), derived role, and lifecycle timestamps. This is what an
    SDK should call on startup to sanity-check that its key still has
    the scopes the application assumes.
    """
    principal = getattr(request.state, "principal", None)
    if not principal:
        # Mirror RFC 7662 ``{"active": false}`` for unauth probes so
        # clients can branch on a single field.
        return {"active": False}

    tenant_id = getattr(request.state, "tenant_id", None)
    raw_scopes = list(getattr(request.state, "auth_scopes", None) or [])
    role = getattr(request.state, "role", None)
    request_id = getattr(request.state, "request_id", None)

    credential: dict = {"type": "session"}
    api_key_id = getattr(request.state, "auth_api_key_id", None)
    if api_key_id:
        record = api_keys_store.get_by_id(api_key_id) if hasattr(api_keys_store, "get_by_id") else None
        credential = {
            "type": "api_key",
            "id": api_key_id,
            "tenant_id": getattr(request.state, "auth_api_key_tenant", None),
        }
        if record is not None:
            credential["label"] = record.label
            credential["created_at"] = (
                record.created_at.isoformat() if record.created_at else None
            )
            credential["last_used_at"] = (
                record.last_used_at.isoformat() if record.last_used_at else None
            )
            credential["expires_at"] = (
                record.expires_at.isoformat() if record.expires_at else None
            )
            credential["revoked_at"] = (
                record.revoked_at.isoformat() if record.revoked_at else None
            )
    elif getattr(request.state, "session_id", None):
        credential = {
            "type": "session",
            "id": request.state.session_id,
        }
    elif getattr(request.state, "auth_api_key", None):
        # Env-var legacy key. We do not expose the raw key id since there
        # isn't one; just acknowledge the credential class.
        credential = {"type": "api_key_legacy"}

    return {
        "active": True,
        "principal": principal,
        "tenant_id": tenant_id,
        "role": role,
        "scopes": raw_scopes,
        "scope_details": describe_scopes(raw_scopes),
        "credential": credential,
        "request_id": request_id,
        "checked_at": datetime.now(UTC).isoformat(),
    }
