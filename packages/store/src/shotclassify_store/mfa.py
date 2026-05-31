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
    """Remove the MFA credential and any associated recovery codes.

    Returns True if a credential row existed. Recovery codes are wiped
    unconditionally because they are only meaningful while a TOTP
    credential is enrolled; leaving them behind would let a stale code
    re-enable step-up after the second factor was removed.
    """
    with get_session() as s:
        row = s.get(MfaCredentialRow, principal)
        if row is None:
            # Still clean up any orphan recovery rows just in case.
            s.query(MfaRecoveryCodeRow).filter(
                MfaRecoveryCodeRow.principal == principal
            ).delete(synchronize_session=False)
            s.commit()
            return False
        s.query(MfaRecoveryCodeRow).filter(
            MfaRecoveryCodeRow.principal == principal
        ).delete(synchronize_session=False)
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


# ---------------------------------------------------------------------------
# Recovery (backup) codes
# ---------------------------------------------------------------------------
#
# A confirmed-MFA user can generate a batch of single-use recovery codes that
# satisfy step-up when the authenticator app is unavailable. Codes are stored
# salted-and-hashed, burned on first use, and a new generation invalidates the
# old batch.

import hashlib
import secrets
import uuid

from .db import MfaRecoveryCodeRow

RECOVERY_BATCH_SIZE = 10
RECOVERY_CODE_GROUPS = 2  # "abcd-efgh" style
RECOVERY_CODE_GROUP_LEN = 4


def _hash_recovery(code: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{code.lower().strip()}".encode("utf-8")).hexdigest()


def _format_code() -> str:
    # Crockford-ish alphabet: no 0/O/1/I/L to keep transcription clean.
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    groups = [
        "".join(secrets.choice(alphabet) for _ in range(RECOVERY_CODE_GROUP_LEN))
        for _ in range(RECOVERY_CODE_GROUPS)
    ]
    return "-".join(groups).lower()


@dataclass(frozen=True)
class RecoveryStatus:
    total: int
    remaining: int
    generated_at: datetime | None
    last_used_at: datetime | None

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "remaining": self.remaining,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
        }


def recovery_status(principal: str) -> RecoveryStatus:
    """Return counts and timestamps for the principal's active recovery batch."""
    with get_session() as s:
        rows = (
            s.query(MfaRecoveryCodeRow)
            .filter(MfaRecoveryCodeRow.principal == principal)
            .all()
        )
        if not rows:
            return RecoveryStatus(0, 0, None, None)
        total = len(rows)
        remaining = sum(1 for r in rows if r.used_at is None)
        generated_at = min(r.created_at for r in rows)
        used_times = [r.used_at for r in rows if r.used_at is not None]
        last_used_at = max(used_times) if used_times else None
        return RecoveryStatus(total, remaining, generated_at, last_used_at)


def regenerate_recovery_codes(principal: str) -> dict:
    """Burn any existing batch and issue a fresh set of plaintext codes.

    Caller MUST gate this on a confirmed MFA credential and a fresh
    TOTP step-up; this function only enforces the "confirmed MFA"
    invariant so it cannot accidentally bootstrap recovery before the
    second factor itself exists.
    """
    if not is_confirmed(principal):
        raise ValueError("Confirm MFA enrollment before generating recovery codes.")
    now = datetime.now(UTC)
    batch_id = uuid.uuid4().hex
    plaintext: list[str] = []
    with get_session() as s:
        # Drop any prior rows for this principal in the same transaction so a
        # crash mid-generation never leaves two active batches.
        s.query(MfaRecoveryCodeRow).filter(
            MfaRecoveryCodeRow.principal == principal
        ).delete(synchronize_session=False)
        for _ in range(RECOVERY_BATCH_SIZE):
            code = _format_code()
            plaintext.append(code)
            salt = secrets.token_hex(16)
            s.add(
                MfaRecoveryCodeRow(
                    id=uuid.uuid4().hex,
                    principal=principal,
                    code_hash=_hash_recovery(code, salt),
                    salt=salt,
                    batch_id=batch_id,
                    created_at=now,
                    used_at=None,
                )
            )
        s.commit()
    return {
        "batch_id": batch_id,
        "generated_at": now.isoformat(),
        "codes": plaintext,
        "remaining": RECOVERY_BATCH_SIZE,
        "total": RECOVERY_BATCH_SIZE,
    }


def consume_recovery_code(
    principal: str, code: str, *, session_id: str | None
) -> bool:
    """Burn one matching recovery code and stamp the session as MFA-verified.

    Returns False if the principal has no MFA credential, no matching
    unused code is found, or no session is present to stamp. The code
    lookup is constant-time per row to avoid leaking which codes exist.
    """
    if not session_id:
        return False
    code = (code or "").strip().lower()
    if not code:
        return False
    if not is_confirmed(principal):
        return False
    now = datetime.now(UTC)
    with get_session() as s:
        rows = (
            s.query(MfaRecoveryCodeRow)
            .filter(
                MfaRecoveryCodeRow.principal == principal,
                MfaRecoveryCodeRow.used_at.is_(None),
            )
            .all()
        )
        match = None
        for row in rows:
            expected = _hash_recovery(code, row.salt)
            if secrets.compare_digest(expected, row.code_hash):
                match = row
        if match is None:
            return False
        match.used_at = now
        # Also stamp the credential so audit shows recent MFA activity.
        cred = s.get(MfaCredentialRow, principal)
        if cred is not None:
            cred.last_used_at = now
        s.execute(
            update(SessionRow)
            .where(SessionRow.id == session_id)
            .values(mfa_verified_at=now)
        )
        s.commit()
        return True


def _invalidate_recovery_codes(principal: str) -> int:
    with get_session() as s:
        deleted = (
            s.query(MfaRecoveryCodeRow)
            .filter(MfaRecoveryCodeRow.principal == principal)
            .delete(synchronize_session=False)
        )
        s.commit()
        return int(deleted)
