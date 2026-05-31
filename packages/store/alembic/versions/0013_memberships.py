"""Workspace memberships and email invitations.

Adds the team-management surface enterprise procurement requires:
``memberships`` binds a principal to a tenant with a role (so role
assignment is no longer a redeploy via ``AUTH_ROLE_MAP``) and
``invitations`` carries pending email invites with a one-shot token,
expiry, and revocation. Both tables are tenant-scoped and every query in
the application layer filters by ``tenant_id`` so a member of tenant A
cannot enumerate or accept invites from tenant B.

Revision ID: 0013_memberships
Revises: 0012_api_key_scopes
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_memberships"
down_revision = "0012_api_key_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memberships",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("principal", sa.String(128), nullable=False, index=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("invited_by", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index(
        "ix_memberships_tenant_principal",
        "memberships",
        ["tenant_id", "principal"],
        unique=True,
    )

    op.create_table(
        "invitations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("email", sa.String(255), nullable=False, index=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("invited_by", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.String(128), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_invitations_tenant_email",
        "invitations",
        ["tenant_id", "email"],
    )


def downgrade() -> None:
    op.drop_index("ix_invitations_tenant_email", table_name="invitations")
    op.drop_table("invitations")
    op.drop_index("ix_memberships_tenant_principal", table_name="memberships")
    op.drop_table("memberships")
