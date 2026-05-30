"""Add principal column to classifications for GDPR data lifecycle.

Revision ID: 0003_classification_principal
Revises: 0002_audit_log
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_classification_principal"
down_revision = "0002_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "classifications",
        sa.Column("principal", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_classifications_principal",
        "classifications",
        ["principal"],
    )


def downgrade() -> None:
    op.drop_index("ix_classifications_principal", table_name="classifications")
    op.drop_column("classifications", "principal")
