"""Per-tenant seat limit: tenant_settings.seat_limit.

Caps the number of seats (active memberships + pending invitations)
a workspace can hold. NULL = unlimited. Enforced in
``memberships.upsert_member`` and ``memberships.create_invitation``
so every code path that adds a seat (manual invite, SSO auto-join,
SCIM provisioning) is gated.

Revision ID: 0020_tenant_seat_limit
Revises: 0019_session_ttl_minutes
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_tenant_seat_limit"
down_revision = "0019_session_ttl_minutes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_settings",
        sa.Column("seat_limit", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_settings", "seat_limit")
