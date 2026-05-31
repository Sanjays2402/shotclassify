"""API-side webhook subscriptions and delivery log.

The Next.js web app already has a file-backed webhook store for its own
proxy route. Enterprise buyers expect webhooks to fire from the API
service itself - the one their server-to-server integrations talk to -
and to be observable through the API admin surface, not just the web
dashboard. This migration adds the two tables that back that:

* ``webhook_subscriptions``: per-tenant outbound endpoints, each with an
  HMAC signing secret, an event filter, and a soft revoke flag.
* ``webhook_deliveries``: every attempt to deliver a payload to a
  subscription. Successes and permanent failures both land here so the
  admin replay UI has the full trail.

Both tables are tenant-scoped via ``tenant_id`` and indexed on the
columns the admin search and the dispatcher actually query.

Revision ID: 0016_webhooks
Revises: 0015_api_key_rpm_override
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_webhooks"
down_revision = "0015_api_key_rpm_override"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("secret_hash", sa.String(128), nullable=False),
        sa.Column("events", sa.JSON, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("success_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("subscription_id", sa.String(64), nullable=False, index=True),
        sa.Column("event", sa.String(64), nullable=False, index=True),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="1"),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("error", sa.String(512), nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("payload_preview", sa.Text, nullable=False, server_default=""),
        sa.Column("signature", sa.String(128), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_subscriptions")
