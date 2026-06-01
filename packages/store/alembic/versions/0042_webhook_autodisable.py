"""Per-tenant webhook auto-disable on consecutive delivery failures.

Adds a circuit-breaker for outbound webhooks. When a tenant configures
``webhook_autodisable_threshold = N`` on ``tenant_settings`` and a
subscription's consecutive failed deliveries reach ``N``, the dispatcher
pauses the subscription (sets ``active = False``) and records why.

Why this matters for procurement:
A buyer's webhook receiver going down is a normal incident; the SaaS
vendor pounding it forever is not. SOC 2 CC7.2 and most enterprise
integration reviews require the vendor to demonstrate automatic
back-pressure that protects downstream systems and that the policy is
configurable per tenant. Pausing (rather than revoking) preserves the
signing secret and delivery history so an operator can resume after the
receiver is healthy again.

New columns:
* ``webhook_subscriptions.consecutive_failure_count`` (int, default 0)
  Resets to 0 on the next successful delivery; incremented on each
  failed delivery. Separate from the lifetime ``failure_count`` so the
  breaker is not skewed by old transient failures.
* ``webhook_subscriptions.auto_disabled_at`` (timestamp, nullable)
  The moment the dispatcher tripped the breaker. NULL if the breaker
  has never tripped (or the subscription was resumed since).
* ``webhook_subscriptions.auto_disabled_reason`` (string, nullable)
  Human-readable explanation surfaced in the admin UI and audit log,
  e.g. ``"5 consecutive failed deliveries (last error: HTTP 503)"``.
* ``tenant_settings.webhook_autodisable_threshold`` (int, nullable)
  NULL = no policy (legacy behaviour, dispatcher never pauses). A
  positive integer enables the breaker at that threshold.

Revision ID: 0042_webhook_autodisable
Revises: 0041_allowed_invite_domains
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0042_webhook_autodisable"
down_revision = "0041_allowed_invite_domains"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("webhook_subscriptions") as batch:
        batch.add_column(
            sa.Column(
                "consecutive_failure_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column("auto_disabled_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("auto_disabled_reason", sa.String(length=256), nullable=True)
        )
    with op.batch_alter_table("tenant_settings") as batch:
        batch.add_column(
            sa.Column("webhook_autodisable_threshold", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch:
        batch.drop_column("webhook_autodisable_threshold")
    with op.batch_alter_table("webhook_subscriptions") as batch:
        batch.drop_column("auto_disabled_reason")
        batch.drop_column("auto_disabled_at")
        batch.drop_column("consecutive_failure_count")
