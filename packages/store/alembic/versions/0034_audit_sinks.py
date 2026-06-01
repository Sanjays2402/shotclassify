"""Per-tenant SIEM audit sinks.

Adds an ``audit_sinks`` table so a workspace owner can register one or
more outbound HTTPS endpoints that receive a signed copy of every audit
event written by the AuditLogMiddleware. This is the boring-but-required
SOC2 / enterprise-procurement integration: forward our audit trail into
Splunk, Datadog, Sumo Logic, or any HTTPS log collector so the buyer's
security team can correlate it with their existing detections.

Signatures use ``HMAC-SHA256(SHA256(secret), body)`` to mirror the
webhook scheme; the plaintext secret is shown once at create time and
only its SHA-256 hash is persisted, so a DB leak cannot be used to
forge events.

Revision ID: 0034_audit_sinks
Revises: 0033_api_key_monthly_quota
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034_audit_sinks"
down_revision = "0033_api_key_monthly_quota"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_sinks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("secret_hash", sa.String(128), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(16), nullable=True),
        sa.Column("last_error", sa.String(512), nullable=True),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_audit_sinks_tenant_active",
        "audit_sinks",
        ["tenant_id", "active"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_sinks_tenant_active", table_name="audit_sinks")
    op.drop_table("audit_sinks")
