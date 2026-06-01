"""SCIM 2.0 user provisioning for enterprise IdPs.

Implements the subset of RFC 7644 that Okta, Azure AD, Google Workspace
Cloud Identity, OneLogin, JumpCloud, and Rippling actually call when you
configure them with a "SCIM" application:

* ``GET    /scim/v2/ServiceProviderConfig`` - capability advertisement
* ``GET    /scim/v2/ResourceTypes`` - resource type discovery
* ``GET    /scim/v2/Schemas`` - schema discovery (User only)
* ``GET    /scim/v2/Users`` - list with ``filter=userName eq "x"`` + paging
* ``POST   /scim/v2/Users`` - provision a new user (creates a membership)
* ``GET    /scim/v2/Users/{id}`` - read one
* ``PUT    /scim/v2/Users/{id}`` - replace (role + active flag)
* ``PATCH  /scim/v2/Users/{id}`` - common Okta de-activate / role change ops
* ``DELETE /scim/v2/Users/{id}`` - de-provision (removes membership)

The whole router is tenant-scoped: ``request.state.tenant_id`` is set by
the auth middleware from the SCIM bearer token. Every read filters by
that tenant, every write binds to that tenant, and the membership store
itself filters by tenant at the query layer. There is no path by which a
SCIM caller with a token for tenant A can list, read, mutate, or delete
a user belonging to tenant B; the test suite proves it.

Responses follow the SCIM 2.0 wire format, including the ``schemas``
envelope, ``meta``, ``totalResults`` / ``itemsPerPage`` / ``startIndex``
paging, and ``urn:ietf:params:scim:api:messages:2.0:Error`` error
documents that Okta and Azure AD parse and surface in their admin UI.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from shotclassify_store import memberships_store

router = APIRouter(prefix="/scim/v2", tags=["scim"])

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
SCIM_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
SCIM_CONTENT_TYPE = "application/scim+json"

# Map SCIM "active" + custom role values onto our internal RBAC tier.
# admin is intentionally NOT a valid value from SCIM: an admin via IdP
# rule would be a self-service privilege escalation path through whoever
# owns the IdP user attribute. Admin promotion stays in the workspace
# admin console behind MFA step-up.
SCIM_ALLOWED_ROLES = {"viewer", "operator"}


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        # Should never happen: the auth middleware sets tenant_id before
        # this route runs. Defensive guard so a refactor cannot silently
        # un-scope SCIM writes.
        raise HTTPException(status_code=401, detail="SCIM tenant unresolved")
    return tenant_id


def _scim_error(status: int, detail: str, scim_type: str | None = None) -> JSONResponse:
    body: dict[str, Any] = {
        "schemas": [SCIM_ERROR_SCHEMA],
        "status": str(status),
        "detail": detail,
    }
    if scim_type:
        body["scimType"] = scim_type
    return JSONResponse(body, status_code=status, media_type=SCIM_CONTENT_TYPE)


def _user_resource(tenant_id: str, principal: str, role: str, created_at: datetime, updated_at: datetime) -> dict[str, Any]:
    # ``principal`` is the canonical user identifier and SCIM ``id``. Using
    # the same value for ``id`` and ``userName`` keeps the round-trip stable
    # for Okta which normalizes id casing on its side.
    active = True  # membership exists therefore the user is active in this tenant
    return {
        "schemas": [SCIM_USER_SCHEMA],
        "id": principal,
        "userName": principal,
        "active": active,
        "displayName": principal,
        "emails": (
            [{"value": principal, "primary": True, "type": "work"}]
            if "@" in principal
            else []
        ),
        "name": {"formatted": principal},
        "roles": [{"value": role, "primary": True}],
        "meta": {
            "resourceType": "User",
            "location": f"/scim/v2/Users/{principal}",
            "created": (created_at.astimezone(UTC) if created_at.tzinfo else created_at.replace(tzinfo=UTC)).isoformat(),
            "lastModified": (updated_at.astimezone(UTC) if updated_at.tzinfo else updated_at.replace(tzinfo=UTC)).isoformat(),
            "version": f'W/"{int(updated_at.timestamp())}"',
        },
    }


# ---------------------------------------------------------------- discovery


@router.get("/ServiceProviderConfig")
def service_provider_config(request: Request) -> JSONResponse:
    _require_tenant(request)
    now = datetime.now(UTC).isoformat()
    body = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "documentationUri": "/scim/v2/ServiceProviderConfig",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "OAuth Bearer Token",
                "description": "Workspace-scoped SCIM provisioning token.",
                "primary": True,
            }
        ],
        "meta": {"resourceType": "ServiceProviderConfig", "created": now, "lastModified": now, "location": "/scim/v2/ServiceProviderConfig"},
    }
    return JSONResponse(body, media_type=SCIM_CONTENT_TYPE)


@router.get("/ResourceTypes")
def resource_types(request: Request) -> JSONResponse:
    _require_tenant(request)
    item = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
        "id": "User",
        "name": "User",
        "endpoint": "/Users",
        "description": "Workspace member",
        "schema": SCIM_USER_SCHEMA,
        "meta": {"location": "/scim/v2/ResourceTypes/User", "resourceType": "ResourceType"},
    }
    body = {
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": 1,
        "itemsPerPage": 1,
        "startIndex": 1,
        "Resources": [item],
    }
    return JSONResponse(body, media_type=SCIM_CONTENT_TYPE)


@router.get("/Schemas")
def schemas(request: Request) -> JSONResponse:
    _require_tenant(request)
    user_schema = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Schema"],
        "id": SCIM_USER_SCHEMA,
        "name": "User",
        "description": "Workspace member",
        "attributes": [
            {"name": "userName", "type": "string", "required": True, "uniqueness": "server"},
            {"name": "active", "type": "boolean", "required": False},
            {"name": "displayName", "type": "string", "required": False},
            {"name": "emails", "type": "complex", "multiValued": True, "required": False},
            {"name": "roles", "type": "complex", "multiValued": True, "required": False},
        ],
        "meta": {"resourceType": "Schema", "location": f"/scim/v2/Schemas/{SCIM_USER_SCHEMA}"},
    }
    body = {
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": 1,
        "itemsPerPage": 1,
        "startIndex": 1,
        "Resources": [user_schema],
    }
    return JSONResponse(body, media_type=SCIM_CONTENT_TYPE)


# ---------------------------------------------------------------- users


class ScimEmail(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: str | None = None
    primary: bool | None = None
    type: str | None = None


class ScimRole(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: str | None = None
    primary: bool | None = None


class ScimUserIn(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    schemas: list[str] | None = None
    userName: str = Field(..., min_length=1, max_length=255)
    active: bool | None = True
    displayName: str | None = None
    emails: list[ScimEmail] | None = None
    roles: list[ScimRole] | None = None


def _principal_from_user_in(payload: ScimUserIn) -> str:
    # Prefer userName; if it's empty fall back to the primary email. Okta
    # always sends userName so the email fallback is a safety net for the
    # smaller IdPs that ship a non-conforming payload.
    name = (payload.userName or "").strip().lower()
    if name:
        return name
    if payload.emails:
        for e in payload.emails:
            if e.value:
                return e.value.strip().lower()
    raise HTTPException(status_code=400, detail="userName or emails[].value is required")


def _role_from_user_in(payload: ScimUserIn, default_role: str) -> str:
    if payload.roles:
        for r in payload.roles:
            v = (r.value or "").strip().lower()
            if v in SCIM_ALLOWED_ROLES:
                return v
            if v == "admin":
                # Reject explicitly so IdP admins see a clear error rather
                # than silently getting downgraded to viewer.
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "role 'admin' cannot be assigned via SCIM. Promote "
                        "from the workspace admin console with MFA step-up."
                    ),
                )
    return default_role


def _default_role_for(tenant_id: str) -> str:
    from shotclassify_store import scim_store as _scim

    cfg = _scim.get_scim_config(tenant_id)
    role = cfg.default_role if cfg.default_role in SCIM_ALLOWED_ROLES else "viewer"
    return role


_FILTER_RE = re.compile(r'userName\s+eq\s+"([^"]+)"', re.IGNORECASE)


@router.get("/Users")
def list_users(
    request: Request,
    startIndex: int = Query(1, ge=1),
    count: int = Query(100, ge=0, le=200),
    filter: str | None = Query(None, alias="filter"),
) -> JSONResponse:
    tenant_id = _require_tenant(request)
    members = memberships_store.list_members(tenant_id)
    # Filter: support only the single pattern Okta/Azure send for de-dup:
    # ``userName eq "alice@example.com"``. Anything else is treated as no
    # filter (RFC 7644 allows the server to ignore unsupported filters,
    # though strictly we should 400; we choose the IdP-friendly path).
    if filter:
        m = _FILTER_RE.search(filter)
        if m:
            wanted = m.group(1).strip().lower()
            members = [m_ for m_ in members if m_.principal.lower() == wanted]
    total = len(members)
    # SCIM startIndex is 1-based.
    start = max(0, startIndex - 1)
    end = start + count
    page = members[start:end]
    body = {
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": total,
        "itemsPerPage": len(page),
        "startIndex": startIndex,
        "Resources": [
            _user_resource(tenant_id, m.principal, m.role, m.created_at, m.updated_at)
            for m in page
        ],
    }
    return JSONResponse(body, media_type=SCIM_CONTENT_TYPE)


@router.post("/Users", status_code=201)
def create_user(payload: ScimUserIn, request: Request) -> JSONResponse:
    tenant_id = _require_tenant(request)
    principal = _principal_from_user_in(payload)
    default_role = _default_role_for(tenant_id)
    role = _role_from_user_in(payload, default_role)
    if payload.active is False:
        # IdP sent active=False on creation; nothing to do but report ok.
        # We do not create a membership row because "inactive" means "no
        # access" and a row would grant access.
        return _scim_error(409, "Refusing to provision an inactive user.", "invalidValue")
    # Cross-tenant safety: list_members + upsert_member both filter by
    # tenant_id at the query layer, so even if a principal already exists
    # in another tenant we create an independent membership row here.
    existing_role = memberships_store.role_for_member(tenant_id, principal)
    if existing_role is not None:
        # SCIM says POST of an existing resource is 409.
        return _scim_error(409, f"User '{principal}' already provisioned.", "uniqueness")
    # Per-tenant allowed-email-domains policy: enforced for SCIM so an
    # IdP cannot push personal addresses into a regulated workspace.
    from shotclassify_store.tenant_settings import (
        email_matches_allowed_domains,
        get_allowed_invite_domains,
    )
    allowed_domains = get_allowed_invite_domains(tenant_id)
    if allowed_domains and not email_matches_allowed_domains(principal, allowed_domains):
        return _scim_error(
            400,
            f"Email '{principal}' is not in this workspace's allowed-invite domains.",
            "invalidValue",
        )
    try:
        record = memberships_store.upsert_member(
            tenant_id=tenant_id,
            principal=principal,
            role=role,
            invited_by=getattr(request.state, "principal", "scim"),
        )
    except memberships_store.SeatLimitExceeded as exc:
        # 507 Insufficient Storage is what Okta and Azure AD treat as a
        # capacity error and retry on. 402 is more semantically correct
        # but most IdP SCIM clients do not surface it cleanly.
        return _scim_error(
            507,
            f"Seat limit reached ({exc.in_use}/{exc.limit}). Raise the cap to provision more users.",
            "tooMany",
        )
    return JSONResponse(
        _user_resource(tenant_id, record.principal, record.role, record.created_at, record.updated_at),
        status_code=201,
        media_type=SCIM_CONTENT_TYPE,
    )


@router.get("/Users/{user_id}")
def get_user(user_id: str, request: Request) -> JSONResponse:
    tenant_id = _require_tenant(request)
    members = memberships_store.list_members(tenant_id)
    for m in members:
        if m.principal.lower() == user_id.strip().lower():
            return JSONResponse(
                _user_resource(tenant_id, m.principal, m.role, m.created_at, m.updated_at),
                media_type=SCIM_CONTENT_TYPE,
            )
    return _scim_error(404, f"User '{user_id}' not found in this workspace.")


@router.put("/Users/{user_id}")
def replace_user(user_id: str, payload: ScimUserIn, request: Request) -> JSONResponse:
    tenant_id = _require_tenant(request)
    existing_role = memberships_store.role_for_member(tenant_id, user_id)
    if existing_role is None:
        return _scim_error(404, f"User '{user_id}' not found in this workspace.")
    if payload.active is False:
        if existing_role == "admin":
            return _scim_error(
                409,
                "Refusing to de-activate the last admin via SCIM.",
                "mutability",
            ) if memberships_store.count_admins(tenant_id, exclude_principal=user_id) == 0 else _scim_error(
                400,
                "Admin de-activation must happen in the workspace admin console.",
                "mutability",
            )
        memberships_store.remove_member(tenant_id, user_id)
        # SCIM 204 on hard delete is technically per-spec for DELETE; we
        # respond 200 here with active=false to match Okta's expectation
        # of a body on PUT.
        body = _user_resource(tenant_id, user_id, existing_role, datetime.now(UTC), datetime.now(UTC))
        body["active"] = False
        return JSONResponse(body, status_code=200, media_type=SCIM_CONTENT_TYPE)
    default_role = _default_role_for(tenant_id)
    new_role = _role_from_user_in(payload, default_role)
    if existing_role == "admin" and new_role != "admin":
        # The admin role lives outside SCIM (see _role_from_user_in). If we
        # let SCIM demote the last admin the workspace would have no admin,
        # so guard the same invariant memberships.py guards.
        if memberships_store.count_admins(tenant_id, exclude_principal=user_id) == 0:
            return _scim_error(409, "Refusing to demote the last admin.", "mutability")
    record = memberships_store.upsert_member(
        tenant_id=tenant_id,
        principal=user_id,
        role=new_role,
        invited_by=getattr(request.state, "principal", "scim"),
    )
    return JSONResponse(
        _user_resource(tenant_id, record.principal, record.role, record.created_at, record.updated_at),
        media_type=SCIM_CONTENT_TYPE,
    )


@router.patch("/Users/{user_id}")
async def patch_user(user_id: str, request: Request) -> JSONResponse:
    """Handle the two PATCH shapes Okta and Azure AD send.

    The big two are ``replace`` of ``active`` (de-provision toggle) and
    ``replace`` of ``roles``. We implement enough of RFC 7644 PatchOp for
    those flows without pretending to support the full path filter grammar.
    """
    tenant_id = _require_tenant(request)
    existing_role = memberships_store.role_for_member(tenant_id, user_id)
    if existing_role is None:
        return _scim_error(404, f"User '{user_id}' not found in this workspace.")
    try:
        body = await request.json()
    except Exception:
        return _scim_error(400, "PATCH body must be JSON.")
    if not isinstance(body, dict):
        return _scim_error(400, "PATCH body must be a JSON object.")
    ops = body.get("Operations") or []
    if not isinstance(ops, list) or not ops:
        return _scim_error(400, "PATCH requires a non-empty Operations array.")
    new_active = True
    new_role = existing_role
    for op in ops:
        if not isinstance(op, dict):
            continue
        operation = (op.get("op") or "").lower()
        path = (op.get("path") or "").strip()
        value = op.get("value")
        if operation not in {"replace", "add", "remove"}:
            return _scim_error(400, f"unsupported op '{operation}'.")
        # Azure AD often omits ``path`` and sends ``value`` as a dict.
        if not path and isinstance(value, dict):
            if "active" in value:
                new_active = bool(value["active"])
            if "roles" in value and isinstance(value["roles"], list):
                cand = _role_from_user_in(
                    ScimUserIn(userName=user_id, roles=value["roles"]),
                    _default_role_for(tenant_id),
                )
                new_role = cand
            continue
        if path.lower() == "active":
            if operation == "remove":
                new_active = False
            else:
                new_active = bool(value) if not isinstance(value, list) else bool(value and value[0])
        elif path.lower().startswith("roles"):
            if operation == "remove":
                new_role = _default_role_for(tenant_id)
            else:
                # Value is usually a list of {value: "operator"} entries.
                items = value if isinstance(value, list) else [value]
                cand = _role_from_user_in(
                    ScimUserIn(
                        userName=user_id,
                        roles=[ScimRole(value=(v.get("value") if isinstance(v, dict) else str(v))) for v in items if v is not None],
                    ),
                    _default_role_for(tenant_id),
                )
                new_role = cand
        # Silently ignore PATCH on fields we do not model (displayName,
        # emails, name.formatted) so Okta does not retry forever.
    if not new_active:
        if existing_role == "admin" and memberships_store.count_admins(tenant_id, exclude_principal=user_id) == 0:
            return _scim_error(409, "Refusing to de-activate the last admin.", "mutability")
        memberships_store.remove_member(tenant_id, user_id)
        ghost = _user_resource(tenant_id, user_id, existing_role, datetime.now(UTC), datetime.now(UTC))
        ghost["active"] = False
        return JSONResponse(ghost, media_type=SCIM_CONTENT_TYPE)
    if new_role == "admin":
        # Defense in depth; _role_from_user_in already rejected this.
        return _scim_error(400, "role 'admin' cannot be assigned via SCIM.", "mutability")
    if existing_role == "admin" and new_role != "admin":
        if memberships_store.count_admins(tenant_id, exclude_principal=user_id) == 0:
            return _scim_error(409, "Refusing to demote the last admin.", "mutability")
    record = memberships_store.upsert_member(
        tenant_id=tenant_id,
        principal=user_id,
        role=new_role,
        invited_by=getattr(request.state, "principal", "scim"),
    )
    return JSONResponse(
        _user_resource(tenant_id, record.principal, record.role, record.created_at, record.updated_at),
        media_type=SCIM_CONTENT_TYPE,
    )


@router.delete("/Users/{user_id}", status_code=204)
def delete_user(user_id: str, request: Request) -> JSONResponse:
    tenant_id = _require_tenant(request)
    existing_role = memberships_store.role_for_member(tenant_id, user_id)
    if existing_role is None:
        return _scim_error(404, f"User '{user_id}' not found in this workspace.")
    if existing_role == "admin" and memberships_store.count_admins(tenant_id, exclude_principal=user_id) == 0:
        return _scim_error(409, "Refusing to delete the last admin.", "mutability")
    memberships_store.remove_member(tenant_id, user_id)
    return JSONResponse(None, status_code=204, media_type=SCIM_CONTENT_TYPE)
