"""Member suspension flag for offboarding without losing audit history.

Adds ``suspended_at``, ``suspended_by``, and ``suspension_reason`` to
``memberships``. A suspended membership row is kept in place so the
audit log still resolves the principal to a recognized name, but the
auth middleware treats the row as an active deny: the principal cannot
load any tenant-scoped resource and receives 403 with
``membership_suspended``. Reinstating the membership clears the three
columns.

Procurement reviewers (SOC2 CC6.3, ISO 27001 A.9.2.6) require that
access is removed in a timely manner upon termination AND that the
trail of who did what survives the removal. Hard-deleting the
membership row satisfies the first requirement but loses the second.
This column gives admins both: instant lockout AND attribution.

Revision ID: 0037_membership_suspension
Revises: 0036_api_key_owner_email
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_membership_suspension"
down_revision = "0036_api_key_owner_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("memberships") as batch:
        batch.add_column(sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("suspended_by", sa.String(128), nullable=True))
        batch.add_column(sa.Column("suspension_reason", sa.String(512), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("memberships") as batch:
        batch.drop_column("suspension_reason")
        batch.drop_column("suspended_by")
        batch.drop_column("suspended_at")
