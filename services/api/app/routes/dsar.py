"""Data Subject Access Requests (DSAR) -- GDPR Articles 12-22, CCPA 1798.

Three surfaces share this router because procurement reviewers think
of them as one capability ("how do you handle data-subject requests?"):

* ``POST /v1/trust/dsar`` is **public** so an EU/CA data subject who is
  not a workspace member can submit a request without credentials. It
  follows the same unauthenticated pattern as ``/v1/trust/incidents``
  and ``/v1/trust/subprocessors``. The submitter MUST name the target
  workspace by ``tenant_id`` (vendors publish it on their privacy page).
* ``GET|POST /v1/dsar`` and ``GET|PATCH /v1/dsar/{id}`` are the
  tenant-scoped admin surfaces. Admin role + MFA step-up gate every
  mutation, and every mutation flows through ``AuditLogMiddleware`` so
  the actor, IP, request id, and timestamp land in the tamper-evident
  audit chain.
* ``GET /v1/dsar/{id}/footprint`` previews the rows in this workspace
  that match the data subject. It is read-only and used to size the
  payload before fulfillment.
* ``POST /v1/dsar/{id}/fulfill`` performs the Article 15 access export
  or Article 17 erasure. Erasure supports ``?dry_run=true``.

Every store call passes ``tenant_id`` explicitly. There is no global
query path; the only way to enumerate tickets is through the
authenticated, tenant-resolved admin endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from shotclassify_store import dsar_store
from shotclassify_store.dsar import (
    DsarNotFound,
    DsarStateError,
    DsarValidationError,
    STATUTORY_DEADLINE_DAYS,
    VALID_REQUEST_TYPES,
    VALID_STATUSES,
)

from ..dryrun import dry_run_query, mark_dry_run
from ..middleware.mfa import require_mfa_step_up
from ..middleware.rbac import require_role

router = APIRouter(tags=["dsar"])


def _tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            400, "No tenant resolved. Pass X-Tenant header to target a tenant."
        )
    return tenant_id


def _actor(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    if not principal:
        raise HTTPException(401, "Authenticated principal required.")
    return str(principal)


def _client_ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


# ---------------------------------------------------------------------------
# Public intake
# ---------------------------------------------------------------------------

@router.post("/v1/trust/dsar", status_code=201)
def submit_public_dsar(request: Request, payload: dict = Body(...)) -> dict:
    """Unauthenticated DSAR intake.

    A data subject (or their authorized agent) submits a request for
    access, erasure, or rectification of their personal data held by
    the named workspace. The vendor's admin then verifies, fulfills,
    and closes the ticket.
    """
    if not isinstance(payload, dict):
        raise HTTPException(422, "Body must be a JSON object.")
    tenant_id = payload.get("tenant_id")
    request_type = payload.get("request_type")
    subject_email = payload.get("subject_email")
    subject_name = payload.get("subject_name")
    description = payload.get("description")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise HTTPException(422, "'tenant_id' is required (string).")
    if not isinstance(request_type, str):
        raise HTTPException(422, "'request_type' is required (string).")
    if not isinstance(subject_email, str):
        raise HTTPException(422, "'subject_email' is required (string).")
    if subject_name is not None and not isinstance(subject_name, str):
        raise HTTPException(422, "'subject_name' must be a string.")
    if description is not None and not isinstance(description, str):
        raise HTTPException(422, "'description' must be a string.")
    try:
        rec = dsar_store.create_request(
            tenant_id=tenant_id.strip(),
            request_type=request_type,
            subject_email=subject_email,
            subject_name=subject_name,
            description=description,
            submitted_via="public",
            submitted_ip=_client_ip(request),
            actor=subject_email.strip(),
        )
    except DsarValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Public response intentionally narrow: ticket id + acknowledgement.
    # The full record is only visible to authenticated admins of the
    # target workspace so a stranger cannot enumerate prior requests.
    return {
        "id": rec["id"],
        "status": rec["status"],
        "received_at": rec["received_at"],
        "statutory_deadline": rec["statutory_deadline"],
        "tenant_id": rec["tenant_id"],
        "message": (
            "Your data subject request has been received. The workspace "
            "owner will verify your identity and respond within "
            f"{STATUTORY_DEADLINE_DAYS} days."
        ),
    }


# ---------------------------------------------------------------------------
# Admin surface: list, get, file-on-behalf, transition, footprint, fulfill
# ---------------------------------------------------------------------------

@router.get("/v1/dsar", dependencies=[require_role("admin")])
def list_dsar(request: Request, status: str | None = None, limit: int = 100) -> dict:
    tenant_id = _tenant(request)
    try:
        items = dsar_store.list_for_tenant(tenant_id, status=status, limit=limit)
    except DsarValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    stats = dsar_store.stats_for_tenant(tenant_id)
    return {
        "tenant_id": tenant_id,
        "items": items,
        "count": len(items),
        "stats": stats,
        "valid_statuses": list(VALID_STATUSES),
        "valid_request_types": list(VALID_REQUEST_TYPES),
    }


@router.post(
    "/v1/dsar",
    dependencies=[require_role("admin"), require_mfa_step_up()],
    status_code=201,
)
def admin_file_dsar(
    request: Request,
    payload: dict = Body(...),
    dry_run: bool = dry_run_query(),
) -> dict:
    """File a DSAR on behalf of a data subject (admin pathway)."""
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "Body must be a JSON object.")
    request_type = payload.get("request_type")
    subject_email = payload.get("subject_email")
    if not isinstance(request_type, str) or not isinstance(subject_email, str):
        raise HTTPException(
            422, "'request_type' and 'subject_email' are required (string)."
        )
    if dry_run:
        return mark_dry_run(
            request,
            would_create={
                "tenant_id": tenant_id,
                "request_type": request_type,
                "subject_email": subject_email,
            },
        )
    try:
        rec = dsar_store.create_request(
            tenant_id=tenant_id,
            request_type=request_type,
            subject_email=subject_email,
            subject_name=payload.get("subject_name"),
            description=payload.get("description"),
            submitted_via="admin",
            submitted_ip=_client_ip(request),
            actor=_actor(request),
        )
    except DsarValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    return rec


@router.get("/v1/dsar/{request_id}", dependencies=[require_role("admin")])
def get_dsar(request: Request, request_id: str) -> dict:
    tenant_id = _tenant(request)
    try:
        return dsar_store.get(tenant_id, request_id)
    except DsarNotFound as exc:
        raise HTTPException(404, "DSAR ticket not found.") from exc


@router.patch(
    "/v1/dsar/{request_id}",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def transition_dsar(
    request: Request,
    request_id: str,
    payload: dict = Body(...),
    dry_run: bool = dry_run_query(),
) -> dict:
    tenant_id = _tenant(request)
    if not isinstance(payload, dict):
        raise HTTPException(422, "Body must be a JSON object.")
    to_status = payload.get("status")
    if not isinstance(to_status, str):
        raise HTTPException(422, "'status' is required (string).")
    note = payload.get("note")
    assigned_to = payload.get("assigned_to")
    if note is not None and not isinstance(note, str):
        raise HTTPException(422, "'note' must be a string.")
    if assigned_to is not None and not isinstance(assigned_to, str):
        raise HTTPException(422, "'assigned_to' must be a string.")
    if dry_run:
        try:
            current = dsar_store.get(tenant_id, request_id)
        except DsarNotFound as exc:
            raise HTTPException(404, "DSAR ticket not found.") from exc
        return mark_dry_run(
            request,
            would_transition={
                "from": current["status"],
                "to": to_status,
                "id": request_id,
            },
        )
    try:
        return dsar_store.transition(
            tenant_id=tenant_id,
            request_id=request_id,
            to_status=to_status,
            actor=_actor(request),
            note=note,
            assigned_to=assigned_to,
        )
    except DsarNotFound as exc:
        raise HTTPException(404, "DSAR ticket not found.") from exc
    except DsarStateError as exc:
        raise HTTPException(409, str(exc)) from exc
    except DsarValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get(
    "/v1/dsar/{request_id}/footprint",
    dependencies=[require_role("admin")],
)
def footprint_dsar(request: Request, request_id: str) -> dict:
    tenant_id = _tenant(request)
    try:
        rec = dsar_store.get(tenant_id, request_id)
    except DsarNotFound as exc:
        raise HTTPException(404, "DSAR ticket not found.") from exc
    matches = dsar_store.scan_subject_footprint(
        tenant_id, rec["subject_identifier"]
    )
    return {
        "request_id": request_id,
        "tenant_id": tenant_id,
        "subject_identifier": rec["subject_identifier"],
        "matches": [m.to_dict() for m in matches],
        "total": sum(m.count for m in matches),
    }


@router.post(
    "/v1/dsar/{request_id}/fulfill",
    dependencies=[require_role("admin"), require_mfa_step_up()],
)
def fulfill_dsar(
    request: Request,
    request_id: str,
    dry_run: bool = dry_run_query(),
) -> dict:
    tenant_id = _tenant(request)
    try:
        rec = dsar_store.get(tenant_id, request_id)
    except DsarNotFound as exc:
        raise HTTPException(404, "DSAR ticket not found.") from exc
    actor = _actor(request)
    rtype = rec["request_type"]
    try:
        if rtype == "access":
            if dry_run:
                matches = dsar_store.scan_subject_footprint(
                    tenant_id, rec["subject_identifier"]
                )
                return mark_dry_run(
                    request,
                    would_export={m.table: m.count for m in matches},
                )
            return dsar_store.fulfill_access(
                tenant_id=tenant_id,
                request_id=request_id,
                actor=actor,
            )
        if rtype == "erasure":
            return dsar_store.fulfill_erasure(
                tenant_id=tenant_id,
                request_id=request_id,
                actor=actor,
                dry_run=dry_run,
            )
        raise HTTPException(
            422,
            f"Automated fulfillment for request_type={rtype!r} is not "
            "supported; transition the ticket manually.",
        )
    except DsarStateError as exc:
        raise HTTPException(409, str(exc)) from exc
    except DsarValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
