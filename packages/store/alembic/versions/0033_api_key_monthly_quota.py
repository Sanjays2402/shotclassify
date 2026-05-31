"""Per-API-key monthly call quota.

Adds ``monthly_quota`` (NULLABLE INTEGER) to ``api_keys`` and a new
``api_key_monthly_usage`` counter table keyed on
(``key_id``, ``year_month``). When ``monthly_quota`` is set, the rate
limit middleware atomically increments the matching counter on every
request authenticated by that key. Once the counter would exceed the
quota, the request is rejected with HTTP 429 and the standard
``X-RateLimit-*`` headers (``Scope=api_key_month``, ``Remaining=0``,
``Reset`` = seconds until the start of the next UTC month) plus a
``Retry-After`` header.

This is the procurement-side control that lets a buyer cap the spend a
single integration credential can incur in a billing period without
revoking it outright. Per-minute caps already exist via
``rpm_override``; the monthly cap is what closes runaway-bill scenarios
when the per-minute rate is acceptable but the sustained 24/7 draw is
not. NULL keeps the existing unbounded behaviour so this is a safe
additive migration for live deployments.

Revision ID: 0033_api_key_monthly_quota
Revises: 0032_webhook_egress_allowed_hosts
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_api_key_monthly_quota"
down_revision = "0032_webhook_egress_allowed_hosts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("api_keys") as batch:
        batch.add_column(sa.Column("monthly_quota", sa.Integer(), nullable=True))
    op.create_table(
        "api_key_monthly_usage",
        sa.Column("key_id", sa.String(64), nullable=False),
        sa.Column("year_month", sa.String(7), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("key_id", "year_month"),
    )
    op.create_index(
        "ix_api_key_monthly_usage_key_id",
        "api_key_monthly_usage",
        ["key_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_api_key_monthly_usage_key_id", table_name="api_key_monthly_usage")
    op.drop_table("api_key_monthly_usage")
    with op.batch_alter_table("api_keys") as batch:
        batch.drop_column("monthly_quota")
