"""Tenant-consented support access grants.

Closes the long-standing back door where a vendor-side ``admin`` could
flip ``X-Tenant: <other>`` and silently read or mutate any customer
workspace. With this table the tenant resolution middleware refuses
cross-tenant admin scoping unless an active, unexpired grant exists for
that target workspace, and every cross-tenant audit row carries the
grant id in ``extra`` so the customer can later prove which ticket
authorized the access.

Revision ID: 0026_support_access_grants
Revises: 0025_api_key_allowed_cidrs
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_support_access_grants"
down_revision = "0025_api_key_allowed_cidrs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_access_grants",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("allowed_admin", sa.String(256), nullable=True),
        sa.Column("created_by", sa.String(256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(256), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_support_access_tenant_active",
        "support_access_grants",
        ["tenant_id", "revoked_at", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_support_access_tenant_active", table_name="support_access_grants"
    )
    op.drop_table("support_access_grants")
