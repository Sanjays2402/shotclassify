"""Per-tenant allowed-scopes policy for API key issuance.

Adds ``allowed_api_key_scopes`` (JSON list of canonical scope ids) to
``tenant_settings``. When the list is non-empty, every API key minted
or rotated for this tenant must request scopes that are a subset of
the policy, otherwise the API rejects the call with HTTP 422.

NULL or empty list keeps the legacy "any valid scope" behaviour so
existing deployments are unaffected until an admin opts in. This is
the SOC 2 CC6.1 / least-privilege control procurement teams ask for
when they want a workspace owner to be unable to ever mint an
``admin``-scoped key (for example, only ``read:classifications`` is
permitted in a read-only audit environment).

Revision ID: 0044_allowed_api_key_scopes
Revises: 0043_allowed_content_types
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0044_allowed_api_key_scopes"
down_revision = "0043_allowed_content_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch:
        batch.add_column(
            sa.Column("allowed_api_key_scopes", sa.JSON(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch:
        batch.drop_column("allowed_api_key_scopes")
