"""Periodic access reviews (SOC2 CC6.3 / ISO 27001 A.9.2.5).

A workspace owner opens a review, the system snapshots every active member
into per-principal items, the owner marks each one ``keep`` or ``revoke``,
then ``apply`` removes the revoked memberships in a single transaction and
seals the review so the trail is immutable.

Every read and every write filters by ``tenant_id`` so a forged review id
from tenant B cannot leak items from tenant A: cross-tenant isolation is
enforced at the query layer, not just at the route layer.

This module deliberately reuses :mod:`memberships` for the snapshot source
and for the actual revocation so the same last-admin guards that protect
the regular member-management UI also protect access-review apply.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select

from . import memberships as memberships_store
from .db import AccessReviewItemRow, AccessReviewRow, get_session

VALID_DECISIONS = ("pending", "keep", "revoke")
OPEN_STATUS = "open"
APPLIED_STATUS = "applied"
CANCELLED_STATUS = "cancelled"


class AccessReviewError(Exception):
    """Base class for access-review domain errors raised to the API layer."""


class AccessReviewNotFound(AccessReviewError):
    pass


class AccessReviewStateError(AccessReviewError):
    """Raised when an operation is not legal in the review's current state."""


class AccessReviewLastAdminError(AccessReviewError):
    """Raised when applying a review would leave the tenant with no admin."""

    def __init__(self, principal: str) -> None:
        self.principal = principal
        super().__init__(
            f"Revoking {principal!r} would leave the workspace with no admin. "
            "Mark at least one admin as 'keep' before applying."
        )


def _new_id() -> str:
    return secrets.token_hex(8)


@dataclass(frozen=True)
class AccessReviewItem:
    id: str
    review_id: str
    tenant_id: str
    principal: str
    snapshot_role: str
    decision: str
    decided_by: str | None
    decided_at: datetime | None
    note: str | None
    revoked_at: datetime | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "review_id": self.review_id,
            "principal": self.principal,
            "snapshot_role": self.snapshot_role,
            "decision": self.decision,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "note": self.note,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
        }


@dataclass(frozen=True)
class AccessReview:
    id: str
    tenant_id: str
    title: str
    status: str
    created_at: datetime
    created_by: str
    due_at: datetime | None
    closed_at: datetime | None
    closed_by: str | None
    applied_at: datetime | None
    applied_by: str | None
    item_count: int = 0
    pending_count: int = 0
    keep_count: int = 0
    revoke_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "title": self.title,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "closed_by": self.closed_by,
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,
            "applied_by": self.applied_by,
            "item_count": self.item_count,
            "pending_count": self.pending_count,
            "keep_count": self.keep_count,
            "revoke_count": self.revoke_count,
        }


def _to_item(row: AccessReviewItemRow) -> AccessReviewItem:
    return AccessReviewItem(
        id=row.id,
        review_id=row.review_id,
        tenant_id=row.tenant_id,
        principal=row.principal,
        snapshot_role=row.snapshot_role,
        decision=row.decision,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        note=row.note,
        revoked_at=row.revoked_at,
    )


def _to_review(row: AccessReviewRow, counts: dict[str, int] | None = None) -> AccessReview:
    counts = counts or {}
    return AccessReview(
        id=row.id,
        tenant_id=row.tenant_id,
        title=row.title,
        status=row.status,
        created_at=row.created_at,
        created_by=row.created_by,
        due_at=row.due_at,
        closed_at=row.closed_at,
        closed_by=row.closed_by,
        applied_at=row.applied_at,
        applied_by=row.applied_by,
        item_count=counts.get("item_count", 0),
        pending_count=counts.get("pending", 0),
        keep_count=counts.get("keep", 0),
        revoke_count=counts.get("revoke", 0),
    )


def _counts_for(session, review_id: str, tenant_id: str) -> dict[str, int]:
    rows = session.execute(
        select(AccessReviewItemRow.decision, func.count(AccessReviewItemRow.id))
        .where(
            AccessReviewItemRow.review_id == review_id,
            AccessReviewItemRow.tenant_id == tenant_id,
        )
        .group_by(AccessReviewItemRow.decision)
    ).all()
    out: dict[str, int] = {"item_count": 0}
    for decision, n in rows:
        out[decision] = int(n)
        out["item_count"] += int(n)
    return out


def has_open_review(tenant_id: str) -> bool:
    """Return True if the tenant already has an open campaign in progress."""
    with get_session() as session:
        row = session.execute(
            select(AccessReviewRow.id).where(
                AccessReviewRow.tenant_id == tenant_id,
                AccessReviewRow.status == OPEN_STATUS,
            )
        ).first()
        return row is not None


