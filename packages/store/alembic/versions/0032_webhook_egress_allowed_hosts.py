"""Per-tenant webhook egress host allowlist.

Adds ``webhook_egress_allowed_hosts`` (JSON) to ``tenant_settings``.
When non-empty, every webhook subscription URL for the tenant must
resolve to a hostname that matches one of the configured entries
(exact hostname, or leading-dot suffix like ``.example.com`` which
matches the apex and any subdomain). The webhook store enforces this
both at subscription create / rotate time AND at delivery time, so a
host removed from the policy stops receiving events on the very next
attempt. NULL or empty keeps legacy behaviour: only the deployment
SSRF block (private addresses, loopback, link-local, cloud metadata)
applies.

This is the SOC 2 CC6.7 / procurement control that lets a buyer prove
that webhook traffic from their workspace can never leave a vetted
list of destinations, even if a compromised admin tries to point a
subscription at an attacker-controlled URL.

Revision ID: 0032_webhook_egress_allowed_hosts
Revises: 0031_api_key_max_active
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_webhook_egress_allowed_hosts"
down_revision = "0031_api_key_max_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_settings",
        sa.Column("webhook_egress_allowed_hosts", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_settings", "webhook_egress_allowed_hosts")
