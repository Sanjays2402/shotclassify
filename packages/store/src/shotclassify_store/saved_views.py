"""Saved views repository: per-user named filter combinations.

A saved view captures the current filter set on the history page (category,
text query, date range, min confidence, sort, tag, page size) so a returning
user can jump back to a workflow in one click instead of re-typing filters.

Scope is always (principal, tenant_id). Rows are never returned to other
principals, and ``tenant_id`` follows the same NULL-tolerant convention used
elsewhere in the store (rows created before a tenant was assigned remain
visible to the default tenant).
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, or_, select

from .db import SavedViewRow, get_session, init_db

NAME_MAX = 128
PER_USER_MAX = 50

# Whitelist of filter keys that the UI is allowed to persist. Anything else is
# dropped on write so a malicious or stale payload can never inflate the row.
ALLOWED_FILTER_KEYS = {
    "category",
    "q",
    "since",
    "until",
    "min_conf",
    "sort",
    "tag",
    "limit",
}

# Sort values mirror the history page UI. Keep in sync with web/app/shots.
ALLOWED_SORTS = {"new", "old", "conf_desc", "conf_asc"}


def _coerce_filters(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("filters must be an object")
    out: dict[str, Any] = {}
    for key in ALLOWED_FILTER_KEYS:
        if key not in raw:
            continue
        v = raw[key]
        if v is None or v == "":
            continue
        if key in ("category", "q", "since", "until", "sort", "tag"):
            if not isinstance(v, str):
                continue
            v = v.strip()
            if not v:
                continue
            if key == "sort" and v not in ALLOWED_SORTS:
                continue
            out[key] = v[:128]
        elif key == "min_conf":
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            out[key] = max(0.0, min(1.0, f))
        elif key == "limit":
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            out[key] = max(1, min(500, n))
    return out


def _clean_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    # Collapse whitespace so list display stays tidy.
    name = re.sub(r"\s+", " ", name)
    return name[:NAME_MAX]


def _row_to_dict(row: SavedViewRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "filters": row.filters or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class SavedViewRepository:
    def __init__(self) -> None:
        init_db()

    def list(
        self, *, principal: str, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        stmt = (
            select(SavedViewRow)
            .where(SavedViewRow.principal == principal)
            .order_by(desc(SavedViewRow.updated_at))
        )
        if tenant_id is not None:
            stmt = stmt.where(
                or_(
                    SavedViewRow.tenant_id == tenant_id,
                    SavedViewRow.tenant_id.is_(None),
                )
            )
        with get_session() as s:
            rows = s.execute(stmt).scalars().all()
        return [_row_to_dict(r) for r in rows]

    def get(
        self, view_id: str, *, principal: str, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        with get_session() as s:
            row = s.get(SavedViewRow, view_id)
            if row is None or row.principal != principal:
                return None
            if tenant_id is not None and row.tenant_id not in (None, tenant_id):
                return None
            return _row_to_dict(row)

    def create(
        self,
        *,
        principal: str,
        name: str,
        filters: dict[str, Any],
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        clean_name = _clean_name(name)
        clean_filters = _coerce_filters(filters)
        now = datetime.now(UTC)
        with get_session() as s:
            existing = s.execute(
                select(SavedViewRow.id).where(SavedViewRow.principal == principal)
            ).all()
            if len(existing) >= PER_USER_MAX:
                raise ValueError(
                    f"saved view limit reached ({PER_USER_MAX} per user)"
                )
            row = SavedViewRow(
                id=uuid.uuid4().hex,
                principal=principal,
                tenant_id=tenant_id,
                name=clean_name,
                filters=clean_filters,
                created_at=now,
                updated_at=now,
            )
            s.add(row)
            s.commit()
            return _row_to_dict(row)

    def update(
        self,
        view_id: str,
        *,
        principal: str,
        name: str | None = None,
        filters: dict[str, Any] | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        with get_session() as s:
            row = s.get(SavedViewRow, view_id)
            if row is None or row.principal != principal:
                return None
            if tenant_id is not None and row.tenant_id not in (None, tenant_id):
                return None
            if name is not None:
                row.name = _clean_name(name)
            if filters is not None:
                row.filters = _coerce_filters(filters)
            row.updated_at = datetime.now(UTC)
            s.commit()
            return _row_to_dict(row)

    def delete(
        self, view_id: str, *, principal: str, tenant_id: str | None = None
    ) -> bool:
        with get_session() as s:
            row = s.get(SavedViewRow, view_id)
            if row is None or row.principal != principal:
                return False
            if tenant_id is not None and row.tenant_id not in (None, tenant_id):
                return False
            s.delete(row)
            s.commit()
            return True
