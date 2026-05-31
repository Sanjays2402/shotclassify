"""Per-tenant security settings: IP allowlist.

Revision ID: 0007_tenant_settings
Revises: 0006_saved_views
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_tenant_settings"
down_revision = "0006_saved_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_settings",
        sa.Column("tenant_id", sa.String(length=64), primary_key=True),
        # JSON list of CIDR strings (IPv4/IPv6). Empty list or NULL means
        # the allowlist is disabled and all source IPs are permitted.
        sa.Column("ip_allowlist", sa.JSON(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("tenant_settings")
