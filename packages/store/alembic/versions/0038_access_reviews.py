"""Quarterly access review campaigns and per-member decisions.

Adds two tables so workspace owners can run the periodic recertification of
member access that SOC2 CC6.3 and ISO 27001 A.9.2.5 require:

* ``access_reviews`` is one campaign: a window of time during which the
  owner walks the member roster and certifies that each principal still
  needs the role they currently hold.
* ``access_review_items`` is one row per member in that campaign, carrying
  the decision (``pending`` / ``keep`` / ``revoke``), who decided, when,
  and an optional note. ``snapshot_role`` freezes the role the principal
  held at review-start so a later role change does not silently rewrite
  history.

Both tables are scoped by ``tenant_id`` on every read AND every write so
cross-tenant enumeration is impossible at the query layer, not just at
the route layer.

Revision ID: 0038_access_reviews
Revises: 0037_membership_suspension
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038_access_reviews"
down_revision = "0037_membership_suspension"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "access_reviews",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.String(128), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_by", sa.String(128), nullable=True),
    )
    op.create_index(
        "ix_access_reviews_tenant_status",
        "access_reviews",
        ["tenant_id", "status"],
    )
    op.create_table(
        "access_review_items",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("review_id", sa.String(64), nullable=False, index=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("principal", sa.String(128), nullable=False),
        sa.Column("snapshot_role", sa.String(16), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(128), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(512), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_access_review_items_review",
        "access_review_items",
        ["review_id", "tenant_id"],
    )
    op.create_index(
        "ix_access_review_items_tenant_principal",
        "access_review_items",
        ["tenant_id", "principal"],
    )


def downgrade() -> None:
    op.drop_index("ix_access_review_items_tenant_principal", table_name="access_review_items")
    op.drop_index("ix_access_review_items_review", table_name="access_review_items")
    op.drop_table("access_review_items")
    op.drop_index("ix_access_reviews_tenant_status", table_name="access_reviews")
    op.drop_table("access_reviews")
