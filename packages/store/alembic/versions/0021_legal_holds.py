"""Legal hold registry.

Records active legal/e-discovery holds on a workspace. While at least one
hold is active for a tenant, the retention scheduler MUST skip its purge
pass and every hard-delete code path MUST refuse with HTTP 423 Locked.
Lifting a hold writes ``lifted_at`` and ``lifted_by`` instead of deleting
the row so the audit trail survives.

Revision ID: 0021_legal_holds
Revises: 0020_tenant_seat_limit
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_legal_holds"
down_revision = "0020_tenant_seat_limit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legal_holds",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("matter", sa.String(256), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("lifted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lifted_by", sa.String(128), nullable=True),
        sa.Column("lifted_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_legal_holds_tenant_active",
        "legal_holds",
        ["tenant_id", "lifted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_legal_holds_tenant_active", table_name="legal_holds")
    op.drop_table("legal_holds")
