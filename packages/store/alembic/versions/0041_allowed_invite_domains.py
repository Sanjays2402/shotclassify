"""Per-tenant allowed email domains for invitations and SSO auto-join.

Adds ``allowed_invite_domains`` (JSON list of normalized email domains)
to ``tenant_settings``. When the list is non-empty, every membership
that this tenant ever creates -- via the invite-by-email flow OR the
SSO domain auto-join path -- must have an email whose domain matches
one of the listed entries, otherwise the API rejects the call with
HTTP 422 and the SSO auto-join silently no-ops.

NULL or empty list keeps the legacy "any email" behaviour so existing
deployments are unaffected until an admin opts in. Maximum 64 domains
per tenant is enforced at the API layer. This is the SOC 2 CC6.2 /
"shadow-IT prevention" control procurement teams ask for when their
employees might otherwise be invited to a third-party SaaS workspace
using a personal address.

Revision ID: 0041_allowed_invite_domains
Revises: 0040_tenant_freeze
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041_allowed_invite_domains"
down_revision = "0040_tenant_freeze"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch:
        batch.add_column(
            sa.Column("allowed_invite_domains", sa.JSON(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch:
        batch.drop_column("allowed_invite_domains")
