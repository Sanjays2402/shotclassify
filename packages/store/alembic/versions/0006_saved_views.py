"""Add per-user saved views (named filter combos for the history page).

Revision ID: 0006_saved_views
Revises: 0005_label_and_tags
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_saved_views"
down_revision = "0005_label_and_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_views",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("principal", sa.String(length=128), nullable=False, index=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=True, index=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_saved_views_principal_tenant",
        "saved_views",
        ["principal", "tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_saved_views_principal_tenant", table_name="saved_views")
    op.drop_table("saved_views")
