"""MFA step-up enforcement for sensitive admin actions.

Use as a FastAPI dependency on any admin mutation that must require a
recent second factor. The dependency:

* Allows API-key callers through (machine-to-machine integrations get
  their own scoped key; MFA is a human-interaction control).
* Requires the cookie-authenticated principal to have a confirmed TOTP
  credential.
* Requires the current session to have a ``mfa_verified_at`` timestamp
  within the configured freshness window (default 15 minutes), set by
  POST ``/v1/mfa/challenge``.

On failure it returns ``401 mfa_required`` with the freshness window so
the UI can prompt the user for a code and re-attempt.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request
from shotclassify_store import mfa_store


def _step_up_window_seconds() -> int:
    raw = os.environ.get("MFA_STEP_UP_WINDOW_SECONDS", "900")
    try:
        n = int(raw)
    except ValueError:
        return 900
    return max(60, n)


def require_mfa_step_up():
    """FastAPI dependency: require a fresh TOTP step-up for the caller.

    API-key principals bypass this check; cookie sessions must have
    presented a valid TOTP code recently.
    """

    def _checker(request: Request) -> None:
        principal = getattr(request.state, "principal", None)
        if not principal:
            raise HTTPException(401, "Not authenticated.")
        # Machine-to-machine: scoped API key already proves possession of a
        # secret; MFA is a human-only control.
        if principal == "api-key" or principal.startswith("api-key:"):
            return
        if not mfa_store.is_confirmed(principal):
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "mfa_enrollment_required",
                    "detail": (
                        "This action requires a second factor. Enroll TOTP "
                        "under Settings -> Security before retrying."
                    ),
                },
            )
        sid = getattr(request.state, "session_id", None)
        verified_at = mfa_store.session_mfa_verified_at(sid)
        window = _step_up_window_seconds()
        now = datetime.now(UTC)
        if verified_at is None or (now - (verified_at if verified_at.tzinfo else verified_at.replace(tzinfo=UTC))) > timedelta(seconds=window):
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "mfa_required",
                    "detail": "Re-enter your authenticator code to confirm this action.",
                    "window_seconds": window,
                },
            )

    return Depends(_checker)
