"""Per-API-key custom rate limit (rpm_override).

Lets workspace admins lift or tighten the requests/minute ceiling for a
specific API key without rolling a tenant-wide environment variable. NULL
keeps the existing settings-driven default so this is a safe additive
migration for live deployments.

Revision ID: 0015_api_key_rpm_override
Revises: 0014_privacy_settings
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_api_key_rpm_override"
down_revision = "0014_privacy_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("api_keys") as batch:
        batch.add_column(sa.Column("rpm_override", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("api_keys") as batch:
        batch.drop_column("rpm_override")
