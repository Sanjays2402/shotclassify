"""Per-tenant API key inactivity policy on tenant_settings.

Adds ``api_key_inactivity_days``: an integer number of days a DB-backed
API key may sit idle (no successful auth) before the platform auto-
revokes it on its next presentation. NULL means no policy: existing
deployments keep working unchanged.

Enterprise procurement and SOC 2 CC6.1 routinely ask "what happens to
abandoned service credentials?" Setting a cap and enforcing it at the
auth layer makes the answer "they auto-revoke after N days idle and
the action is written to the audit log" rather than "we trust admins
to clean up". When a key has never been used the policy clock starts
at ``created_at`` so a key minted-and-forgotten is also caught.

* When a tenant policy is set and the presented key's effective
  ``last_used_at`` (falling back to ``created_at``) is older than the
  cap, the auth middleware revokes the key and returns 401
  ``api_key_stale_inactive``. The next request with the same token
  gets the usual "key not found" 401 because revocation is permanent.

* Existing keys are not retroactively shortened at policy set time, so
  a tightened policy does not break live integrations until the keys
  in question actually go idle for longer than the new cap.

Revision ID: 0030_api_key_inactivity_days
Revises: 0029_webhook_secret_rotation
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_api_key_inactivity_days"
down_revision = "0029_webhook_secret_rotation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_settings",
        sa.Column("api_key_inactivity_days", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_settings", "api_key_inactivity_days")
