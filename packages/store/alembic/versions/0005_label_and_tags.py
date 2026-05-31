"""Add user-editable label and tags to classifications.

Revision ID: 0005_label_and_tags
Revises: 0004_tenant_id
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_label_and_tags"
down_revision = "0004_tenant_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "classifications",
        sa.Column("label", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "classifications",
        sa.Column("tags", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("classifications", "tags")
    op.drop_column("classifications", "label")
