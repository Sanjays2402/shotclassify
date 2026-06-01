"""Per-tenant audit-log retention policy.

Adds ``audit_retention_days`` to ``tenant_settings``. When set to a positive
integer, audit-log rows older than that many days are eligible for deletion
by the audit-retention purge. NULL or 0 keeps the audit log forever
(current behaviour), so the new policy is opt-in and existing deployments
see no change.

The audit-log purge is a separate knob from the classifications retention
policy (``retention_days``) because enterprise customers commonly negotiate
those two windows independently: GDPR-driven contracts often ask for a
short audit window (90 to 365 days) on data minimisation grounds, while
SOC 2 and HIPAA-aligned customers ask for a long one (>= 365 days, often
seven years). Conflating them is what blocks the deal review.

Revision ID: 0039_audit_retention_days
Revises: 0038_access_reviews
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039_audit_retention_days"
down_revision = "0038_access_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch:
        batch.add_column(sa.Column("audit_retention_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch:
        batch.drop_column("audit_retention_days")
