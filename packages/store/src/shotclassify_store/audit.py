"""Persisted audit log repository.

Records authenticated, state-changing requests so operators can answer
"who did what, when, against which resource" without re-deriving it from logs.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select

from .db import AuditLogRow, get_session, init_db


class AuditRepository:
    def __init__(self) -> None:
        init_db()

    def record(
        self,
        *,
        principal: str,
        method: str,
        path: str,
        status_code: int,
        request_id: str | None = None,
        client_ip: str | None = None,
        user_agent: str | None = None,
        elapsed_ms: int = 0,
        target_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        entry_id = uuid.uuid4().hex
        row = AuditLogRow(
            id=entry_id,
            created_at=datetime.now(UTC),
            principal=principal[:128],
            method=method[:8],
            path=path[:512],
            status_code=status_code,
            request_id=request_id,
            client_ip=client_ip[:64] if client_ip else None,
            user_agent=user_agent[:512] if user_agent else None,
            elapsed_ms=elapsed_ms,
            target_id=target_id,
            extra=extra or {},
        )
        with get_session() as s:
            s.add(row)
            s.commit()
        return entry_id

    def list(
        self,
        *,
        limit: int = 100,
        principal: str | None = None,
        path_prefix: str | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(AuditLogRow).order_by(desc(AuditLogRow.created_at)).limit(limit)
        if principal:
            stmt = stmt.where(AuditLogRow.principal == principal)
        if path_prefix:
            stmt = stmt.where(AuditLogRow.path.like(f"{path_prefix}%"))
        with get_session() as s:
            rows = s.execute(stmt).scalars().all()
        return [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "principal": r.principal,
                "method": r.method,
                "path": r.path,
                "status_code": r.status_code,
                "request_id": r.request_id,
                "client_ip": r.client_ip,
                "user_agent": r.user_agent,
                "elapsed_ms": r.elapsed_ms,
                "target_id": r.target_id,
                "extra": r.extra or {},
            }
            for r in rows
        ]

    def count(self) -> int:
        from sqlalchemy import func

        with get_session() as s:
            return int(s.execute(select(func.count(AuditLogRow.id))).scalar() or 0)

    def list_for_principal(self, principal: str, limit: int = 10000) -> list[dict[str, Any]]:
        return self.list(limit=limit, principal=principal)

    def delete_for_principal(self, principal: str) -> int:
        """Hard-delete every audit row owned by ``principal`` (GDPR erasure)."""
        from sqlalchemy import delete as sa_delete

        with get_session() as s:
            result = s.execute(
                sa_delete(AuditLogRow).where(AuditLogRow.principal == principal)
            )
            s.commit()
            return int(result.rowcount or 0)
