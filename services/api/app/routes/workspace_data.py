"""Workspace-wide GDPR data lifecycle (admin only).

Per-user export and erasure already exists at ``/v1/me/data``. This module
exposes the workspace owner equivalents at ``/v1/workspace/data``:

* ``GET  /v1/workspace/data``  -- export everything in the workspace as a
  single ZIP bundle (manifest.json + classifications.json +
  audit_log.json + saved_views.json + members.json + api_keys.json,
  retention policy, sso config, ip allowlist).
* ``DELETE /v1/workspace/data?confirm=erase`` -- hard-delete every
  classification, saved view, audit row, and stored blob for the
  workspace. Memberships, API keys, SSO config, and IP allowlist are
  preserved so the admin can still log in afterwards; explicit workspace
  teardown is intentionally out of scope here.

Both endpoints require:

* ``admin`` role (enforced via ``require_role``)
* TOTP MFA step-up (enforced via ``require_mfa_step_up``)
* a resolved tenant on ``request.state.tenant_id``

Mutations are audited by the global ``AuditLogMiddleware``; the response
body of the delete endpoint includes the counts that were removed so the
admin has an immediate receipt.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from shotclassify_store import (
    AuditRepository,
    LegalHoldActive,
    Repository,
    SavedViewRepository,
    api_keys_store,
    get_ip_allowlist,
    get_retention_days,
    get_sso_config,
    legal_holds_store,
    memberships_store,
)

from ..middleware.mfa import require_mfa_step_up
from ..middleware.rbac import require_role

router = APIRouter(prefix="/v1/workspace", tags=["data-lifecycle"])


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=422,
            detail="A tenant context is required. Pass X-Tenant or sign in to a workspace.",
        )
    return tenant_id


def _collect_export(tenant_id: str, principal: str | None) -> dict[str, Any]:
    repo = Repository()
    audit = AuditRepository()
    views = SavedViewRepository()

    classifications = [
        r.model_dump(mode="json") for r in repo.list_by_tenant(tenant_id)
    ]
    audit_rows = audit.list_for_tenant(tenant_id)
    saved_views = views.list_by_tenant(tenant_id)
    members = [m.to_dict() for m in memberships_store.list_members(tenant_id)]
    invitations = [
        inv.to_dict()
        for inv in memberships_store.list_invitations(tenant_id, include_inactive=True)
    ]
    keys = [
        k.to_dict()
        for k in api_keys_store.list_keys(tenant_id=tenant_id, include_revoked=True)
    ]
    sso = get_sso_config(tenant_id)
    sso_dict = sso.to_dict() if hasattr(sso, "to_dict") else dict(sso.__dict__)
    # Don't ship the OIDC client secret in an export.
    if isinstance(sso_dict, dict):
        sso_dict.pop("client_secret", None)
    manifest = {
        "tenant_id": tenant_id,
        "exported_by": principal,
        "exported_at": datetime.now(UTC).isoformat(),
        "schema_version": 1,
        "counts": {
            "classifications": len(classifications),
            "audit_log": len(audit_rows),
            "saved_views": len(saved_views),
            "members": len(members),
            "invitations": len(invitations),
            "api_keys": len(keys),
        },
    }
    return {
        "manifest": manifest,
        "classifications": classifications,
        "audit_log": audit_rows,
        "saved_views": saved_views,
        "members": members,
        "invitations": invitations,
        "api_keys": keys,
        "settings": {
            "ip_allowlist": get_ip_allowlist(tenant_id),
            "retention_days": get_retention_days(tenant_id),
            "sso": sso_dict,
        },
    }


def _zip_bytes(payload: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(payload["manifest"], indent=2, default=str))
        for name in (
            "classifications",
            "audit_log",
            "saved_views",
            "members",
            "invitations",
            "api_keys",
        ):
            zf.writestr(
                f"{name}.json",
                json.dumps(payload[name], indent=2, default=str),
            )
        zf.writestr("settings.json", json.dumps(payload["settings"], indent=2, default=str))
    return buf.getvalue()


@router.get(
    "/data",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def export_workspace_data(
    request: Request,
    format: str = Query("zip", pattern="^(zip|json)$"),
) -> Any:
    tenant_id = _require_tenant(request)
    principal = getattr(request.state, "principal", None)
    payload = _collect_export(tenant_id, principal)
    if format == "json":
        return payload
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    filename = f"shotclassify-workspace-{tenant_id}-{stamp}.zip"
    body = _zip_bytes(payload)
    return StreamingResponse(
        io.BytesIO(body),
        media_type="application/zip",
        headers={
            "content-disposition": f'attachment; filename="{filename}"',
            "cache-control": "no-store",
            "x-export-rows": str(payload["manifest"]["counts"]["classifications"]),
        },
    )


@router.delete(
    "/data",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def delete_workspace_data(
    request: Request,
    confirm: str = Query(
        "",
        description="Must equal 'erase' to acknowledge the destructive operation.",
    ),
    dry_run: bool = Query(
        False,
        description="When true, return the counts that would be deleted without mutating.",
    ),
) -> dict[str, Any]:
    if not dry_run and confirm != "erase":
        raise HTTPException(
            status_code=400,
            detail="Pass ?confirm=erase to permanently delete every record in this workspace.",
        )
    tenant_id = _require_tenant(request)

    repo = Repository()
    audit = AuditRepository()
    views = SavedViewRepository()

    if dry_run:
        return {
            "dry_run": True,
            "tenant_id": tenant_id,
            "would_delete": {
                "classifications": len(repo.list_by_tenant(tenant_id)),
                "audit_log": len(audit.list_for_tenant(tenant_id)),
                "saved_views": len(views.list_by_tenant(tenant_id)),
            },
            "preserved": ["memberships", "api_keys", "sso", "ip_allowlist"],
            "legal_hold": {
                "active": legal_holds_store.tenant_has_active_hold(tenant_id),
                "matters": legal_holds_store.active_hold_matters(tenant_id),
            },
        }

    try:
        classifications_removed = repo.delete_by_tenant(tenant_id)
    except LegalHoldActive as exc:
        raise HTTPException(
            status_code=423,
            detail={
                "error": "legal_hold_active",
                "message": (
                    "Workspace is under legal hold; lift all active holds "
                    "before deleting workspace data."
                ),
                "matters": exc.matters,
            },
        )
    saved_views_removed = views.delete_by_tenant(tenant_id)
    # Delete audit rows LAST so the audit row this very request writes via
    # AuditLogMiddleware (on response) survives in the new empty log. We
    # accept that the in-flight audit row gets wiped along with the rest;
    # the immutable receipt is the JSON response the admin sees.
    audit_removed = audit.delete_for_tenant(tenant_id)
    return {
        "tenant_id": tenant_id,
        "deleted": {
            "classifications": classifications_removed,
            "audit_log": audit_removed,
            "saved_views": saved_views_removed,
        },
        "preserved": ["memberships", "api_keys", "sso", "ip_allowlist"],
    }
