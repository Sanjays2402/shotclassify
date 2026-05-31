"""Per-tenant data retention policy.

Adds ``retention_days`` to ``tenant_settings``. When set to a positive
integer, classifications older than that many days are eligible for
purge by the retention job. NULL or 0 disables the policy and keeps
data indefinitely (current behavior).

Revision ID: 0009_retention_policy
Revises: 0008_pinned
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_retention_policy"
down_revision = "0008_pinned"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch:
        batch.add_column(sa.Column("retention_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch:
        batch.drop_column("retention_days")
