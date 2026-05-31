"""Tamper-evident audit log: per-row hash + prev_hash chain.

Each row now stores a SHA-256 link (`entry_hash`) computed over the
canonical JSON of its own fields concatenated with the previous row's
`entry_hash` (per tenant). Mutating any historical row breaks the chain,
which the new ``/v1/audit/verify`` endpoint detects.

Revision ID: 0018_audit_hash_chain
Revises: 0017_scim_provisioning
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_audit_hash_chain"
down_revision = "0017_scim_provisioning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_log",
        sa.Column("prev_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "audit_log",
        sa.Column("entry_hash", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_audit_log_entry_hash", "audit_log", ["entry_hash"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_entry_hash", table_name="audit_log")
    op.drop_column("audit_log", "entry_hash")
    op.drop_column("audit_log", "prev_hash")
