"""Per-tenant OIDC IdP credentials on tenant_settings.

Adds ``oidc_issuer``, ``oidc_client_id``, ``oidc_client_secret``,
``oidc_scopes``, ``oidc_updated_at``. When populated, ``/auth/sso/login``
resolves the tenant by email domain and uses the tenant's own IdP
instead of the deployment-level shared OIDC client.

Revision ID: 0022_tenant_oidc
Revises: 0021_legal_holds
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_tenant_oidc"
down_revision = "0021_legal_holds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_settings", sa.Column("oidc_issuer", sa.String(length=256), nullable=True))
    op.add_column("tenant_settings", sa.Column("oidc_client_id", sa.String(length=256), nullable=True))
    op.add_column("tenant_settings", sa.Column("oidc_client_secret", sa.String(length=512), nullable=True))
    op.add_column("tenant_settings", sa.Column("oidc_scopes", sa.String(length=256), nullable=True))
    op.add_column("tenant_settings", sa.Column("oidc_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant_settings", "oidc_updated_at")
    op.drop_column("tenant_settings", "oidc_scopes")
    op.drop_column("tenant_settings", "oidc_client_secret")
    op.drop_column("tenant_settings", "oidc_client_id")
    op.drop_column("tenant_settings", "oidc_issuer")
