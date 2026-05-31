"""Per-tenant session TTL: tenant_settings.session_ttl_minutes.

Lets each workspace set its own cookie-session lifetime (in minutes).
NULL falls back to the global default in ``sessions.SESSION_TTL``.

Revision ID: 0019_session_ttl_minutes
Revises: 0018_audit_hash_chain
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_session_ttl_minutes"
down_revision = "0018_audit_hash_chain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_settings",
        sa.Column("session_ttl_minutes", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_settings", "session_ttl_minutes")
