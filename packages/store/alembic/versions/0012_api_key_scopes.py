"""DB-backed API keys: scopes, expiry, revocation, last-used tracking.

Promotes the previously dormant ``api_keys`` table to the live source of
truth for X-API-Key authentication. Adds the columns enterprise procurement
reviews require: ``scopes`` (JSON list of fine-grained capabilities such as
``read:classifications`` / ``write:classifications`` / ``admin``),
``expires_at`` (optional hard cutoff so keys can be issued with a TTL), and
``revoked_at`` (so revocation is a soft delete that preserves the audit
trail). The ``last_used_at`` column already existed; the auth middleware now
bumps it on every successful request so the admin console can show live
activity per key.

Revision ID: 0012_api_key_scopes
Revises: 0011_sso
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_api_key_scopes"
down_revision = "0011_sso"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("api_keys") as batch:
        batch.add_column(sa.Column("scopes", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("created_by", sa.String(128), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("api_keys") as batch:
        batch.drop_column("created_by")
        batch.drop_column("revoked_at")
        batch.drop_column("expires_at")
        batch.drop_column("scopes")
