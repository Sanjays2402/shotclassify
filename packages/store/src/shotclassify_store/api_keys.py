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
import ipaddress
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable

from sqlalchemy import func, select, update

from .db import ApiKeyRow, get_session
from . import tenant_settings as _tenant_settings

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


# Maximum number of CIDR entries we will persist for a single key. Generous
# enough for ``/32`` per office plus per-CI-runner ranges, low enough to
# keep auth-time matching constant-time in practice.
_MAX_ALLOWED_CIDRS = 64


def normalize_cidrs(cidrs: Iterable[str] | None) -> list[str]:
    """Parse, canonicalise, dedupe, and sort a CIDR allowlist.

    Accepts bare addresses (``203.0.113.7`` becomes ``203.0.113.7/32``)
    and CIDR ranges (``198.51.100.0/24``). IPv4 and IPv6 are both valid.
    Raises :class:`ValueError` on any unparseable entry so callers see a
    422 rather than silently dropping a typo to an empty list (which
    would mean 'no restriction' and is exactly the wrong default).
    """
    if not cidrs:
        return []
    out: set[str] = set()
    for raw in cidrs:
        if raw is None:
            continue
        s = str(raw).strip()
        if not s:
            continue
        try:
            net = ipaddress.ip_network(s, strict=False)
        except ValueError as exc:
            raise ValueError(f"invalid CIDR: {s!r} ({exc})") from exc
        out.add(str(net))
    if len(out) > _MAX_ALLOWED_CIDRS:
        raise ValueError(
            f"too many CIDRs: {len(out)} (max {_MAX_ALLOWED_CIDRS})"
        )
    return sorted(out)


def ip_in_cidrs(ip: str, cidrs: Iterable[str] | None) -> bool:
    """True when ``ip`` is allowed by ``cidrs``.

    An empty / missing allowlist means 'no restriction' and returns True.
    Unparseable inputs fail closed (return False) so a malformed source
    IP can never bypass an active allowlist.
    """
    items = list(cidrs or [])
    if not items:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except (ValueError, TypeError):
        return False
    for c in items:
        try:
            if addr in ipaddress.ip_network(c, strict=False):
                return True
        except ValueError:
            continue
    return False


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
    allowed_cidrs: list[str]

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None:
            exp = self.expires_at
            now = _now()
            # Normalize both to naive UTC for comparison: SQLite returns naive
            # datetimes even when we wrote timezone-aware ones.
            if exp.tzinfo is None:
                now = now.replace(tzinfo=None)
            if exp <= now:
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
            "allowed_cidrs": list(self.allowed_cidrs),
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
        allowed_cidrs=list(row.allowed_cidrs or []),
    )


