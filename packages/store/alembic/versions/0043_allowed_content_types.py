"""Per-tenant allowed upload content types (DLP control).

Adds ``allowed_content_types`` to ``tenant_settings``. When set to a
non-empty JSON list, the classify routes refuse any upload whose
``Content-Type`` is not on the list before the bytes touch disk or the
model. NULL or empty list keeps the legacy behaviour: any
``image/*`` MIME type is accepted.

Why this matters for procurement:
A buyer's data-loss prevention review will ask the SaaS vendor to
demonstrate per-workspace control over what file formats may enter the
pipeline. SVG (active content), TIFF (parsing surface), and HEIC
(closed format) are common excludes; financial-services tenants often
want to lock the surface down to ``image/png`` and ``image/jpeg``
only. Existing per-tenant ``max_upload_bytes`` (0042) gates size; this
column gates type. Pairs with SOC 2 CC6.6 and ISO 27001 A.8.24.

Revision ID: 0043_allowed_content_types
Revises: 0042_webhook_autodisable
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0043_allowed_content_types"
down_revision = "0042_webhook_autodisable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch:
        batch.add_column(
            sa.Column("allowed_content_types", sa.JSON(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch:
        batch.drop_column("allowed_content_types")
