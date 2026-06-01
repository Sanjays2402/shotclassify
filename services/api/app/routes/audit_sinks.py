"""Per-tenant audit log SIEM sink management.

Workspace admins use this surface to register HTTPS endpoints that
receive a signed copy of every audit row written by the
AuditLogMiddleware. This is the SOC2 / enterprise-procurement
integration buyers ask for so they can forward our trail into Splunk,
Datadog, Sumo Logic, or any HTTPS log collector.

Plaintext sink secrets are returned exactly once at creation and never
persisted; only the SHA-256 hash is stored, so a DB leak cannot be used
to forge audit events. Mutations require admin role + ``admin`` scope
and run through MFA step-up, and the audit middleware records every
call.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from shotclassify_common import get_settings
from shotclassify_store import audit_sinks_store

from ..dryrun import dry_run_query, mark_dry_run
from ..middleware.mfa import require_mfa_step_up
from ..middleware.rbac import require_role, require_scope

router = APIRouter(prefix="/v1/audit/sinks", tags=["audit-sinks"])


class CreateSinkRequest(BaseModel):
    url: str = Field(min_length=1, max_length=1024)
    description: str | None = Field(default=None, max_length=255)


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=422,
            detail="A tenant context is required for audit sinks. Pass X-Tenant.",
        )
    return tenant_id


@router.get("", dependencies=[require_role("admin"), require_scope("read:audit")])
def list_sinks(request: Request):
    tenant_id = _require_tenant(request)
    return {"sinks": [s.to_dict() for s in audit_sinks_store.list_sinks(tenant_id)]}


@router.post(
    "",
    dependencies=[require_role("admin"), require_scope("admin"), require_mfa_step_up()],
)
def create_sink(
    body: CreateSinkRequest,
    request: Request,
    dry_run: bool = dry_run_query(),
):
    tenant_id = _require_tenant(request)
    if dry_run:
        return mark_dry_run(
            request,
            would_create={"url": body.url, "description": body.description},
        )
    try:
        record, secret = audit_sinks_store.create_sink(
            tenant_id=tenant_id,
            url=body.url,
            description=body.description,
            created_by=getattr(request.state, "principal", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    payload = record.to_dict()
    # Plaintext secret shown exactly once; receiver computes
    # HMAC-SHA256(sha256(secret), body) against the raw request body to
    # verify each delivery.
    payload["secret"] = secret
    return payload


@router.get(
    "/{sink_id}", dependencies=[require_role("admin"), require_scope("read:audit")]
)
def get_sink(sink_id: str, request: Request):
    tenant_id = _require_tenant(request)
    sink = audit_sinks_store.get_sink(sink_id, tenant_id=tenant_id)
    if not sink:
        raise HTTPException(status_code=404, detail="Audit sink not found.")
    return sink.to_dict()


@router.delete(
    "/{sink_id}",
    dependencies=[require_role("admin"), require_scope("admin"), require_mfa_step_up()],
)
def revoke_sink(sink_id: str, request: Request, dry_run: bool = dry_run_query()):
    tenant_id = _require_tenant(request)
    sink = audit_sinks_store.get_sink(sink_id, tenant_id=tenant_id)
    if not sink:
        raise HTTPException(status_code=404, detail="Audit sink not found.")
    if dry_run:
        return mark_dry_run(request, would_revoke={"id": sink_id})
    audit_sinks_store.revoke_sink(sink_id, tenant_id=tenant_id)
    updated = audit_sinks_store.get_sink(sink_id, tenant_id=tenant_id)
    return (updated or sink).to_dict()


@router.post(
    "/{sink_id}/test",
    dependencies=[require_role("admin"), require_scope("admin"), require_mfa_step_up()],
)
def fire_test(sink_id: str, request: Request):
    tenant_id = _require_tenant(request)
    sink = audit_sinks_store.get_sink(sink_id, tenant_id=tenant_id)
    if not sink:
        raise HTTPException(status_code=404, detail="Audit sink not found.")
    s = get_settings()
    updated = audit_sinks_store.test_fire(
        sink_id,
        tenant_id=tenant_id,
        allow_http=s.webhook_egress_allow_http,
        allow_private=s.webhook_egress_allow_private,
        extra_blocked_cidrs=s.webhook_egress_extra_blocked_cidrs,
    )
    return (updated or sink).to_dict()
