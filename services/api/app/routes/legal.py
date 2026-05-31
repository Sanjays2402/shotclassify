"""Trust Center: legal agreement catalog and per-tenant acceptance ledger.

Endpoints:

* ``GET /v1/trust/legal`` - public catalog of TOS, DPA, AUP bodies with
  their current version hashes. No auth required; procurement reviewers
  must be able to read these before they have credentials.
* ``GET /v1/trust/legal/status`` - admin view: per-agreement acceptance
  state for the caller workspace, plus the enforcement flag and the list
  of required agreements still missing.
* ``GET /v1/trust/legal/ledger`` - admin view: full append-only
  acceptance history for the caller workspace.
* ``POST /v1/trust/legal/accept`` - admin + MFA step-up: record an
  acceptance for a single agreement at a specific version.
* ``PUT /v1/trust/legal/enforcement`` - admin + MFA step-up: toggle the
  workspace-wide gate that blocks mutating /v1 routes until all required
  agreements have a current acceptance.

Every mutating route here is picked up by the audit middleware so the
actor, IP, user agent, and request id land in the tamper-evident audit
chain automatically.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from shotclassify_store import legal_agreements_store

from ..dryrun import dry_run_query, mark_dry_run
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


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid:
        return rid
    hdr = request.headers.get("x-request-id")
    return hdr or None


def _actor(request: Request) -> str:
    actor = getattr(request.state, "principal", None)
    if not actor:
        raise HTTPException(401, "Authenticated principal required.")
    return str(actor)


@router.get("/legal")
def list_legal_public() -> dict:
    """Public catalog. No auth required.

    Returned bodies are the exact text used to derive the version hash.
    A reviewer with no account can fetch this to start a procurement
    review.
    """
    return legal_agreements_store.list_catalog()


@router.get(
    "/legal/status",
    dependencies=[require_role("admin")],
)
def get_status_route(request: Request) -> dict:
    tenant_id = _tenant(request)
    return legal_agreements_store.status_for(tenant_id)


@router.get(
    "/legal/ledger",
    dependencies=[require_role("admin")],
)
def get_ledger_route(request: Request, limit: int = 200) -> dict:
    tenant_id = _tenant(request)
    if not isinstance(limit, int) or limit < 1 or limit > 1000:
        raise HTTPException(422, "limit must be an integer between 1 and 1000.")
    entries = legal_agreements_store.list_ledger(tenant_id, limit=limit)
    return {
        "tenant_id": tenant_id,
        "count": len(entries),
        "entries": [e.to_dict() for e in entries],
    }


@router.post(
    "/legal/accept",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def post_accept_route(request: Request, payload: dict = Body(...)) -> dict:
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "Body must be a JSON object.")
    agreement_id = payload.get("agreement_id")
    version = payload.get("version")
    if not isinstance(agreement_id, str) or not agreement_id.strip():
        raise HTTPException(422, "Field 'agreement_id' is required (string).")
    if not isinstance(version, str) or not version.strip():
        raise HTTPException(422, "Field 'version' is required (string).")
    try:
        acceptance = legal_agreements_store.accept(
            tenant_id,
            agreement_id.strip(),
            version.strip(),
            accepted_by=_actor(request),
            accepted_ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            request_id=_request_id(request),
        )
    except ValueError as exc:
        msg = str(exc)
        status = 409 if "no longer current" in msg else 422
        raise HTTPException(status, msg)
    return {
        "tenant_id": tenant_id,
        "acceptance": acceptance.to_dict(),
        "status": legal_agreements_store.status_for(tenant_id),
    }


@router.put(
    "/legal/enforcement",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def put_enforcement_route(
    request: Request,
    payload: dict = Body(...),
    dry_run: bool = dry_run_query(),
):
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "Body must be a JSON object.")
    enforce = payload.get("enforce")
    if not isinstance(enforce, bool):
        raise HTTPException(422, "Field 'enforce' is required (boolean).")
    if enforce:
        # Fail closed: refuse to arm the gate while required acceptances
        # are missing, otherwise the workspace immediately locks itself
        # out of every mutating route.
        missing = legal_agreements_store.gate_blocks(tenant_id)
        status = legal_agreements_store.status_for(tenant_id)
        if status["missing_required"]:
            raise HTTPException(
                409,
                "Cannot enable enforcement while required agreements are "
                "unaccepted: " + ", ".join(status["missing_required"]),
            )
        # gate_blocks returns None if enforce is currently off; the real
        # check is missing_required above.
        del missing
    if dry_run:
        return mark_dry_run(
            request,
            would_set={"tenant_id": tenant_id, "enforce": enforce},
            status=legal_agreements_store.status_for(tenant_id),
        )
    policy = legal_agreements_store.set_enforcement(
        tenant_id, enforce=enforce, updated_by=_actor(request)
    )
    return {
        "tenant_id": tenant_id,
        "enforcement": policy.to_dict(),
        "status": legal_agreements_store.status_for(tenant_id),
    }
