"""Per-API-key source-IP allowlist (allowed_cidrs).

Adds a JSON ``allowed_cidrs`` column to ``api_keys``. When the list is
empty (NULL or ``[]``) the key is accepted from any source IP, preserving
existing behaviour. When the list contains one or more CIDRs the auth
middleware rejects API-key requests whose source IP is not contained by
any range with HTTP 403 ``api_key_ip_not_allowed``.

This is the per-credential complement to the existing per-tenant IP
allowlist. Enterprises typically need both: the tenant allowlist gates
the dashboard, the per-key allowlist locks individual machine-to-machine
credentials (CI runners, vendor integrations, prod-only batch jobs) to
the addresses they are supposed to call from.

Revision ID: 0025_api_key_allowed_cidrs
Revises: 0024_mfa_policy
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_api_key_allowed_cidrs"
down_revision = "0024_mfa_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("api_keys") as batch:
        batch.add_column(sa.Column("allowed_cidrs", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("api_keys") as batch:
        batch.drop_column("allowed_cidrs")
