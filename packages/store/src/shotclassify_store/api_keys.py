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

from .db import ApiKeyMonthlyUsageRow, ApiKeyRow, get_session
from . import tenant_settings as _tenant_settings
from .scope_catalog import all_scope_ids

# Canonical scope strings. ``admin`` is a superset shorthand the auth layer
# expands so callers don't have to list every read+write capability.
READ_CLASSIFICATIONS = "read:classifications"
WRITE_CLASSIFICATIONS = "write:classifications"
READ_AUDIT = "read:audit"
ADMIN = "admin"

# Authoritative list lives in :mod:`scope_catalog`. Keeping that as the
# single source of truth means a new scope shipped without a catalog
# entry fails API-key creation immediately instead of being silently
# accepted with no documentation for auditors.
VALID_SCOPES = all_scope_ids()

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
    monthly_quota: int | None
    monthly_usage: int = 0
    owner_email: str | None = None

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
            "monthly_quota": self.monthly_quota,
            "monthly_usage": self.monthly_usage,
            "owner_email": self.owner_email,
        }


def _current_year_month(now: datetime | None = None) -> str:
    """Return the current UTC year-month bucket (``YYYY-MM``)."""
    t = now or _now()
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.strftime("%Y-%m")


def _seconds_until_next_month(now: datetime | None = None) -> int:
    """Seconds remaining until the start of the next UTC month.

    Used by the rate limit middleware to populate ``X-RateLimit-Reset`` and
    ``Retry-After`` when a request is rejected by the per-key monthly cap.
    Always returns at least 1 so clients never see ``Retry-After: 0``.
    """
    t = now or _now()
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    year = t.year + (1 if t.month == 12 else 0)
    month = 1 if t.month == 12 else t.month + 1
    nxt = datetime(year, month, 1, tzinfo=UTC)
    return max(1, int((nxt - t).total_seconds()))


def _row_to_record(row: ApiKeyRow, *, monthly_usage: int = 0) -> ApiKeyRecord:
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
        monthly_quota=row.monthly_quota,
        monthly_usage=monthly_usage,
        owner_email=row.owner_email,
    )


_EMAIL_MAX_LEN = 254


def normalize_owner_email(value: str | None, *, required: bool = True) -> str | None:
    """Validate and canonicalise an API-key owner email.

    Procurement-grade: a key without a named human owner is a finding.
    We accept any syntactically plausible mailbox (RFC 5321 is permissive;
    we keep this lightweight on purpose so internal mailing-list owners
    like ``platform-oncall@acme.com`` are accepted) and lowercase the
    domain so two keys cannot end up owned by ``Alice@ACME.com`` and
    ``alice@acme.com``. Raises :class:`ValueError` when ``required`` and
    the value is missing or unparseable so the route returns 422.
    """
    if value is None or not str(value).strip():
        if required:
            raise ValueError("owner_email is required")
        return None
    s = str(value).strip()
    if len(s) > _EMAIL_MAX_LEN:
        raise ValueError(f"owner_email exceeds {_EMAIL_MAX_LEN} characters")
    if s.count("@") != 1:
        raise ValueError("owner_email must contain exactly one '@'")
    local, _, domain = s.partition("@")
    if not local or not domain or "." not in domain:
        raise ValueError("owner_email is not a valid mailbox")
    if any(ch.isspace() for ch in s):
        raise ValueError("owner_email may not contain whitespace")
    return f"{local}@{domain.lower()}"


