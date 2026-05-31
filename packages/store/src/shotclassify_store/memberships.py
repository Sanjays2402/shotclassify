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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "principal": self.principal,
            "role": self.role,
            "invited_by": self.invited_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
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
    """Return the role for ``(tenant_id, principal)`` or ``None`` if no row.

    Used by the auth middleware to override the env-var role map. Returns
    ``None`` when either argument is missing or no membership exists so
    the caller can fall back to legacy behaviour.
    """
    if not tenant_id or not principal:
        return None
    with get_session() as session:
        row = session.execute(
            select(MembershipRow)
            .where(MembershipRow.tenant_id == tenant_id)
            .where(MembershipRow.principal == principal)
        ).scalar_one_or_none()
        return row.role if row else None


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
) -> MembershipRecord:
    """Create or update a membership. Returns the resulting record."""
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
    """How many admin members the tenant has, optionally excluding one.

    Used to prevent the last admin from demoting or removing themselves
    and locking the workspace out of role management.
    """
    if not tenant_id:
        return 0
    with get_session() as session:
        q = (
            select(MembershipRow)
            .where(MembershipRow.tenant_id == tenant_id)
            .where(MembershipRow.role == "admin")
        )
        if exclude_principal:
            q = q.where(MembershipRow.principal != exclude_principal)
        return len(session.execute(q).scalars().all())


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
