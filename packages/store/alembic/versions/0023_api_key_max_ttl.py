"""Per-tenant max API key TTL policy on tenant_settings.

Adds ``api_key_max_ttl_days``: an integer cap (in days) on every newly
minted or rotated API key for that tenant. NULL means no policy, so
existing deployments keep working unchanged.

Enterprise procurement and SOC 2 CC6.1 routinely ask for documented
credential rotation. Enforcing the cap at creation (and shortening
rotated-successor expiry) makes the answer "yes, technically enforced"
instead of "yes, by policy doc".

Revision ID: 0023_api_key_max_ttl
Revises: 0022_tenant_oidc
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_api_key_max_ttl"
down_revision = "0022_tenant_oidc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_settings",
        sa.Column("api_key_max_ttl_days", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_settings", "api_key_max_ttl_days")
