"""MFA recovery (backup) codes.

Stores one row per generated single-use backup code so a user who loses
their authenticator can still satisfy a step-up challenge. Codes are
stored hashed (SHA-256, salted with a per-row salt) and burned on use.
Generating a new set invalidates the previous batch.

Required by enterprise procurement when MFA is mandated: SOC 2 CC6.1
("authorized users can recover access through documented procedures"),
ISO 27001 A.9.4.2, and NIST 800-63B 5.1.2 ("memorized look-up secrets
SHALL be used at most once").

Revision ID: 0027_mfa_recovery_codes
Revises: 0026_support_access_grants
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_mfa_recovery_codes"
down_revision = "0026_support_access_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("principal", sa.String(length=128), nullable=False, index=True),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("salt", sa.String(length=64), nullable=False),
        sa.Column(
            "batch_id",
            sa.String(length=64),
            nullable=False,
            index=True,
            comment="Identifier shared by all codes generated together; lets a regeneration burn the old set in one shot.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_mfa_recovery_codes_principal_used",
        "mfa_recovery_codes",
        ["principal", "used_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_mfa_recovery_codes_principal_used", table_name="mfa_recovery_codes")
    op.drop_table("mfa_recovery_codes")
