"""TOTP (RFC 6238) multi-factor enrollment and step-up verification.

Stores one row per principal in ``mfa_credentials``. Enrollment is a
two-step flow:

1. :func:`begin_enrollment` writes a fresh secret with ``confirmed_at=NULL``
   and returns the otpauth URI to scan in an authenticator app.
2. :func:`confirm_enrollment` verifies a code against the pending secret
   and stamps ``confirmed_at`` so the credential becomes active.

Step-up is handled by :func:`verify_step_up`, which checks a code against
the confirmed secret and stamps ``mfa_verified_at`` on the session row.
The auth middleware exposes that timestamp; ``require_mfa_step_up`` in
the API enforces a configurable freshness window for admin mutations.

Pending (unconfirmed) credentials are ignored by step-up so a half-enrolled
account cannot lock the user out. Confirmed credentials are required for
admin step-up checks (no opt-out at the store layer).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pyotp
from sqlalchemy import update

from .db import MfaCredentialRow, SessionRow, get_session


@dataclass(frozen=True)
class MfaStatus:
    enrolled: bool  # any row present
    confirmed: bool  # active credential
    created_at: datetime | None
    confirmed_at: datetime | None
    last_used_at: datetime | None

    def to_dict(self) -> dict:
        return {
            "enrolled": self.enrolled,
            "confirmed": self.confirmed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
        }


def _row_to_status(row: MfaCredentialRow | None) -> MfaStatus:
    if row is None:
        return MfaStatus(False, False, None, None, None)
    return MfaStatus(
        enrolled=True,
        confirmed=row.confirmed_at is not None,
        created_at=row.created_at,
        confirmed_at=row.confirmed_at,
        last_used_at=row.last_used_at,
    )


def status(principal: str) -> MfaStatus:
    with get_session() as s:
        row = s.get(MfaCredentialRow, principal)
        return _row_to_status(row)


def is_confirmed(principal: str) -> bool:
    return status(principal).confirmed


def begin_enrollment(principal: str, *, issuer: str = "ShotClassify") -> dict:
    """Start (or restart) TOTP enrollment. Returns secret + otpauth URI.

    Overwrites any existing UNCONFIRMED row. If the principal already has a
    CONFIRMED credential, raises ValueError so callers do not silently rotate
    an active second factor without an explicit ``disable`` first.
    """
    now = datetime.now(UTC)
    with get_session() as s:
        existing = s.get(MfaCredentialRow, principal)
        if existing is not None and existing.confirmed_at is not None:
            raise ValueError("MFA already enrolled. Disable it first to re-enroll.")
        secret = pyotp.random_base32()
        if existing is None:
            s.add(
                MfaCredentialRow(
                    principal=principal,
                    secret=secret,
                    created_at=now,
                    confirmed_at=None,
                    last_used_at=None,
                )
            )
        else:
            existing.secret = secret
            existing.created_at = now
        s.commit()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=principal, issuer_name=issuer)
    return {"secret": secret, "otpauth_uri": uri, "issuer": issuer, "account": principal}


def confirm_enrollment(principal: str, code: str) -> bool:
    """Verify a code against the pending secret and mark it confirmed.

    Returns True on success. Returns False if there is no pending enrollment
    or the code is invalid. Already-confirmed credentials return True
    (idempotent) so retrying a confirmation does not error.
    """
    code = (code or "").strip().replace(" ", "")
    now = datetime.now(UTC)
    with get_session() as s:
        row = s.get(MfaCredentialRow, principal)
        if row is None:
            return False
        if row.confirmed_at is not None:
            return True
        totp = pyotp.TOTP(row.secret)
        if not totp.verify(code, valid_window=1):
            return False
        row.confirmed_at = now
        row.last_used_at = now
        s.commit()
        return True


def disable(principal: str) -> bool:
    """Remove the MFA credential. Returns True if a row existed."""
    with get_session() as s:
        row = s.get(MfaCredentialRow, principal)
        if row is None:
            return False
        s.delete(row)
        s.commit()
        return True


def verify_step_up(principal: str, code: str, *, session_id: str | None) -> bool:
    """Verify a TOTP code and, on success, stamp the session as MFA-verified.

    Returns False if the principal has no confirmed credential, the code is
    wrong, or there is no session id to stamp (API-key callers do not have
    sessions and must use their own scoped key).
    """
    if not session_id:
        return False
    code = (code or "").strip().replace(" ", "")
    now = datetime.now(UTC)
    with get_session() as s:
        row = s.get(MfaCredentialRow, principal)
        if row is None or row.confirmed_at is None:
            return False
        totp = pyotp.TOTP(row.secret)
        if not totp.verify(code, valid_window=1):
            return False
        row.last_used_at = now
        s.execute(
            update(SessionRow)
            .where(SessionRow.id == session_id)
            .values(mfa_verified_at=now)
        )
        s.commit()
        return True


def session_mfa_verified_at(session_id: str | None) -> datetime | None:
    if not session_id:
        return None
    with get_session() as s:
        row = s.get(SessionRow, session_id)
        if row is None:
            return None
        return row.mfa_verified_at
