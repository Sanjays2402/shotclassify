"""Workspace memberships and email invitations.

Membership rows are the authoritative source of role assignment for a
``(tenant_id, principal)`` pair once any row exists for that pair. The
auth middleware consults :func:`role_for_member` on every request and
prefers a membership over the legacy env-var ``AUTH_ROLE_MAP``. This is
the wiring that lets workspace owners hand out roles from the UI
without a redeploy.

Every read and write in this module filters by ``tenant_id`` so cross-
tenant enumeration is impossible at the query layer (not just at the
route layer).
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from .db import InvitationRow, MembershipRow, get_session

VALID_ROLES = ("admin", "operator", "viewer")
DEFAULT_INVITE_TTL_DAYS = 7
INVITE_TOKEN_PREFIX = "inv_"
# Hard cap on the seat_limit column. Keeps a fat-fingered value (e.g.
# 1e9) from making the count cheap-to-query but expensive-to-reason
# about. Workspaces that genuinely need more should set NULL (unlimited).
SEAT_LIMIT_MAX = 100_000


class SeatLimitExceeded(Exception):
    """Raised when adding a seat would exceed the workspace's seat_limit.

    A "seat" is one active membership row plus one pending non-expired
    invitation. The API layer maps this to HTTP 402 Payment Required so
    billing/seat overage flows can branch on it without parsing strings.
    """

    def __init__(self, tenant_id: str, limit: int, in_use: int) -> None:
        self.tenant_id = tenant_id
        self.limit = limit
        self.in_use = in_use
        super().__init__(
            f"Workspace {tenant_id!r} has used {in_use}/{limit} seats. "
            "Revoke a pending invite, remove a member, or raise the seat limit."
        )


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_id() -> str:
    return secrets.token_hex(8)


def _new_token() -> str:
    return INVITE_TOKEN_PREFIX + secrets.token_urlsafe(32)


@dataclass(frozen=True)
class MembershipRecord:
    id: str
    tenant_id: str
    principal: str
    role: str
    invited_by: str | None
    created_at: datetime
    updated_at: datetime
    suspended_at: datetime | None = None
    suspended_by: str | None = None
    suspension_reason: str | None = None

    @property
    def status(self) -> str:
        return "suspended" if self.suspended_at is not None else "active"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "principal": self.principal,
            "role": self.role,
            "invited_by": self.invited_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "status": self.status,
            "suspended_at": self.suspended_at.isoformat() if self.suspended_at else None,
            "suspended_by": self.suspended_by,
            "suspension_reason": self.suspension_reason,
        }


@dataclass(frozen=True)
class InvitationRecord:
    id: str
    tenant_id: str
    email: str
    role: str
    invited_by: str | None
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None

    @property
    def status(self) -> str:
        now = datetime.now(UTC)
        # SQLite hands back naive datetimes; normalize so comparisons work
        # across both sqlite (tests) and Postgres (prod).
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if self.revoked_at is not None:
            return "revoked"
        if self.accepted_at is not None:
            return "accepted"
        if expires_at < now:
            return "expired"
        return "pending"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "email": self.email,
            "role": self.role,
            "invited_by": self.invited_by,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "accepted_at": self.accepted_at.isoformat() if self.accepted_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "status": self.status,
        }


def _to_membership(row: MembershipRow) -> MembershipRecord:
    return MembershipRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        principal=row.principal,
        role=row.role,
        invited_by=row.invited_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        suspended_at=getattr(row, "suspended_at", None),
        suspended_by=getattr(row, "suspended_by", None),
        suspension_reason=getattr(row, "suspension_reason", None),
    )


def _to_invitation(row: InvitationRow) -> InvitationRecord:
    return InvitationRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        email=row.email,
        role=row.role,
        invited_by=row.invited_by,
        created_at=row.created_at,
        expires_at=row.expires_at,
        accepted_at=row.accepted_at,
        revoked_at=row.revoked_at,
    )


# ---------------------------------------------------------------- memberships


def role_for_member(tenant_id: str | None, principal: str | None) -> str | None:
    """Return the active role for ``(tenant_id, principal)`` or ``None``.

    Suspended memberships return ``None`` so role-based checks fail
    closed. Callers that need to distinguish "no row" from "suspended"
    (the auth middleware does, to surface a clear error) should use
    :func:`membership_status` instead.
    """
    if not tenant_id or not principal:
        return None
    with get_session() as session:
        row = session.execute(
            select(MembershipRow)
            .where(MembershipRow.tenant_id == tenant_id)
            .where(MembershipRow.principal == principal)
        ).scalar_one_or_none()
        if row is None:
            return None
        if getattr(row, "suspended_at", None) is not None:
            return None
        return row.role


def membership_status(tenant_id: str | None, principal: str | None) -> str:
    """Return ``"active"``, ``"suspended"``, or ``"none"``.

    The auth middleware uses this to fail an entire tenant-scoped
    request with 403 ``membership_suspended`` when the row exists but
    the principal has been offboarded. ``"none"`` preserves the legacy
    fallback path (env-var role map / first-touch behaviour) so adding
    suspension does not change behaviour for tenants that never used
    the feature.
    """
    if not tenant_id or not principal:
        return "none"
    with get_session() as session:
        row = session.execute(
            select(MembershipRow)
            .where(MembershipRow.tenant_id == tenant_id)
            .where(MembershipRow.principal == principal)
        ).scalar_one_or_none()
        if row is None:
            return "none"
        return "suspended" if getattr(row, "suspended_at", None) is not None else "active"


def suspend_member(
    tenant_id: str,
    principal: str,
    *,
    suspended_by: str | None,
    reason: str | None = None,
) -> MembershipRecord | None:
    """Mark a membership suspended. Returns the updated record or None.

    Idempotent: suspending an already-suspended member keeps the original
    ``suspended_at`` and ``suspended_by`` so the audit trail of who
    first offboarded the user is preserved. The caller is responsible
    for ensuring at least one admin remains active (use
    :func:`count_active_admins`).
    """
    if not tenant_id or not principal:
        return None
    if reason is not None:
        reason = reason.strip() or None
        if reason and len(reason) > 512:
            raise ValueError("suspension reason must be 512 characters or fewer.")
    now = datetime.now(UTC)
    with get_session() as session:
        row = session.execute(
            select(MembershipRow)
            .where(MembershipRow.tenant_id == tenant_id)
            .where(MembershipRow.principal == principal)
        ).scalar_one_or_none()
        if row is None:
            return None
        if getattr(row, "suspended_at", None) is None:
            row.suspended_at = now
            row.suspended_by = suspended_by
            row.suspension_reason = reason
            row.updated_at = now
            session.commit()
            session.refresh(row)
        return _to_membership(row)


def reinstate_member(tenant_id: str, principal: str) -> MembershipRecord | None:
    """Clear a suspension. Returns the refreshed record or None."""
    if not tenant_id or not principal:
        return None
    now = datetime.now(UTC)
    with get_session() as session:
        row = session.execute(
            select(MembershipRow)
            .where(MembershipRow.tenant_id == tenant_id)
            .where(MembershipRow.principal == principal)
        ).scalar_one_or_none()
        if row is None:
            return None
        row.suspended_at = None
        row.suspended_by = None
        row.suspension_reason = None
        row.updated_at = now
        session.commit()
        session.refresh(row)
        return _to_membership(row)


def count_active_admins(
    tenant_id: str, *, exclude_principal: str | None = None
) -> int:
    """Count admins that are NOT suspended. Use this before suspending or
    demoting the last admin so the workspace cannot lock itself out."""
    if not tenant_id:
        return 0
    with get_session() as session:
        q = (
            select(MembershipRow)
            .where(MembershipRow.tenant_id == tenant_id)
            .where(MembershipRow.role == "admin")
            .where(MembershipRow.suspended_at.is_(None))
        )
        if exclude_principal:
            q = q.where(MembershipRow.principal != exclude_principal)
        return len(session.execute(q).scalars().all())


def list_members(tenant_id: str) -> list[MembershipRecord]:
    if not tenant_id:
        return []
    with get_session() as session:
        rows = (
            session.execute(
                select(MembershipRow)
                .where(MembershipRow.tenant_id == tenant_id)
                .order_by(MembershipRow.created_at.asc())
            )
            .scalars()
            .all()
        )
        return [_to_membership(r) for r in rows]


def upsert_member(
    *,
    tenant_id: str,
    principal: str,
    role: str,
    invited_by: str | None = None,
    enforce_seat_limit: bool = True,
) -> MembershipRecord:
    """Create or update a membership. Returns the resulting record.

    When ``enforce_seat_limit`` is True (default) and the principal is not
    already a member of the tenant, the call raises
    :class:`SeatLimitExceeded` if seating a new member would exceed the
    tenant's configured ``seat_limit``. Role changes on an existing member
    never consume a new seat, so they are always allowed.

    Pass ``enforce_seat_limit=False`` for internal bootstrap paths (test
    fixtures, data migrations) where a quota check is not appropriate.
    Production code paths that surface to humans (manual invite, SSO
    auto-join, SCIM provisioning) MUST leave the default in place so the
    quota cannot be bypassed by routing through a different surface.
    """
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role '{role}'. Must be one of {VALID_ROLES}.")
    if not tenant_id or not principal:
        raise ValueError("tenant_id and principal are required.")
    now = datetime.now(UTC)
    with get_session() as session:
        existing = session.execute(
            select(MembershipRow)
            .where(MembershipRow.tenant_id == tenant_id)
            .where(MembershipRow.principal == principal)
        ).scalar_one_or_none()
        if existing is not None:
            existing.role = role
            existing.updated_at = now
            session.commit()
            session.refresh(existing)
            return _to_membership(existing)
        if enforce_seat_limit:
            _enforce_seat_capacity(session, tenant_id)
        row = MembershipRow(
            id=_new_id(),
            tenant_id=tenant_id,
            principal=principal,
            role=role,
            invited_by=invited_by,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_membership(row)


def remove_member(tenant_id: str, principal: str) -> bool:
    """Delete a membership. Returns True if a row was removed."""
    if not tenant_id or not principal:
        return False
    with get_session() as session:
        row = session.execute(
            select(MembershipRow)
            .where(MembershipRow.tenant_id == tenant_id)
            .where(MembershipRow.principal == principal)
        ).scalar_one_or_none()
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def count_admins(tenant_id: str, *, exclude_principal: str | None = None) -> int:
    """How many ACTIVE admin members the tenant has, optionally excluding one.

    Used to prevent the last admin from demoting or removing themselves
    and locking the workspace out of role management. Suspended
    memberships are excluded because they cannot administer anything.
    """
    return count_active_admins(tenant_id, exclude_principal=exclude_principal)


# ---------------------------------------------------------------- invitations


def create_invitation(
    *,
    tenant_id: str,
    email: str,
    role: str,
    invited_by: str | None,
    ttl_days: int = DEFAULT_INVITE_TTL_DAYS,
) -> tuple[InvitationRecord, str]:
    """Create a pending invitation. Returns (record, plaintext_token).

    The plaintext token is the only credential the invitee needs to
    accept; it is shown exactly once and only its hash is stored.
    """
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role '{role}'. Must be one of {VALID_ROLES}.")
    email = email.strip().lower()
    if not email or "@" not in email or len(email) > 255:
        raise ValueError("A valid email address is required.")
    if not tenant_id:
        raise ValueError("tenant_id is required.")
    token = _new_token()
    now = datetime.now(UTC)
    row = InvitationRow(
        id=_new_id(),
        tenant_id=tenant_id,
        email=email,
        role=role,
        token_hash=_hash(token),
        invited_by=invited_by,
        created_at=now,
        expires_at=now + timedelta(days=max(1, int(ttl_days))),
    )
    with get_session() as session:
        # Pending invitations consume a seat for the purposes of the cap.
        # Without this check an admin could mint more invitations than the
        # plan allows and only hit the wall on accept, leaving paying
        # invitees stranded.
        _enforce_seat_capacity(session, tenant_id)
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_invitation(row), token


def list_invitations(tenant_id: str, *, include_inactive: bool = False) -> list[InvitationRecord]:
    if not tenant_id:
        return []
    with get_session() as session:
        rows = (
            session.execute(
                select(InvitationRow)
                .where(InvitationRow.tenant_id == tenant_id)
                .order_by(InvitationRow.created_at.desc())
            )
            .scalars()
            .all()
        )
        records = [_to_invitation(r) for r in rows]
        if include_inactive:
            return records
        return [r for r in records if r.status == "pending"]


def revoke_invitation(invitation_id: str, *, tenant_id: str) -> InvitationRecord | None:
    if not invitation_id or not tenant_id:
        return None
    with get_session() as session:
        row = session.execute(
            select(InvitationRow)
            .where(InvitationRow.id == invitation_id)
            .where(InvitationRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            return None
        if row.revoked_at is None and row.accepted_at is None:
            row.revoked_at = datetime.now(UTC)
            session.commit()
            session.refresh(row)
        return _to_invitation(row)


def get_invitation_by_token(token: str) -> InvitationRecord | None:
    """Look up an invitation by its plaintext token. Tenant-agnostic on purpose.

    The token itself is the proof of authorization to view this row, so we
    cannot scope the lookup by tenant (the invitee does not yet know their
    tenant). The caller MUST verify status before acting on the result.
    """
    if not token:
        return None
    with get_session() as session:
        row = session.execute(
            select(InvitationRow).where(InvitationRow.token_hash == _hash(token))
        ).scalar_one_or_none()
        return _to_invitation(row) if row else None


def accept_invitation(
    token: str, *, principal: str
) -> tuple[InvitationRecord, MembershipRecord] | None:
    """Consume an invitation token and create the matching membership.

    Returns ``None`` if the token is unknown, revoked, expired, or already
    accepted. The membership upsert and the invitation update happen in
    the same transaction so a half-applied accept cannot leave a
    dangling row.
    """
    if not token or not principal:
        return None
    now = datetime.now(UTC)
    with get_session() as session:
        row = session.execute(
            select(InvitationRow).where(InvitationRow.token_hash == _hash(token))
        ).scalar_one_or_none()
        if row is None:
            return None
        if row.revoked_at is not None or row.accepted_at is not None:
            return None
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < now:
            return None
        existing = session.execute(
            select(MembershipRow)
            .where(MembershipRow.tenant_id == row.tenant_id)
            .where(MembershipRow.principal == principal)
        ).scalar_one_or_none()
        if existing is not None:
            existing.role = row.role
            existing.updated_at = now
            member = existing
        else:
            member = MembershipRow(
                id=_new_id(),
                tenant_id=row.tenant_id,
                principal=principal,
                role=row.role,
                invited_by=row.invited_by,
                created_at=now,
                updated_at=now,
            )
            session.add(member)
        row.accepted_at = now
        row.accepted_by = principal
        session.commit()
        session.refresh(row)
        session.refresh(member)
        return _to_invitation(row), _to_membership(member)


# ---------------------------------------------------------------- seats


def count_seats_in_use(tenant_id: str) -> dict[str, int]:
    """Return the seat accounting for ``tenant_id``.

    A seat is one of:

    * an active membership row (any role), OR
    * a pending invitation (not yet accepted, not revoked, not expired).

    The pair add up to ``total`` -- the number that gets compared to the
    ``seat_limit`` cap. Existing members are never counted twice (an
    accepted invitation is no longer pending).
    """
    if not tenant_id:
        return {"members": 0, "pending_invitations": 0, "total": 0}
    members = len(list_members(tenant_id))
    pending = len(list_invitations(tenant_id, include_inactive=False))
    return {
        "members": members,
        "pending_invitations": pending,
        "total": members + pending,
    }


def _count_seats_in_session(session, tenant_id: str) -> int:
    """Same as :func:`count_seats_in_use`'s ``total`` but reuses an open
    SQLAlchemy session. Used inside the same transaction as the row that
    is about to be added so the check and the insert see consistent state.
    """
    now = datetime.now(UTC)
    member_rows = session.execute(
        select(MembershipRow).where(MembershipRow.tenant_id == tenant_id)
    ).scalars().all()
    invite_rows = session.execute(
        select(InvitationRow).where(InvitationRow.tenant_id == tenant_id)
    ).scalars().all()
    pending = 0
    for r in invite_rows:
        if r.accepted_at is not None or r.revoked_at is not None:
            continue
        expires_at = r.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < now:
            continue
        pending += 1
    return len(member_rows) + pending


def get_seat_limit(tenant_id: str) -> int | None:
    """Return the seat cap for ``tenant_id``, or ``None`` if unlimited."""
    if not tenant_id:
        return None
    # Local import keeps this module free of a hard cycle with db; we
    # only need the row type at call time.
    from .db import TenantSettingsRow, get_session as _gs

    with _gs() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            return None
        return row.seat_limit


def set_seat_limit(
    tenant_id: str, seat_limit: int | None, updated_by: str | None
) -> int | None:
    """Persist a new seat cap. ``None`` means unlimited.

    Lowering the cap below the current usage is allowed: it blocks all
    new seats but does not retro-evict existing members. The admin must
    revoke pending invites or remove members to come back under quota.
    Raises ``ValueError`` on invalid input (negative, zero, or beyond
    :data:`SEAT_LIMIT_MAX`).
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    if seat_limit is not None:
        if not isinstance(seat_limit, int) or isinstance(seat_limit, bool):
            raise ValueError("seat_limit must be an integer or null")
        if seat_limit < 1:
            raise ValueError("seat_limit must be at least 1, or null for unlimited")
        if seat_limit > SEAT_LIMIT_MAX:
            raise ValueError(f"seat_limit must not exceed {SEAT_LIMIT_MAX}")

    from .db import TenantSettingsRow, get_session as _gs, init_db as _init

    _init()
    with _gs() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                seat_limit=seat_limit,
                updated_at=now,
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.seat_limit = seat_limit
            row.updated_at = now
            row.updated_by = updated_by
        s.commit()
    return seat_limit


def _enforce_seat_capacity(session, tenant_id: str) -> None:
    """Raise :class:`SeatLimitExceeded` if adding one more seat would
    exceed ``seat_limit``. NULL/0 limit means unlimited.

    Called from inside ``upsert_member`` (only for net-new members) and
    ``create_invitation`` (for every new invitation, since pending
    invites count toward the cap).
    """
    from .db import TenantSettingsRow

    row = session.execute(
        select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
    ).scalar_one_or_none()
    limit = row.seat_limit if row is not None else None
    if not limit or limit <= 0:
        return
    in_use = _count_seats_in_session(session, tenant_id)
    if in_use >= limit:
        raise SeatLimitExceeded(tenant_id, limit, in_use)
