"""Server-side session tracking.

Adds a ``sessions`` table so signed session cookies can be revoked, listed,
and audited. Each cookie carries an opaque session id (``sid``) that is
validated against this table on every authenticated request. Lets the
admin console answer "what devices are logged in?" and "force-logout
everyone who had access yesterday" -- both standard requirements in any
enterprise security review (SOC2 CC6.1, ISO 27001 A.9.4).

Revision ID: 0010_sessions
Revises: 0009_retention_policy
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_sessions"
down_revision = "0009_retention_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("principal", sa.String(128), nullable=False, index=True),
        sa.Column("tenant_id", sa.String(64), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("client_ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sessions")
