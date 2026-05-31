"""Workspace-wide MFA enrolment policy on tenant_settings.

Adds ``mfa_required_for_members``: when True, every cookie-authenticated
request from a member of the tenant must have a confirmed TOTP
credential or the auth middleware rejects the call. Defaults to False so
existing deployments are unchanged.

Enterprise security questionnaires (SOC 2 CC6.6, ISO 27001 A.9.4.2,
HIPAA 164.308(a)(5)(ii)(D)) routinely require "all human users must
authenticate with multiple factors". Per-action step-up alone does not
satisfy that: a viewer who never hits an admin mutation never gets
prompted. This policy closes that gap.

Revision ID: 0024_mfa_policy
Revises: 0023_api_key_max_ttl
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_mfa_policy"
down_revision = "0023_api_key_max_ttl"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_settings",
        sa.Column(
            "mfa_required_for_members",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenant_settings", "mfa_required_for_members")
