"""Per-tenant session idle (inactivity) timeout: tenant_settings.session_idle_minutes.

Adds a column that, when set, makes the auth middleware revoke any
session whose ``last_seen_at`` is older than the configured number of
minutes. NULL preserves the existing behaviour (no idle timeout, lifetime
bounded only by ``session_ttl_minutes`` / the global default).

Revision ID: 0028_session_idle_minutes
Revises: 0027_mfa_recovery_codes
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_session_idle_minutes"
down_revision = "0027_mfa_recovery_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_settings",
        sa.Column("session_idle_minutes", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_settings", "session_idle_minutes")
