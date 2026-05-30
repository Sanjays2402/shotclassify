"""Add tenant_id to classifications, api_keys, audit_log for multi-tenancy.

Revision ID: 0004_tenant_id
Revises: 0003_classification_principal
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_tenant_id"
down_revision = "0003_classification_principal"
branch_labels = None
depends_on = None


TABLES = ("classifications", "api_keys", "audit_log")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("tenant_id", sa.String(length=64), nullable=True),
        )
        op.create_index(
            f"ix_{table}_tenant_id",
            table,
            ["tenant_id"],
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
