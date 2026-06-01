"""Per-tenant emergency freeze (write lockdown).

Adds four columns to ``tenant_settings`` so a workspace owner can
engage a tenant-wide write lockdown during a suspected breach or other
incident:

* ``freeze_mode`` (bool, default false) -- when true the freeze
  middleware rejects every mutating HTTP request scoped to this tenant
  with HTTP 423 ``tenant_frozen``. Reads are unaffected so investigators
  and exporters keep working.
* ``freeze_reason`` (str, nullable) -- short free-form note the
  middleware surfaces in the error body and the dashboard banner so
  members understand why the lockdown is engaged. Bounded to 256 chars
  in the API layer.
* ``freeze_engaged_at`` (datetime, nullable) -- when the freeze was
  last engaged. Used by the admin console and audit log so the
  ``revoked at`` / ``engaged at`` story is unambiguous during an
  incident review.
* ``freeze_engaged_by`` (str, nullable) -- principal that engaged the
  freeze. Also captured by the audit middleware via the mutation
  record itself; persisted here so the banner can name the owner who
  is currently holding the lockdown.

The default (false / null) keeps every existing deployment unchanged
until an owner opts in. Lifting the freeze clears all four columns so
the row reads as "never engaged" for clean banner copy.

Revision ID: 0040_tenant_freeze
Revises: 0039_audit_retention_days
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0040_tenant_freeze"
down_revision = "0039_audit_retention_days"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch:
        batch.add_column(
            sa.Column(
                "freeze_mode",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(sa.Column("freeze_reason", sa.String(256), nullable=True))
        batch.add_column(
            sa.Column(
                "freeze_engaged_at", sa.DateTime(timezone=True), nullable=True
            )
        )
        batch.add_column(
            sa.Column("freeze_engaged_by", sa.String(128), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch:
        batch.drop_column("freeze_engaged_by")
        batch.drop_column("freeze_engaged_at")
        batch.drop_column("freeze_reason")
        batch.drop_column("freeze_mode")
