"""Multi-factor authentication: TOTP enrollment and step-up.

Endpoints:

* ``GET  /v1/mfa/status``    - current enrollment + step-up state
* ``POST /v1/mfa/setup``     - begin (or restart) enrollment; returns secret + otpauth URI
* ``POST /v1/mfa/verify``    - confirm enrollment with a code from the authenticator
* ``POST /v1/mfa/challenge`` - step-up: prove possession of the factor now
* ``DELETE /v1/mfa``         - disable MFA for the caller (requires a fresh code)

All mutations are written through the audit middleware (it captures every
``/v1/...`` mutation), so MFA enrollment, removal, and step-up events
appear in the audit trail with actor, IP, and timestamp.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from shotclassify_store import mfa_store

from ..dryrun import dry_run_query, mark_dry_run
from ..middleware.mfa import require_mfa_step_up

router = APIRouter(prefix="/v1/mfa", tags=["mfa"])


def _require_human_principal(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    if not principal:
        raise HTTPException(401, "Not authenticated.")
    if principal == "api-key":
        raise HTTPException(
            status_code=400,
            detail="MFA enrollment is for human sessions. API keys carry their own secret.",
        )
    return principal


class VerifyCodeIn(BaseModel):
    code: str = Field(..., min_length=6, max_length=10, description="TOTP code from authenticator app.")


@router.get("/status")
def get_status(request: Request):
    principal = getattr(request.state, "principal", None)
    if not principal:
        raise HTTPException(401, "Not authenticated.")
    st = mfa_store.status(principal) if principal != "api-key" else mfa_store.MfaStatus(False, False, None, None, None)
    sid = getattr(request.state, "session_id", None)
    verified = mfa_store.session_mfa_verified_at(sid)
    recovery = (
        mfa_store.recovery_status(principal)
        if principal != "api-key"
        else mfa_store.RecoveryStatus(0, 0, None, None)
    )
    return {
        **st.to_dict(),
        "session_verified_at": verified.isoformat() if verified else None,
        "principal": principal,
        "recovery_codes": recovery.to_dict(),
    }


@router.post("/setup")
def setup(request: Request):
    """Begin enrollment. Returns the secret + otpauth URI to scan.

    Refuses to clobber an already-confirmed credential; call DELETE /v1/mfa
    first to rotate.
    """
    principal = _require_human_principal(request)
    try:
        return mfa_store.begin_enrollment(principal)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/verify")
def verify(body: VerifyCodeIn, request: Request):
    """Confirm the pending enrollment by submitting a current TOTP code."""
    principal = _require_human_principal(request)
    if not mfa_store.confirm_enrollment(principal, body.code):
        raise HTTPException(400, "Invalid code, or no pending enrollment.")
    # Confirming enrollment also satisfies the step-up freshness window so
    # the user can complete an admin action they were just prompted for
    # without re-entering a second code.
    sid = getattr(request.state, "session_id", None)
    if sid:
        mfa_store.verify_step_up(principal, body.code, session_id=sid)
    return {"ok": True, "confirmed_at": datetime.now(UTC).isoformat()}


@router.post("/challenge")
def challenge(body: VerifyCodeIn, request: Request):
    """Step-up: prove the second factor is present, stamp the session."""
    principal = _require_human_principal(request)
    sid = getattr(request.state, "session_id", None)
    if not sid:
        raise HTTPException(400, "No session to stamp.")
    if not mfa_store.verify_step_up(principal, body.code, session_id=sid):
        raise HTTPException(400, "Invalid code.")
    return {"ok": True, "verified_at": datetime.now(UTC).isoformat()}


@router.delete("")
def disable(body: VerifyCodeIn, request: Request, dry_run: bool = dry_run_query()):
    """Remove the MFA credential.

    Requires a current code so a stolen active session cannot silently
    drop the second factor.
    """
    principal = _require_human_principal(request)
    sid = getattr(request.state, "session_id", None)
    # Verify possession of the factor before allowing removal, even on
    # dry-runs. A preview path that skipped this check would let a
    # stolen session enumerate whether MFA is enabled without proving
    # possession of the factor.
    if not mfa_store.verify_step_up(principal, body.code, session_id=sid):
        raise HTTPException(400, "Invalid code.")
    if dry_run:
        return mark_dry_run(request, would_remove={"principal": principal})
    removed = mfa_store.disable(principal)
    return {"removed": removed}


class RecoveryConsumeIn(BaseModel):
    code: str = Field(..., min_length=4, max_length=32, description="A recovery code shown at generation time.")


@router.get("/recovery-codes")
def recovery_codes_status(request: Request):
    """Counts and timestamps for the caller's active recovery batch. No plaintext."""
    principal = _require_human_principal(request)
    return mfa_store.recovery_status(principal).to_dict()


@router.post("/recovery-codes", dependencies=[require_mfa_step_up()])
def regenerate_recovery_codes(request: Request, dry_run: bool = dry_run_query()):
    """Issue a fresh batch of single-use recovery codes.

    Requires a confirmed second factor and a fresh TOTP step-up (the
    existing ``mfa_verified_at`` window on the session). The previous
    batch is invalidated atomically. Plaintext codes are returned exactly
    once; the server only retains salted hashes.
    """
    principal = _require_human_principal(request)
    if not mfa_store.is_confirmed(principal):
        raise HTTPException(409, "Confirm MFA enrollment before generating recovery codes.")
    if dry_run:
        existing = mfa_store.recovery_status(principal)
        return mark_dry_run(
            request,
            would_replace_batch={
                "previous_total": existing.total,
                "previous_remaining": existing.remaining,
            },
            would_issue=mfa_store.RECOVERY_BATCH_SIZE,
        )
    try:
        result = mfa_store.regenerate_recovery_codes(principal)
    except ValueError as e:
        raise HTTPException(409, str(e))
    # Mark the audit extra so the log captures intent without exposing
    # plaintext codes.
    request.state.audit_extra = {
        "batch_id": result["batch_id"],
        "issued": len(result["codes"]),
    }
    return result


@router.post("/recovery")
def consume_recovery_code(body: RecoveryConsumeIn, request: Request):
    """Burn one recovery code; on success, stamps the session as MFA-verified.

    Use this when the authenticator app is unavailable. Each code works
    exactly once. After consumption you should rotate the batch from a
    secure device.
    """
    principal = _require_human_principal(request)
    sid = getattr(request.state, "session_id", None)
    if not sid:
        raise HTTPException(400, "No session to stamp.")
    ok = mfa_store.consume_recovery_code(principal, body.code, session_id=sid)
    if not ok:
        # Constant message; do not leak whether the principal has any
        # recovery codes outstanding.
        raise HTTPException(400, "Invalid recovery code.")
    remaining = mfa_store.recovery_status(principal).remaining
    request.state.audit_extra = {"remaining": remaining}
    return {
        "ok": True,
        "verified_at": datetime.now(UTC).isoformat(),
        "remaining": remaining,
    }
