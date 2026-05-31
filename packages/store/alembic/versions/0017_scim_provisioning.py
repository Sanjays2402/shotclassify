"""SCIM 2.0 provisioning columns on tenant_settings.

Revision ID: 0017_scim_provisioning
Revises: 0016_webhooks
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_scim_provisioning"
down_revision = "0016_webhooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Feature flag. When False the /scim/v2/* endpoints return 401 for this
    # tenant even if a stale token hash is still on the row, so disabling
    # SCIM in the admin console truly breaks glass without a token rotation.
    op.add_column(
        "tenant_settings",
        sa.Column(
            "scim_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    # SHA-256 of the bearer token. Indexed so token-to-tenant lookup on every
    # SCIM request is O(log n) without scanning the table or leaking the
    # plaintext into query logs.
    op.add_column(
        "tenant_settings",
        sa.Column("scim_token_hash", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_tenant_settings_scim_token_hash",
        "tenant_settings",
        ["scim_token_hash"],
    )
    # Last four characters of the plaintext, kept for the admin UI so an
    # operator can confirm which token is live without us ever having to
    # store the plaintext anywhere.
    op.add_column(
        "tenant_settings",
        sa.Column("scim_token_last_four", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "tenant_settings",
        sa.Column("scim_token_rotated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The role assigned to users that the IdP creates via SCIM. Locked to
    # viewer/operator at the API layer so a misconfigured IdP rule cannot
    # auto-mint workspace admins.
    op.add_column(
        "tenant_settings",
        sa.Column("scim_default_role", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_settings", "scim_default_role")
    op.drop_column("tenant_settings", "scim_token_rotated_at")
    op.drop_column("tenant_settings", "scim_token_last_four")
    op.drop_index("ix_tenant_settings_scim_token_hash", table_name="tenant_settings")
    op.drop_column("tenant_settings", "scim_token_hash")
    op.drop_column("tenant_settings", "scim_enabled")
