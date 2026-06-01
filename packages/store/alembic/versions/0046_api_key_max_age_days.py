"""Per-tenant API key mandatory rotation cap on tenant_settings.

Adds ``api_key_max_age_days``: an integer number of days a DB-backed
API key may exist from its ``created_at`` before the platform auto
revokes it on its next presentation. NULL means no policy: existing
deployments keep working unchanged.

This is the freshness sibling of ``api_key_inactivity_days`` (0030).
Inactivity caps catch credentials that have gone dormant; this cap
catches credentials that are actively used but have simply lived too
long. SOC 2 CC6.1, PCI DSS 3.6.4, NIST SP 800-63B section 5.1.1.2
and most enterprise procurement questionnaires explicitly ask "how
often must keys be rotated?" with the expected answer being a
documented maximum age, not "whenever the customer remembers".

* When a tenant policy is set and the presented key's ``created_at``
  is older than the cap, the auth middleware revokes the key and
  returns 401 ``api_key_rotation_required``. The next request with
  the same token gets the usual "key not found" 401 because
  revocation is permanent.

* Existing keys are not retroactively shortened at policy set time:
  a tightened policy does not break live integrations until the keys
  in question actually exceed the new cap. Admins who want immediate
  enforcement can list and revoke older keys from the admin console.

Revision ID: 0046_api_key_max_age_days
Revises: 0045_api_key_access_windows
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0046_api_key_max_age_days"
down_revision = "0045_api_key_access_windows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_settings",
        sa.Column("api_key_max_age_days", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_settings", "api_key_max_age_days")
