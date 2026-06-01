"""Mandatory accountable owner for API keys.

Adds ``owner_email`` (NULLABLE STRING(254)) to ``api_keys``. New keys
created via ``/v1/api-keys`` must supply an ``owner_email`` that is a
syntactically valid mailbox; the store rejects anything else with a
422. Existing rows are left as NULL so this is a safe additive
migration for live deployments. Those grandfathered rows are surfaced
by ``GET /v1/api-keys/unowned`` so a workspace admin can see exactly
which legacy credentials still need a human owner assigned.

Procurement reviewers consistently ask "who owns this credential and
who do we call when it leaks" - this is the column that answers it
without joining against the audit log. It's also the field the admin
console uses to drive a quarterly access review: every active key
must have a named owner; unowned keys are flagged in the UI.

Revision ID: 0036_api_key_owner_email
Revises: 0035_tenant_cmek_reference
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_api_key_owner_email"
down_revision = "0035_tenant_cmek_reference"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("api_keys") as batch:
        batch.add_column(sa.Column("owner_email", sa.String(254), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("api_keys") as batch:
        batch.drop_column("owner_email")
