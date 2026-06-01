"""Per-tenant cap on concurrent active sessions per user.

Adds ``max_sessions_per_user`` to ``tenant_settings``: an integer
that limits how many simultaneous, non-revoked, non-expired sessions
any single principal (login) may hold inside this tenant. NULL means
no policy (legacy behaviour: a user can have as many parallel logins
as they want).

This is the "concurrent session control" line item every SOC 2 CC6.1
auditor and enterprise procurement questionnaire asks about. It is
distinct from:

* ``session_ttl_minutes`` (0024): absolute lifetime ceiling.
* ``session_idle_minutes`` (0028): idle timeout per session.

Both of those let a single user accumulate dozens of long-lived
cookies on shared devices; this cap prevents that.

Enforcement is at session creation time: when a new session would
exceed the cap, the oldest active sessions for that principal in the
same tenant are revoked back to ``cap - 1`` before the new row is
written. The oldest-first eviction is intentional so the most
recently used device (typically the active workstation) is kept.

Revision ID: 0047_session_cap_per_user
Revises: 0046_api_key_max_age_days
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0047_session_cap_per_user"
down_revision = "0046_api_key_max_age_days"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_settings",
        sa.Column("max_sessions_per_user", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_settings", "max_sessions_per_user")
