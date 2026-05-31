"""Per-tenant PII redaction modes and data residency hint.

Revision ID: 0014_privacy_settings
Revises: 0013_memberships
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_privacy_settings"
down_revision = "0013_memberships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # JSON list of redaction modes applied to OCR text and extracted fields
    # before persistence and webhook delivery. Empty/NULL means redaction
    # is disabled and existing data flows through unchanged, so this is a
    # safe additive migration for live tenants.
    op.add_column(
        "tenant_settings",
        sa.Column("pii_redact_modes", sa.JSON(), nullable=True),
    )
    # Free-form region label echoed back as X-Data-Residency. Storage
    # backend selection itself is a deploy-time concern; this column lets
    # a procurement reviewer prove which region label is in effect for
    # their tenant without grepping infra config.
    op.add_column(
        "tenant_settings",
        sa.Column("data_residency", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_settings", "data_residency")
    op.drop_column("tenant_settings", "pii_redact_modes")
