"""Per-tenant cap on the number of active (non-revoked) API keys.

Adds ``api_key_max_active`` to ``tenant_settings``. When set, attempts
to mint a new DB-backed API key (or rotate an existing one, which mints
a successor) are rejected with HTTP 422 ``api_key_max_active_reached``
once the workspace already has that many active (non-revoked) keys. The
cap counts every active key for the tenant; revoking a stale key frees
a slot immediately. NULL keeps the legacy unbounded behaviour so
existing deployments are unaffected until an admin opts in.

Enterprise procurement and SOC 2 CC6.1 / NIST AC-2 routinely ask
"how do you prevent unbounded service-credential sprawl in a single
workspace?" A per-tenant cap turns the answer into a hard limit that
admins can document, audit, and enforce without code changes.

Revision ID: 0031_api_key_max_active
Revises: 0030_api_key_inactivity_days
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_api_key_max_active"
down_revision = "0030_api_key_inactivity_days"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_settings",
        sa.Column("api_key_max_active", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_settings", "api_key_max_active")
