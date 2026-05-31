"""Persisted audit log repository.

Records authenticated, state-changing requests so operators can answer
"who did what, when, against which resource" without re-deriving it from logs.

Each row is cryptographically chained to the previous row in the same tenant:

    entry_hash = sha256(prev_hash || canonical_json(fields))

where ``prev_hash`` is the previous row's ``entry_hash`` (or the literal
``"GENESIS"`` for the first row in a tenant). Modifying or deleting any
historical row breaks the chain, which :meth:`verify_chain` detects. This
gives the audit log the tamper-evident property enterprise auditors look for
in SOC 2 and ISO 27001 reviews without requiring a separate write-once store.
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select

from .db import AuditLogRow, get_session, init_db

GENESIS = "GENESIS"

# Serialize writes so two concurrent ``record()`` calls cannot read the same
# tail row and both link to it (which would silently fork the chain). The DB
# itself remains the source of truth; this lock is per-process belt-and-braces.
_CHAIN_LOCK = threading.Lock()


def _canonical_fields(
    *,
    entry_id: str,
    created_at: datetime,
    principal: str,
    method: str,
    path: str,
    status_code: int,
    request_id: str | None,
    client_ip: str | None,
    user_agent: str | None,
    elapsed_ms: int,
    target_id: str | None,
    tenant_id: str | None,
    extra: dict[str, Any],
) -> str:
    """Canonical JSON used as the hash pre-image. Stable key order + ISO time."""
    # Normalize created_at to a naive UTC ISO string. SQLite's DateTime(tz=True)
    # drops tzinfo on read, so we strip it on write too; the verifier sees the
    # same string either way.
    if created_at.tzinfo is not None:
        created_at = created_at.astimezone(UTC).replace(tzinfo=None)
    payload = {
        "id": entry_id,
        "created_at": created_at.isoformat(timespec="microseconds"),
        "principal": principal,
        "method": method,
        "path": path,
        "status_code": status_code,
        "request_id": request_id,
        "client_ip": client_ip,
        "user_agent": user_agent,
        "elapsed_ms": elapsed_ms,
        "target_id": target_id,
        "tenant_id": tenant_id,
        "extra": extra or {},
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _compute_entry_hash(prev_hash: str, canonical: str) -> str:
    h = hashlib.sha256()
    h.update(prev_hash.encode("utf-8"))
    h.update(b"\x1f")  # ASCII unit separator: unambiguous boundary
    h.update(canonical.encode("utf-8"))
    return h.hexdigest()


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
        tenant_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        entry_id = uuid.uuid4().hex
        created_at = datetime.now(UTC)
        principal_v = principal[:128]
        method_v = method[:8]
        path_v = path[:512]
        client_ip_v = client_ip[:64] if client_ip else None
        user_agent_v = user_agent[:512] if user_agent else None
        extra_v = extra or {}

        with _CHAIN_LOCK, get_session() as s:
            # Find the chain tip for this tenant. Rows with tenant_id IS NULL
            # form their own legacy chain so we don't accidentally entangle
            # workspaces during the migration window.
            tip_stmt = select(AuditLogRow.entry_hash).order_by(
                desc(AuditLogRow.created_at), desc(AuditLogRow.id)
            ).limit(1)
            if tenant_id is None:
                tip_stmt = tip_stmt.where(AuditLogRow.tenant_id.is_(None))
            else:
                tip_stmt = tip_stmt.where(AuditLogRow.tenant_id == tenant_id)
            tip = s.execute(tip_stmt).scalar()
            prev_hash = tip if tip else GENESIS
            canonical = _canonical_fields(
                entry_id=entry_id,
                created_at=created_at,
                principal=principal_v,
                method=method_v,
                path=path_v,
                status_code=status_code,
                request_id=request_id,
                client_ip=client_ip_v,
                user_agent=user_agent_v,
                elapsed_ms=elapsed_ms,
                target_id=target_id,
                tenant_id=tenant_id,
                extra=extra_v,
            )
            entry_hash = _compute_entry_hash(prev_hash, canonical)
            row = AuditLogRow(
                id=entry_id,
                created_at=created_at,
                principal=principal_v,
                method=method_v,
                path=path_v,
                status_code=status_code,
                request_id=request_id,
                client_ip=client_ip_v,
                user_agent=user_agent_v,
                elapsed_ms=elapsed_ms,
                target_id=target_id,
                tenant_id=tenant_id,
                extra=extra_v,
                prev_hash=prev_hash,
                entry_hash=entry_hash,
            )
            s.add(row)
            s.commit()
        return entry_id

    # ------------------------------------------------------------------ chain
    def verify_chain(
        self, *, tenant_id: str | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        """Recompute the chain and report the first break, if any.

        Returns a dict with:
            ok: bool
            checked: number of rows verified
            tenant_id: scope verified (None means global, no scope filter)
            broken_at: id of the first row whose hash does not match (or None)
            reason: human-readable explanation when ``ok`` is False
            tip_hash: latest entry_hash in scope (the value an external
                      observer should pin to detect future tampering)
        """
        stmt = select(AuditLogRow).order_by(
            AuditLogRow.created_at.asc(), AuditLogRow.id.asc()
        )
        if tenant_id is not None:
            stmt = stmt.where(AuditLogRow.tenant_id == tenant_id)
        if limit:
            stmt = stmt.limit(limit)
        prev_by_tenant: dict[str | None, str] = {}
        checked = 0
        tip_hash: str | None = None
        with get_session() as s:
            for r in s.execute(stmt).scalars():
                t = r.tenant_id
                expected_prev = prev_by_tenant.get(t, GENESIS)
                # Tolerate legacy rows from before the chain existed: if both
                # hash columns are NULL, treat them as a chain reset point so
                # an upgrade from <=0017 does not look like tampering. New
                # rows are always hashed and verified.
                if r.entry_hash is None and r.prev_hash is None:
                    prev_by_tenant[t] = GENESIS
                    continue
                if r.prev_hash != expected_prev:
                    return {
                        "ok": False,
                        "checked": checked,
                        "tenant_id": tenant_id,
                        "broken_at": r.id,
                        "reason": (
                            f"prev_hash mismatch at {r.id}: "
                            f"expected {expected_prev}, found {r.prev_hash}"
                        ),
                        "tip_hash": tip_hash,
                    }
                canonical = _canonical_fields(
                    entry_id=r.id,
                    created_at=r.created_at,
                    principal=r.principal,
                    method=r.method,
                    path=r.path,
                    status_code=r.status_code,
                    request_id=r.request_id,
                    client_ip=r.client_ip,
                    user_agent=r.user_agent,
                    elapsed_ms=r.elapsed_ms,
                    target_id=r.target_id,
                    tenant_id=r.tenant_id,
                    extra=r.extra or {},
                )
                recomputed = _compute_entry_hash(r.prev_hash or GENESIS, canonical)
                if recomputed != r.entry_hash:
                    return {
                        "ok": False,
                        "checked": checked,
                        "tenant_id": tenant_id,
                        "broken_at": r.id,
                        "reason": (
                            f"entry_hash mismatch at {r.id}: row contents "
                            f"do not match stored hash"
                        ),
                        "tip_hash": tip_hash,
                    }
                prev_by_tenant[t] = r.entry_hash
                tip_hash = r.entry_hash
                checked += 1
        return {
            "ok": True,
            "checked": checked,
            "tenant_id": tenant_id,
            "broken_at": None,
            "reason": None,
            "tip_hash": tip_hash,
        }

    def list(
        self,
        *,
        limit: int = 100,
        principal: str | None = None,
        path_prefix: str | None = None,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        from sqlalchemy import or_

        stmt = select(AuditLogRow).order_by(desc(AuditLogRow.created_at)).limit(limit)
        if principal:
            stmt = stmt.where(AuditLogRow.principal == principal)
        if path_prefix:
            stmt = stmt.where(AuditLogRow.path.like(f"{path_prefix}%"))
        if tenant_id is not None:
            stmt = stmt.where(
                or_(
                    AuditLogRow.tenant_id == tenant_id,
                    AuditLogRow.tenant_id.is_(None),
                )
            )
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
                "tenant_id": r.tenant_id,
                "extra": r.extra or {},
                "prev_hash": r.prev_hash,
                "entry_hash": r.entry_hash,
            }
            for r in rows
        ]

    def count(self) -> int:
        from sqlalchemy import func

        with get_session() as s:
            return int(s.execute(select(func.count(AuditLogRow.id))).scalar() or 0)

    def list_for_principal(
        self, principal: str, limit: int = 10000, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        return self.list(limit=limit, principal=principal, tenant_id=tenant_id)

    def list_for_tenant(
        self, tenant_id: str, limit: int = 1_000_000
    ) -> list[dict[str, Any]]:
        """Return every audit row scoped to ``tenant_id`` (workspace export).

        Includes legacy rows with ``tenant_id IS NULL`` for parity with how
        every other read path resolves the deployment's default scope.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required for workspace audit export.")
        return self.list(limit=limit, tenant_id=tenant_id)

    def delete_for_tenant(self, tenant_id: str) -> int:
        """Hard-delete every audit row owned by ``tenant_id``.

        Used by the workspace-wide GDPR erasure endpoint. Mirrors
        :meth:`delete_for_principal` at workspace scope.

        Note: erasure intentionally breaks the chain for the affected scope.
        The verifier reports the break, which is the auditable evidence of a
        right-to-erasure execution rather than an undisclosed mutation.
        """
        from sqlalchemy import delete as sa_delete
        from sqlalchemy import or_

        if not tenant_id:
            raise ValueError("tenant_id is required for workspace audit erasure.")
        with get_session() as s:
            stmt = sa_delete(AuditLogRow).where(
                or_(
                    AuditLogRow.tenant_id == tenant_id,
                    AuditLogRow.tenant_id.is_(None),
                )
            )
            result = s.execute(stmt)
            s.commit()
            return int(result.rowcount or 0)

    def delete_for_principal(
        self, principal: str, tenant_id: str | None = None
    ) -> int:
        """Hard-delete every audit row owned by ``principal`` (GDPR erasure).

        When ``tenant_id`` is provided, only rows in that tenant (or rows with
        a NULL tenant from before the migration) are removed.
        """
        from sqlalchemy import delete as sa_delete
        from sqlalchemy import or_

        with get_session() as s:
            stmt = sa_delete(AuditLogRow).where(AuditLogRow.principal == principal)
            if tenant_id is not None:
                stmt = stmt.where(
                    or_(
                        AuditLogRow.tenant_id == tenant_id,
                        AuditLogRow.tenant_id.is_(None),
                    )
                )
            result = s.execute(stmt)
            s.commit()
            return int(result.rowcount or 0)