def create_key(
    *,
    label: str,
    tenant_id: str | None,
    scopes: Iterable[str],
    created_by: str | None,
    ttl_days: int | None = None,
    allowed_cidrs: Iterable[str] | None = None,
    monthly_quota: int | None = None,
    owner_email: str | None = None,
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
    if monthly_quota is not None:
        if not isinstance(monthly_quota, int) or isinstance(monthly_quota, bool):
            raise ValueError("monthly_quota must be an integer or null")
        if monthly_quota < 1 or monthly_quota > _MAX_MONTHLY_QUOTA:
            raise ValueError(
                f"monthly_quota must be between 1 and {_MAX_MONTHLY_QUOTA}"
            )
    # Owner email: required for net-new keys minted via the public route.
    # Internal callers (tests, retention seeders) can pass ``required=False``
    # by sending ``owner_email=None`` and we will store NULL so they show
    # up in the unowned bucket for an admin to assign. The route layer is
    # the choke point that enforces "new keys must have an owner."
    normalized_owner = normalize_owner_email(owner_email, required=False)
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
        monthly_quota=monthly_quota,
        owner_email=normalized_owner,
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
    ym = _current_year_month()
    with get_session() as ses:
        stmt = select(ApiKeyRow).order_by(ApiKeyRow.created_at.desc())
        if tenant_id is not None:
            stmt = stmt.where(ApiKeyRow.tenant_id == tenant_id)
        if not include_revoked:
            stmt = stmt.where(ApiKeyRow.revoked_at.is_(None))
        rows = ses.scalars(stmt).all()
        out: list[ApiKeyRecord] = []
        for r in rows:
            usage = _read_usage_locked(ses, r.id, ym) if r.monthly_quota is not None else 0
            out.append(_row_to_record(r, monthly_usage=usage))
    return out


def get_by_id(key_id: str) -> ApiKeyRecord | None:
    """Fetch a key record by id, including revoked/expired ones.

    Used by introspection and admin tooling so the caller can see
    ``revoked_at`` / ``expires_at`` for diagnostics. Returns ``None`` when
    the row does not exist or the backing table is not initialized.
    """
    if not key_id:
        return None
    try:
        with get_session() as ses:
            row = ses.scalar(select(ApiKeyRow).where(ApiKeyRow.id == key_id))
            if row is None:
                return None
            ym = _current_year_month()
            usage = (
                _read_usage_locked(ses, row.id, ym)
                if row.monthly_quota is not None
                else 0
            )
            return _row_to_record(row, monthly_usage=usage)
    except Exception:  # pragma: no cover - defensive
        return None


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
            monthly_quota=row.monthly_quota,
            owner_email=row.owner_email,
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


# ---------------------------------------------------------------------------
# Per-key monthly call quota (0033).
# ---------------------------------------------------------------------------


_MAX_MONTHLY_QUOTA = 1_000_000_000


def set_monthly_quota(
    key_id: str,
    *,
    tenant_id: str | None,
    quota: int | None,
) -> ApiKeyRecord | None:
    """Set or clear the per-key monthly call quota.

    ``quota=None`` clears the cap. Returns ``None`` when the key is missing
    or belongs to another tenant so a tenant-scoped admin can't probe ids
    across workspaces. Raises :class:`ValueError` on a non-positive or
    absurdly large value.
    """
    if quota is not None:
        if not isinstance(quota, int) or isinstance(quota, bool):
            raise ValueError("quota must be an integer or null")
        if quota < 1 or quota > _MAX_MONTHLY_QUOTA:
            raise ValueError(
                f"quota must be between 1 and {_MAX_MONTHLY_QUOTA}"
            )
    with get_session() as ses:
        row = ses.scalar(select(ApiKeyRow).where(ApiKeyRow.id == key_id))
        if row is None:
            return None
        if tenant_id is not None and row.tenant_id != tenant_id:
            return None
        row.monthly_quota = quota
        ses.commit()
        ses.refresh(row)
        usage = _read_usage_locked(ses, row.id, _current_year_month())
    return _row_to_record(row, monthly_usage=usage)


def get_monthly_usage(key_id: str, *, year_month: str | None = None) -> int:
    """Return the call count for ``key_id`` in the given UTC ``YYYY-MM``.

    Defaults to the current UTC month. Returns 0 when no row exists yet.
    Never raises; storage hiccups degrade to 0 so callers can render UIs
    without surfacing internal errors.
    """
    ym = year_month or _current_year_month()
    try:
        with get_session() as ses:
            return _read_usage_locked(ses, key_id, ym)
    except Exception:  # pragma: no cover - defensive
        return 0


def _read_usage_locked(ses, key_id: str, ym: str) -> int:
    row = ses.scalar(
        select(ApiKeyMonthlyUsageRow).where(
            ApiKeyMonthlyUsageRow.key_id == key_id,
            ApiKeyMonthlyUsageRow.year_month == ym,
        )
    )
    return int(row.count) if row is not None else 0


@dataclass(frozen=True)
class MonthlyConsumeResult:
    allowed: bool
    quota: int | None
    used: int
    remaining: int
    reset_seconds: int


def try_consume_monthly_quota(
    record: ApiKeyRecord,
    *,
    now: datetime | None = None,
) -> MonthlyConsumeResult:
    """Atomically charge one request against the key's monthly quota.

    When the key has no ``monthly_quota`` set this is a no-op that reports
    ``allowed=True`` and ``quota=None``. When a quota is set we increment
    the counter row inside a single transaction and only commit when the
    new value would not exceed the cap, so concurrent requests cannot
    race past the configured limit.

    Returns a :class:`MonthlyConsumeResult` describing the post-charge
    state. The middleware uses ``reset_seconds`` to populate
    ``X-RateLimit-Reset`` and ``Retry-After`` on a 429 response.
    """
    quota = record.monthly_quota
    reset = _seconds_until_next_month(now)
    if quota is None:
        return MonthlyConsumeResult(
            allowed=True, quota=None, used=0, remaining=-1, reset_seconds=reset
        )
    ym = _current_year_month(now)
    try:
        with get_session() as ses:
            row = ses.scalar(
                select(ApiKeyMonthlyUsageRow).where(
                    ApiKeyMonthlyUsageRow.key_id == record.id,
                    ApiKeyMonthlyUsageRow.year_month == ym,
                )
            )
            if row is None:
                row = ApiKeyMonthlyUsageRow(
                    key_id=record.id, year_month=ym, count=0
                )
                ses.add(row)
                ses.flush()
            current = int(row.count)
            if current >= quota:
                # Refuse: do not commit any change so the counter accurately
                # reflects accepted requests only.
                ses.rollback()
                return MonthlyConsumeResult(
                    allowed=False,
                    quota=quota,
                    used=current,
                    remaining=0,
                    reset_seconds=reset,
                )
            row.count = current + 1
            row.updated_at = _now()
            ses.commit()
            new_used = current + 1
            return MonthlyConsumeResult(
                allowed=True,
                quota=quota,
                used=new_used,
                remaining=max(0, quota - new_used),
                reset_seconds=reset,
            )
    except Exception:  # pragma: no cover - defensive; fail open on storage glitch
        return MonthlyConsumeResult(
            allowed=True,
            quota=quota,
            used=0,
            remaining=quota,
            reset_seconds=reset,
        )


def set_owner_email(
    key_id: str,
    *,
    tenant_id: str | None,
    owner_email: str | None,
) -> ApiKeyRecord | None:
    """Set or clear the accountable-owner email for a key.

    ``owner_email=None`` clears the value back to NULL so the key shows
    up in the unowned bucket again. Returns ``None`` when the key is
    missing or belongs to another tenant so a tenant-scoped admin can't
    probe ids across workspaces. Raises :class:`ValueError` when the
    email is not a syntactically valid mailbox.
    """
    normalized = normalize_owner_email(owner_email, required=False)
    with get_session() as ses:
        row = ses.scalar(select(ApiKeyRow).where(ApiKeyRow.id == key_id))
        if row is None:
            return None
        if tenant_id is not None and row.tenant_id != tenant_id:
            return None
        row.owner_email = normalized
        ses.commit()
        ses.refresh(row)
    return _row_to_record(row)


def list_expiring(
    *,
    tenant_id: str | None,
    within_days: int = 30,
    now: datetime | None = None,
) -> list[ApiKeyRecord]:
    """List active (non-revoked) keys whose ``expires_at`` falls inside a window.

    Drives the admin console "expiring credentials" widget that lets
    security teams plan rotations *before* a key silently dies and
    pages an on-call engineer at 3am. Keys that have already expired
    (``expires_at <= now``) are included so a long-overdue rotation is
    not invisible. Keys without an ``expires_at`` (never-expire) are
    excluded because they cannot be "expiring soon" by definition.

    Tenant-scoped so one workspace cannot enumerate another workspace's
    credential lifecycle. Ordering is soonest-first so the UI can render
    the most urgent rotations at the top without re-sorting.
    """
    if within_days < 0:
        raise ValueError("within_days must be >= 0")
    cutoff_now = now or _now()
    cutoff = cutoff_now + timedelta(days=within_days)
    with get_session() as ses:
        stmt = (
            select(ApiKeyRow)
            .where(ApiKeyRow.revoked_at.is_(None))
            .where(ApiKeyRow.expires_at.is_not(None))
            .where(ApiKeyRow.expires_at <= cutoff)
            .order_by(ApiKeyRow.expires_at.asc())
        )
        if tenant_id is not None:
            stmt = stmt.where(ApiKeyRow.tenant_id == tenant_id)
        rows = ses.scalars(stmt).all()
    return [_row_to_record(r) for r in rows]


def list_unowned(*, tenant_id: str | None) -> list[ApiKeyRecord]:
    """List active (non-revoked) keys missing an accountable owner.

    Used by the admin console to drive an access-review workflow: every
    active key must have a named human owner; rows created before the
    ``owner_email`` migration land here for assignment. Tenant-scoped so
    one workspace cannot enumerate another workspace's grandfathered keys.
    """
    with get_session() as ses:
        stmt = (
            select(ApiKeyRow)
            .where(ApiKeyRow.revoked_at.is_(None))
            .where(ApiKeyRow.owner_email.is_(None))
            .order_by(ApiKeyRow.created_at.desc())
        )
        if tenant_id is not None:
            stmt = stmt.where(ApiKeyRow.tenant_id == tenant_id)
        rows = ses.scalars(stmt).all()
    return [_row_to_record(r) for r in rows]