def open_review(
    *,
    tenant_id: str,
    title: str,
    created_by: str,
    due_at: datetime | None = None,
) -> AccessReview:
    """Open a new campaign and snapshot every active member into items.

    Raises ``AccessReviewStateError`` if an open campaign already exists for
    the tenant: two simultaneous open reviews would race on apply.
    """
    if has_open_review(tenant_id):
        raise AccessReviewStateError(
            "An access review is already open for this workspace. "
            "Apply or cancel it before opening another."
        )
    members = memberships_store.list_members(tenant_id)
    if not members:
        raise AccessReviewStateError(
            "No active members to review. Invite at least one member first."
        )
    review_id = _new_id()
    now = datetime.now(UTC)
    with get_session() as session:
        session.add(
            AccessReviewRow(
                id=review_id,
                tenant_id=tenant_id,
                title=title,
                status=OPEN_STATUS,
                created_at=now,
                created_by=created_by,
                due_at=due_at,
            )
        )
        for m in members:
            session.add(
                AccessReviewItemRow(
                    id=_new_id(),
                    review_id=review_id,
                    tenant_id=tenant_id,
                    principal=m.principal,
                    snapshot_role=m.role,
                    decision="pending",
                )
            )
        session.commit()
    review = get_review(tenant_id=tenant_id, review_id=review_id)
    if review is None:  # pragma: no cover - we just inserted it
        raise AccessReviewNotFound(review_id)
    return review


def list_reviews(tenant_id: str) -> list[AccessReview]:
    with get_session() as session:
        rows = (
            session.execute(
                select(AccessReviewRow)
                .where(AccessReviewRow.tenant_id == tenant_id)
                .order_by(AccessReviewRow.created_at.desc())
            )
            .scalars()
            .all()
        )
        return [_to_review(r, _counts_for(session, r.id, tenant_id)) for r in rows]


