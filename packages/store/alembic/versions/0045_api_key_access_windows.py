"""Per-API-key time-of-day access windows (access_windows).

Adds a JSON ``access_windows`` column to ``api_keys``. When the value is
NULL or an empty list the key is accepted at any time (legacy behaviour).
When set, the value is a list of allow-windows. Each window is an object:

    {"weekdays": [0, 1, 2, 3, 4],
     "start": "08:00",
     "end": "18:00",
     "tz": "UTC"}

Weekdays are Python ``datetime.weekday()`` integers (Mon=0..Sun=6). Times
are 24h ``HH:MM`` strings. ``tz`` is an IANA zone name (we validate it on
write); we evaluate the wall-clock in that zone so a global ops team can
say "US/Pacific business hours" and have it follow daylight savings
without manual maintenance. Requests arriving outside every window are
rejected at the auth boundary with HTTP 403 ``api_key_outside_window``.

Procurement context: PCI-DSS 7 and SOX change-management reviews routinely
require that machine-to-machine credentials used to mutate production data
are bound to a maintenance / business-hours window. This is the per-key
complement to the existing per-key CIDR allowlist and monthly quota.

Revision ID: 0045_api_key_access_windows
Revises: 0044_allowed_api_key_scopes
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045_api_key_access_windows"
down_revision = "0044_allowed_api_key_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("api_keys") as batch:
        batch.add_column(sa.Column("access_windows", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("api_keys") as batch:
        batch.drop_column("access_windows")
