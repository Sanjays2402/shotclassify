"""Customer-Managed Encryption Key (CMEK) reference on tenant_settings.

Records the per-workspace declaration that the tenant's data is (or
should be) encrypted at rest with a key the customer controls in their
own KMS. The actual envelope-encryption integration is a deployment
concern owned by the storage layer. These columns are the authoritative
tenant declaration that procurement, audit, and the operator-side CMEK
adapter all read.

Columns:
* ``cmek_provider`` -- one of ``aws-kms``, ``gcp-kms``, ``azure-kv``,
  ``hashicorp-vault``. NULL when disabled.
* ``cmek_key_uri`` -- fully-qualified resource URI for the key in the
  customer's KMS (e.g. an AWS KMS ARN). NULL when disabled.
* ``cmek_mode`` -- ``disabled`` (default), ``advisory`` (declared but
  not gated), or ``required`` (the storage adapter refuses to write
  new objects when the CMEK adapter is unhealthy).
* ``cmek_updated_at`` / ``cmek_updated_by`` -- audit metadata.

Revision ID: 0035_tenant_cmek_reference
Revises: 0034_audit_sinks
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035_tenant_cmek_reference"
down_revision = "0034_audit_sinks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch:
        batch.add_column(sa.Column("cmek_provider", sa.String(32), nullable=True))
        batch.add_column(sa.Column("cmek_key_uri", sa.String(512), nullable=True))
        batch.add_column(sa.Column("cmek_mode", sa.String(16), nullable=True))
        batch.add_column(
            sa.Column("cmek_updated_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("cmek_updated_by", sa.String(256), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch:
        batch.drop_column("cmek_updated_by")
        batch.drop_column("cmek_updated_at")
        batch.drop_column("cmek_mode")
        batch.drop_column("cmek_key_uri")
        batch.drop_column("cmek_provider")
