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
    "max_conf",
    "sort",
    "tag",
    "tags",
    "pinned",
    "limit",
}

# Deterministic processing order: ``min_conf`` must be coerced before
# ``max_conf`` so the inverted-range guard below always drops ``max_conf``
# (the later bound) rather than whichever key the set happened to yield
# first. Order also fixes the public JSON shape on round-trip.
_FILTER_KEY_ORDER: tuple[str, ...] = (
    "category",
    "q",
    "since",
    "until",
    "min_conf",
    "max_conf",
    "sort",
    "tag",
    "tags",
    "pinned",
    "limit",
)
assert set(_FILTER_KEY_ORDER) == ALLOWED_FILTER_KEYS

# Mirror of the per-record cap enforced on the history route's ``tags`` query
# parameter. Keeps stored views from holding more tags than a list call would
# accept on replay.
MAX_TAGS_IN_VIEW = 8
TAG_MAX_LEN = 32

# Sort values mirror the history page UI. Keep in sync with web/app/shots.
ALLOWED_SORTS = {"new", "old", "conf_desc", "conf_asc"}


def _coerce_filters(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("filters must be an object")
    out: dict[str, Any] = {}
    for key in _FILTER_KEY_ORDER:
        if key not in raw:
            continue
        v = raw[key]
        # ``pinned=False`` and ``tags=[]`` are meaningful filters, so only
        # treat ``None``/empty string as "unset" here. List/dict emptiness is
        # handled inside the per-key branches.
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
        elif key in ("min_conf", "max_conf"):
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            f = max(0.0, min(1.0, f))
            # Drop an inverted range on save so a replay does not 400. The
            # history route already rejects inverted ranges at request time;
            # mirroring that here keeps a saved view always replayable.
            if key == "max_conf" and "min_conf" in out and f < out["min_conf"]:
                continue
            if key == "min_conf" and "max_conf" in out and f > out["max_conf"]:
                continue
            out[key] = f
        elif key == "pinned":
            if isinstance(v, bool):
                out[key] = v
            elif isinstance(v, str):
                low = v.strip().lower()
                if low in ("true", "1", "yes"):
                    out[key] = True
                elif low in ("false", "0", "no"):
                    out[key] = False
        elif key == "tags":
            if not isinstance(v, list):
                continue
            seen: list[str] = []
            for t in v:
                if not isinstance(t, str):
                    continue
                norm = t.strip().lower()
                if not norm or len(norm) > TAG_MAX_LEN:
                    continue
                if norm not in seen:
                    seen.append(norm)
                if len(seen) >= MAX_TAGS_IN_VIEW:
                    break
            if seen:
                out[key] = seen
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

    def delete_by_tenant(self, tenant_id: str) -> int:
        """Hard-delete every saved view scoped to ``tenant_id``.

        Workspace-wide erasure helper. Returns the number of rows removed.
        """
        from sqlalchemy import delete as sa_delete

        if not tenant_id:
            raise ValueError("tenant_id is required.")
        with get_session() as s:
            stmt = sa_delete(SavedViewRow).where(
                or_(
                    SavedViewRow.tenant_id == tenant_id,
                    SavedViewRow.tenant_id.is_(None),
                )
            )
            result = s.execute(stmt)
            s.commit()
            return int(result.rowcount or 0)

    def list_by_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        """Return every saved view in ``tenant_id`` for workspace-wide export."""
        if not tenant_id:
            raise ValueError("tenant_id is required.")
        stmt = (
            select(SavedViewRow)
            .where(
                or_(
                    SavedViewRow.tenant_id == tenant_id,
                    SavedViewRow.tenant_id.is_(None),
                )
            )
            .order_by(desc(SavedViewRow.updated_at))
        )
        with get_session() as s:
            rows = s.execute(stmt).scalars().all()
        return [
            {**_row_to_dict(r), "principal": r.principal, "tenant_id": r.tenant_id}
            for r in rows
        ]