def create_key(
    *,
    label: str,
    tenant_id: str | None,
    scopes: Iterable[str],
    created_by: str | None,
    ttl_days: int | None = None,
    allowed_cidrs: Iterable[str] | None = None,
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
    # Enforce per-tenant max-TTL policy. NULL policy = legacy behaviour.
    # When the caller omits ttl_days but a policy exists, default to the
    # policy cap so we never silently mint an unbounded key under a
    # tenant that explicitly opted into rotation.
    policy_cap: int | None = None
    if tenant_id:
        policy_cap = _tenant_settings.get_api_key_ttl_policy(tenant_id).max_ttl_days
    if policy_cap is not None:
        if ttl_days is None:
            ttl_days = policy_cap
        elif ttl_days > policy_cap:
            raise ValueError(
                f"ttl_days {ttl_days} exceeds tenant policy max of "
                f"{policy_cap} days"
            )
    # Enforce per-tenant active-key cap (0031). When the workspace
    # already holds this many non-revoked keys, refuse to mint another.
    # Tightening the cap below the current count never retroactively
    # revokes anyone; it only blocks the next mint until an admin frees
    # a slot by revoking a stale key.
    if tenant_id:
        max_active = _tenant_settings.get_api_key_max_active_policy(
            tenant_id
        ).max_active
        if max_active is not None:
            with get_session() as ses:
                current = ses.scalar(
                    select(func.count())
                    .select_from(ApiKeyRow)
                    .where(
                        ApiKeyRow.tenant_id == tenant_id,
                        ApiKeyRow.revoked_at.is_(None),
                    )
                )
            if (current or 0) >= max_active:
                raise ValueError(
                    f"api_key_max_active_reached: tenant already has "
                    f"{current} active keys at the configured cap of "
                    f"{max_active}. Revoke an existing key before minting "
                    f"a new one or raise the cap in Settings."
                )
    token = _new_token()
    cidrs = normalize_cidrs(allowed_cidrs)
    row = ApiKeyRow(
        id=_new_id(),
        label=label[:128],
        token_hash=_hash(token),
        tenant_id=tenant_id,
        scopes=normalized,
        created_by=created_by,
        expires_at=(_now() + timedelta(days=ttl_days)) if ttl_days else None,
        allowed_cidrs=cidrs or None,
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


def set_allowed_cidrs(
    key_id: str,
    *,
    tenant_id: str | None,
    cidrs: Iterable[str] | None,
) -> ApiKeyRecord | None:
    """Replace the per-key source-IP allowlist.

    Pass an empty list or ``None`` to clear the restriction (key accepted
    from any IP). Returns ``None`` when the key is missing or belongs to
    another tenant so a tenant-scoped admin can't probe ids across
    workspaces. Raises :class:`ValueError` on invalid CIDR input.
    """
    normalised = normalize_cidrs(cidrs)
    with get_session() as ses:
        row = ses.scalar(select(ApiKeyRow).where(ApiKeyRow.id == key_id))
        if row is None:
            return None
        if tenant_id is not None and row.tenant_id != tenant_id:
            return None
        row.allowed_cidrs = normalised or None
        ses.commit()
        ses.refresh(row)
    return _row_to_record(row)


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


def rotate(
    key_id: str,
    *,
    tenant_id: str | None,
    grace_minutes: int = 1440,
    rotated_by: str | None = None,
) -> tuple[ApiKeyRecord, ApiKeyRecord, str] | None:
    """Issue a successor key and shorten the old key's lifetime to a grace window.

    Returns ``(old_record, new_record, plaintext_token)`` or ``None`` when the
    source key is not found or belongs to another tenant. The new key inherits
    the source's ``label`` (suffixed ``(rotated)``), ``tenant_id``, ``scopes``,
    and ``rpm_override``. The old key's ``expires_at`` is pulled in to
    ``now + grace_minutes`` (unless it already expires sooner) so existing
    integrations keep working long enough to swap the secret, but no longer.

    A ``grace_minutes`` of ``0`` revokes the old key immediately. The maximum
    grace window is 7 days; longer windows defeat the purpose of rotation.
    """
    if not isinstance(grace_minutes, int) or isinstance(grace_minutes, bool):
        raise ValueError("grace_minutes must be an integer")
    if grace_minutes < 0 or grace_minutes > 7 * 24 * 60:
        raise ValueError("grace_minutes must be between 0 and 10080 (7 days)")
    now = _now()
    with get_session() as ses:
        row = ses.scalar(select(ApiKeyRow).where(ApiKeyRow.id == key_id))
        if row is None:
            return None
        if tenant_id is not None and row.tenant_id != tenant_id:
            return None
        if row.revoked_at is not None:
            raise ValueError("cannot rotate a revoked key")
        # Mint the successor first so the source is never left without
        # a replacement on the off chance of a partial failure.
        scopes = list(row.scopes or [])
        new_label = row.label
        if not new_label.endswith("(rotated)"):
            new_label = f"{row.label} (rotated)"[:128]
        new_token = _new_token()
        # Clamp the successor's lifetime to the tenant policy if one is
        # set. We never extend the inherited expiry; we only shorten it.
        successor_expires = row.expires_at
        if row.tenant_id:
            policy_cap = _tenant_settings.get_api_key_ttl_policy(
                row.tenant_id
            ).max_ttl_days
            if policy_cap is not None:
                cap_aware = now + timedelta(days=policy_cap)
                cap_naive = cap_aware.replace(tzinfo=None)
                existing = successor_expires
                existing_cmp = (
                    existing.replace(tzinfo=None)
                    if existing is not None and existing.tzinfo is not None
                    else existing
                )
                if existing_cmp is None or existing_cmp > cap_naive:
                    successor_expires = cap_naive
        new_row = ApiKeyRow(
            id=_new_id(),
            label=new_label,
            token_hash=_hash(new_token),
            tenant_id=row.tenant_id,
            scopes=scopes,
            created_by=rotated_by or row.created_by,
            expires_at=successor_expires,
            rpm_override=row.rpm_override,
            allowed_cidrs=list(row.allowed_cidrs) if row.allowed_cidrs else None,
        )
        ses.add(new_row)
        # Shorten (never extend) the old key's TTL. SQLite strips tzinfo on
        # round-trip so we strip it here too to keep comparisons consistent
        # with rows read back from the DB.
        if grace_minutes == 0:
            row.revoked_at = now.replace(tzinfo=None)
        else:
            new_exp_aware = now + timedelta(minutes=grace_minutes)
            new_exp = new_exp_aware.replace(tzinfo=None)
            existing = row.expires_at
            existing_cmp = existing.replace(tzinfo=None) if existing is not None and existing.tzinfo is not None else existing
            if existing_cmp is None or existing_cmp > new_exp:
                row.expires_at = new_exp
        ses.commit()
        ses.refresh(row)
        ses.refresh(new_row)
        old_rec = _row_to_record(row)
        new_rec = _row_to_record(new_row)
    return old_rec, new_rec, new_token


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


def is_stale(record: "ApiKeyRecord", inactivity_days: int | None, *, now: datetime | None = None) -> bool:
    """Return True when the key has been idle longer than ``inactivity_days``.

    Uses ``last_used_at`` when present, else falls back to ``created_at`` so a
    key minted-and-forgotten is also caught. ``inactivity_days=None`` (no
    policy) always returns False. The check is timezone-safe: legacy rows
    written without tzinfo are treated as UTC.
    """
    if inactivity_days is None or inactivity_days <= 0:
        return False
    ts = record.last_used_at or record.created_at
    if ts is None:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    current = now or _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return (current - ts) > timedelta(days=inactivity_days)