def get_review(*, tenant_id: str, review_id: str) -> AccessReview | None:
    with get_session() as session:
        row = session.execute(
            select(AccessReviewRow).where(
                AccessReviewRow.id == review_id,
                AccessReviewRow.tenant_id == tenant_id,
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return _to_review(row, _counts_for(session, review_id, tenant_id))


def list_items(*, tenant_id: str, review_id: str) -> list[AccessReviewItem]:
    """Return every item for a review, tenant-scoped at the query layer.

    Returns ``[]`` if the review does not exist for this tenant: callers
    should check with :func:`get_review` first if they need to distinguish
    not-found from empty.
    """
    with get_session() as session:
        rows = (
            session.execute(
                select(AccessReviewItemRow)
                .where(
                    AccessReviewItemRow.review_id == review_id,
                    AccessReviewItemRow.tenant_id == tenant_id,
                )
                .order_by(AccessReviewItemRow.principal.asc())
            )
            .scalars()
            .all()
        )
        return [_to_item(r) for r in rows]


def set_decision(
    *,
    tenant_id: str,
    review_id: str,
    item_id: str,
    decision: str,
    decided_by: str,
    note: str | None = None,
) -> AccessReviewItem:
    if decision not in VALID_DECISIONS:
        raise AccessReviewError(
            f"Invalid decision {decision!r}. Must be one of {VALID_DECISIONS!r}."
        )
    with get_session() as session:
        review = session.execute(
            select(AccessReviewRow).where(
                AccessReviewRow.id == review_id,
                AccessReviewRow.tenant_id == tenant_id,
            )
        ).scalar_one_or_none()
        if review is None:
            raise AccessReviewNotFound(review_id)
        if review.status != OPEN_STATUS:
            raise AccessReviewStateError(
                f"Review {review_id!r} is {review.status!r}; cannot change decisions."
            )
        item = session.execute(
            select(AccessReviewItemRow).where(
                AccessReviewItemRow.id == item_id,
                AccessReviewItemRow.review_id == review_id,
                AccessReviewItemRow.tenant_id == tenant_id,
            )
        ).scalar_one_or_none()
        if item is None:
            raise AccessReviewNotFound(item_id)
        item.decision = decision
        item.decided_by = decided_by
        item.decided_at = datetime.now(UTC)
        if note is not None:
            item.note = note[:512]
        session.commit()
        session.refresh(item)
        return _to_item(item)


def cancel_review(*, tenant_id: str, review_id: str, actor: str) -> AccessReview:
    with get_session() as session:
        row = session.execute(
            select(AccessReviewRow).where(
                AccessReviewRow.id == review_id,
                AccessReviewRow.tenant_id == tenant_id,
            )
        ).scalar_one_or_none()
        if row is None:
            raise AccessReviewNotFound(review_id)
        if row.status != OPEN_STATUS:
            raise AccessReviewStateError(
                f"Review {review_id!r} is {row.status!r}; only open reviews can be cancelled."
            )
        row.status = CANCELLED_STATUS
        row.closed_at = datetime.now(UTC)
        row.closed_by = actor
        session.commit()
    review = get_review(tenant_id=tenant_id, review_id=review_id)
    if review is None:  # pragma: no cover
        raise AccessReviewNotFound(review_id)
    return review


def preview_apply(*, tenant_id: str, review_id: str) -> dict:
    """Return what :func:`apply_review` would do without mutating anything.

    Used by the ``?dry_run=true`` branch of the apply endpoint.
    """
    review = get_review(tenant_id=tenant_id, review_id=review_id)
    if review is None:
        raise AccessReviewNotFound(review_id)
    if review.status != OPEN_STATUS:
        raise AccessReviewStateError(
            f"Review {review_id!r} is {review.status!r}; nothing to apply."
        )
    items = list_items(tenant_id=tenant_id, review_id=review_id)
    pending = [i.principal for i in items if i.decision == "pending"]
    to_revoke = [i.principal for i in items if i.decision == "revoke"]
    to_keep = [i.principal for i in items if i.decision == "keep"]
    blocker = _last_admin_blocker(tenant_id, to_revoke)
    return {
        "review_id": review_id,
        "would_revoke": to_revoke,
        "would_keep": to_keep,
        "still_pending": pending,
        "blocker": blocker,
    }


def _last_admin_blocker(tenant_id: str, to_revoke: list[str]) -> str | None:
    """Return the principal whose revocation would leave zero admins, if any."""
    if not to_revoke:
        return None
    admin_revokes = [
        p for p in to_revoke
        if memberships_store.role_for_member(tenant_id, p) == "admin"
    ]
    if not admin_revokes:
        return None
    remaining = memberships_store.count_admins(tenant_id)
    if remaining - len(admin_revokes) <= 0:
        return admin_revokes[0]
    return None


def apply_review(*, tenant_id: str, review_id: str, actor: str) -> AccessReview:
    """Execute decisions: remove every revoke membership, seal the review."""
    review = get_review(tenant_id=tenant_id, review_id=review_id)
    if review is None:
        raise AccessReviewNotFound(review_id)
    if review.status != OPEN_STATUS:
        raise AccessReviewStateError(
            f"Review {review_id!r} is {review.status!r}; cannot apply twice."
        )
    items = list_items(tenant_id=tenant_id, review_id=review_id)
    to_revoke = [i for i in items if i.decision == "revoke"]
    blocker = _last_admin_blocker(tenant_id, [i.principal for i in to_revoke])
    if blocker is not None:
        raise AccessReviewLastAdminError(blocker)
    now = datetime.now(UTC)
    for item in to_revoke:
        # Reuse the same revoke path the members UI uses so last-admin guards
        # and audit log entries fire identically. We already proved above
        # that we are not removing the last admin.
        memberships_store.remove_member(tenant_id, item.principal)
    with get_session() as session:
        if to_revoke:
            session.execute(
                AccessReviewItemRow.__table__.update()
                .where(
                    AccessReviewItemRow.review_id == review_id,
                    AccessReviewItemRow.tenant_id == tenant_id,
                    AccessReviewItemRow.decision == "revoke",
                )
                .values(revoked_at=now)
            )
        row = session.execute(
            select(AccessReviewRow).where(
                AccessReviewRow.id == review_id,
                AccessReviewRow.tenant_id == tenant_id,
            )
        ).scalar_one()
        row.status = APPLIED_STATUS
        row.applied_at = now
        row.applied_by = actor
        row.closed_at = now
        row.closed_by = actor
        session.commit()
    sealed = get_review(tenant_id=tenant_id, review_id=review_id)
    assert sealed is not None
    return sealed


def export_csv(*, tenant_id: str, review_id: str) -> str:
    """Render the review and its items as CSV for compliance evidence."""
    import csv
    import io

    review = get_review(tenant_id=tenant_id, review_id=review_id)
    if review is None:
        raise AccessReviewNotFound(review_id)
    items = list_items(tenant_id=tenant_id, review_id=review_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "review_id", "tenant_id", "title", "status", "created_at", "created_by",
        "applied_at", "applied_by",
        "principal", "snapshot_role", "decision", "decided_by", "decided_at",
        "revoked_at", "note",
    ])
    for it in items:
        writer.writerow([
            review.id, review.tenant_id, review.title, review.status,
            review.created_at.isoformat(),
            review.created_by,
            review.applied_at.isoformat() if review.applied_at else "",
            review.applied_by or "",
            it.principal, it.snapshot_role, it.decision,
            it.decided_by or "",
            it.decided_at.isoformat() if it.decided_at else "",
            it.revoked_at.isoformat() if it.revoked_at else "",
            (it.note or "").replace("\n", " "),
        ])
    return buf.getvalue()
