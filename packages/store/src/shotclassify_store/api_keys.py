"""Database-backed API keys with scopes, expiry, and revocation.

Replaces the previous env-var-only key configuration as the authoritative
source for X-API-Key authentication. Keys are stored hashed (SHA-256, no
secret material at rest) and looked up by hash on every request. Each key
carries:

* ``scopes``: fine-grained capability list. The auth layer derives a coarse
  role from these so the existing ``require_role`` dependencies keep
  working, and routes can additionally call :func:`require_scope` to demand
  a specific capability.
* ``tenant_id``: hard tenant binding. The tenant resolution middleware uses
  this so a key issued to tenant A can never read tenant B even if the
  caller passes ``X-Tenant: B`` (admins still get cross-tenant access via
  session auth, by design).
* ``expires_at`` / ``revoked_at``: enterprise-grade lifecycle. Revoked or
  expired keys hard-fail with 401 ``invalid_api_key`` and are recorded as
  such in the audit log.

The plaintext token is returned exactly once at creation time; subsequent
reads only expose ``id``, ``label``, ``scopes``, ``last_used_at``, and the
timestamps so leaked database backups do not leak usable credentials.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable

from sqlalchemy import select, update

from .db import ApiKeyRow, get_session

# Canonical scope strings. ``admin`` is a superset shorthand the auth layer
# expands so callers don't have to list every read+write capability.
READ_CLASSIFICATIONS = "read:classifications"
WRITE_CLASSIFICATIONS = "write:classifications"
READ_AUDIT = "read:audit"
ADMIN = "admin"

VALID_SCOPES = frozenset(
    {READ_CLASSIFICATIONS, WRITE_CLASSIFICATIONS, READ_AUDIT, ADMIN}
)

# Scope -> role mapping for backward compatibility with ``require_role``.
# ``admin`` wins, then write implies operator, then read-only is viewer.
_DEFAULT_TOKEN_PREFIX = "sk_live_"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_id() -> str:
    return secrets.token_hex(8)


def _new_token() -> str:
    return _DEFAULT_TOKEN_PREFIX + secrets.token_urlsafe(32)


def _now() -> datetime:
    return datetime.now(UTC)


def role_for_scopes(scopes: Iterable[str] | None) -> str:
    """Derive the coarse RBAC role from a scope list."""
    if not scopes:
        return "viewer"
    s = set(scopes)
    if ADMIN in s:
        return "admin"
    if WRITE_CLASSIFICATIONS in s:
        return "operator"
    return "viewer"


def normalize_scopes(scopes: Iterable[str] | None) -> list[str]:
    """Drop unknown scopes, dedupe, sort. Empty input means viewer-equivalent."""
    if not scopes:
        return []
    out = sorted({s for s in scopes if s in VALID_SCOPES})
    return out


@dataclass(frozen=True)
class ApiKeyRecord:
    id: str
    label: str
    tenant_id: str | None
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    created_by: str | None
    rpm_override: int | None

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= _now():
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "tenant_id": self.tenant_id,
            "scopes": list(self.scopes),
            "role": role_for_scopes(self.scopes),
            "created_at": self.created_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "created_by": self.created_by,
            "active": self.is_active,
            "rpm_override": self.rpm_override,
        }


def _row_to_record(row: ApiKeyRow) -> ApiKeyRecord:
    return ApiKeyRecord(
        id=row.id,
        label=row.label,
        tenant_id=row.tenant_id,
        scopes=list(row.scopes or []),
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        created_by=row.created_by,
        rpm_override=row.rpm_override,
    )


def create_key(
    *,
    label: str,
    tenant_id: str | None,
    scopes: Iterable[str],
    created_by: str | None,
    ttl_days: int | None = None,
) -> tuple[ApiKeyRecord, str]:
    """Mint a new key. Returns ``(record, plaintext_token)``.

    The plaintext token is only returned here; subsequent reads can only
    surface the hashed form. Callers must display the token to the user
    exactly once and then drop it.
    """
    label = (label or "").strip()
    if not label:
        raise ValueError("label is required")
    normalized = normalize_scopes(scopes)
    if not normalized:
        raise ValueError("at least one valid scope is required")
    token = _new_token()
    row = ApiKeyRow(
        id=_new_id(),
        label=label[:128],
        token_hash=_hash(token),
        tenant_id=tenant_id,
        scopes=normalized,
        created_by=created_by,
        expires_at=(_now() + timedelta(days=ttl_days)) if ttl_days else None,
    )
    with get_session() as ses:
        ses.add(row)
        ses.commit()
        ses.refresh(row)
    return _row_to_record(row), token


def list_keys(
    *,
    tenant_id: str | None,
    include_revoked: bool = False,
) -> list[ApiKeyRecord]:
    """List keys for a tenant. Pass ``tenant_id=None`` for cross-tenant (admin)."""
    with get_session() as ses:
        stmt = select(ApiKeyRow).order_by(ApiKeyRow.created_at.desc())
        if tenant_id is not None:
            stmt = stmt.where(ApiKeyRow.tenant_id == tenant_id)
        if not include_revoked:
            stmt = stmt.where(ApiKeyRow.revoked_at.is_(None))
        rows = ses.scalars(stmt).all()
    return [_row_to_record(r) for r in rows]


def get_active_by_token(token: str) -> ApiKeyRecord | None:
    """Look up a key by presented plaintext token; return only if active.

    Returns ``None`` (rather than raising) when the backing table is not yet
    initialized: callers in early-boot or test paths that have not run
    ``init_db`` should fall through to the env-var key map without crashing.
    """
    if not token:
        return None
    h = _hash(token)
    try:
        with get_session() as ses:
            row = ses.scalar(select(ApiKeyRow).where(ApiKeyRow.token_hash == h))
            if row is None:
                return None
            rec = _row_to_record(row)
    except Exception:
        return None
    return rec if rec.is_active else None


def touch_last_used(key_id: str) -> None:
    """Stamp ``last_used_at`` for the matching key. Best-effort, never raises."""
    if not key_id:
        return
    try:
        with get_session() as ses:
            ses.execute(
                update(ApiKeyRow).where(ApiKeyRow.id == key_id).values(last_used_at=_now())
            )
            ses.commit()
    except Exception:  # pragma: no cover - defensive
        pass


def set_rpm_override(
    key_id: str,
    *,
    tenant_id: str | None,
    rpm: int | None,
) -> ApiKeyRecord | None:
    """Set or clear the per-key requests/minute override.

    ``rpm=None`` clears the override and falls back to the workspace default.
    Returns ``None`` when the key is missing or belongs to another tenant so
    a tenant-scoped admin can't probe ids across workspaces.
    """
    if rpm is not None:
        if not isinstance(rpm, int) or isinstance(rpm, bool):
            raise ValueError("rpm must be an integer or null")
        if rpm < 1 or rpm > 1_000_000:
            raise ValueError("rpm must be between 1 and 1000000")
    with get_session() as ses:
        row = ses.scalar(select(ApiKeyRow).where(ApiKeyRow.id == key_id))
        if row is None:
            return None
        if tenant_id is not None and row.tenant_id != tenant_id:
            return None
        row.rpm_override = rpm
        ses.commit()
        ses.refresh(row)
    return _row_to_record(row)


def revoke(key_id: str, *, tenant_id: str | None) -> ApiKeyRecord | None:
    """Soft-revoke a key. Returns the updated record or ``None`` if not found.

    When ``tenant_id`` is not ``None`` the row must belong to that tenant or
    the call is treated as not-found, so a tenant-scoped admin can't revoke
    keys belonging to a different workspace by guessing ids.
    """
    with get_session() as ses:
        row = ses.scalar(select(ApiKeyRow).where(ApiKeyRow.id == key_id))
        if row is None:
            return None
        if tenant_id is not None and row.tenant_id != tenant_id:
            return None
        if row.revoked_at is None:
            row.revoked_at = _now()
            ses.commit()
            ses.refresh(row)
    return _row_to_record(row)
