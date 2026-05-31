"""Add pinned flag to classifications.

Revision ID: 0008_pinned
Revises: 0007_tenant_settings
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_pinned"
down_revision = "0007_tenant_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "classifications",
        sa.Column(
            "pinned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_classifications_pinned",
        "classifications",
        ["pinned"],
    )


def downgrade() -> None:
    op.drop_index("ix_classifications_pinned", table_name="classifications")
    op.drop_column("classifications", "pinned")
