"""Webhook signing-secret rotation with overlap window.

Adds two columns on ``webhook_subscriptions`` so that an admin can mint
a new signing secret without breaking integrations that are still
validating with the old one. During the overlap window the dispatcher
signs every outbound payload TWICE: once with the previous secret in
``X-Shotclassify-Signature`` and once with the new secret in
``X-Shotclassify-Signature-Next``. Receivers verify either header,
update their stored secret, and the next rotation drops the old one.

* ``secret_hash_next`` - SHA-256 of the newly issued plaintext secret.
  NULL when no rotation is in flight.
* ``secret_rotated_at`` - timestamp of the most recent rotation start.
  Used by the UI to render "rotated N hours ago" and by operators
  deciding when to finalise.

Both columns are additive and nullable, so existing tenants keep
working without backfill.

Revision ID: 0029_webhook_secret_rotation
Revises: 0028_session_idle_minutes
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_webhook_secret_rotation"
down_revision = "0028_session_idle_minutes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "webhook_subscriptions",
        sa.Column("secret_hash_next", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "webhook_subscriptions",
        sa.Column("secret_rotated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("webhook_subscriptions", "secret_rotated_at")
    op.drop_column("webhook_subscriptions", "secret_hash_next")
