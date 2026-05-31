"""Per-tenant OIDC SSO + enforce-SSO flag.

Adds three columns to ``tenant_settings`` so each workspace can be wired to
its own identity provider (Google Workspace, Okta, Azure AD) and require
that every interactive sign-in flow through it:

* ``sso_enforced`` (bool): when True the auth middleware refuses any
  session for this tenant that was not minted via /auth/sso/callback.
* ``sso_domain`` (str): email domain that auto-routes to this tenant from
  /auth/sso/login (e.g. ``acme.com``). Unique per tenant.
* ``sso_provider`` (str): free-form label shown in the admin UI.

Also adds ``auth_method`` to ``sessions`` so the middleware can tell which
flow minted a given cookie. Legacy rows default to ``oauth`` so existing
deployments keep working until enforce-SSO is toggled on. Standard
SOC2 CC6.1 / ISO 27001 A.9.2 control.

Revision ID: 0011_sso
Revises: 0010_sessions
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_sso"
down_revision = "0010_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_settings") as batch:
        batch.add_column(
            sa.Column(
                "sso_enforced",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(sa.Column("sso_domain", sa.String(128), nullable=True))
        batch.add_column(sa.Column("sso_provider", sa.String(64), nullable=True))
    op.create_index(
        "ix_tenant_settings_sso_domain",
        "tenant_settings",
        ["sso_domain"],
        unique=True,
    )
    with op.batch_alter_table("sessions") as batch:
        batch.add_column(
            sa.Column(
                "auth_method",
                sa.String(16),
                nullable=False,
                server_default="oauth",
            )
        )


def downgrade() -> None:
    op.drop_index("ix_tenant_settings_sso_domain", table_name="tenant_settings")
    with op.batch_alter_table("tenant_settings") as batch:
        batch.drop_column("sso_provider")
        batch.drop_column("sso_domain")
        batch.drop_column("sso_enforced")
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("auth_method")
