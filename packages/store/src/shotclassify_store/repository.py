"""Repository for classification history."""
from __future__ import annotations

from datetime import datetime

from shotclassify_common import (
    Category,
    ClassificationRecord,
    ExtractedFields,
    ProcessResult,
    RouteDecision,
)
from sqlalchemy import Text, func, or_, select

from .db import ClassificationRow, get_session, init_db


class Repository:
    def __init__(self) -> None:
        init_db()

    def save_result(
        self,
        result: ProcessResult,
        image_path: str | None = None,
        principal: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        row = ClassificationRow(
            id=result.id,
            filename=result.filename,
            image_path=image_path,
            created_at=result.created_at,
            primary_category=result.classification.primary.value,
            confidence=result.classification.confidence_of(result.classification.primary),
            ocr_text=result.ocr.text,
            ocr_lang=result.ocr.language,
            extracted=result.extracted.model_dump(mode="json"),
            route=result.route.model_dump(mode="json"),
            elapsed_ms=result.elapsed_ms,
            principal=principal,
            tenant_id=tenant_id,
        )
        with get_session() as s:
            s.merge(row)
            s.commit()

    @staticmethod
    def _scope_tenant(stmt, tenant_id: str | None):
        """Apply a tenant filter unless ``tenant_id`` is ``None`` (admin cross-tenant).

        Rows written before the multi-tenancy migration have ``tenant_id IS
        NULL`` and are treated as belonging to whatever the caller's tenant
        is, so that the upgrade is non-destructive for solo deployments.
        """
        if tenant_id is None:
            return stmt
        return stmt.where(
            or_(
                ClassificationRow.tenant_id == tenant_id,
                ClassificationRow.tenant_id.is_(None),
            )
        )

    def count_by_principal_since(
        self,
        principal: str,
        since: datetime,
        tenant_id: str | None = None,
    ) -> int:
        """Count classifications owned by ``principal`` created at or after ``since``.

        Used by the usage/quota endpoint to compute current-period usage.
        """
        stmt = select(func.count(ClassificationRow.id)).where(
            ClassificationRow.principal == principal,
            ClassificationRow.created_at >= since,
        )
        stmt = self._scope_tenant(stmt, tenant_id)
        with get_session() as s:
            return int(s.execute(stmt).scalar() or 0)

    def list_by_principal(
        self, principal: str, tenant_id: str | None = None
    ) -> list[ClassificationRecord]:
        stmt = (
            select(ClassificationRow)
            .where(ClassificationRow.principal == principal)
            .order_by(ClassificationRow.created_at.desc())
        )
        stmt = self._scope_tenant(stmt, tenant_id)
        with get_session() as s:
            rows = list(s.execute(stmt).scalars())
        return [self._to_record(r) for r in rows]

    def delete_by_principal(
        self, principal: str, tenant_id: str | None = None
    ) -> int:
        """Hard-delete all classifications owned by a principal.

        Returns the number of rows removed. Also unlinks the associated blob
        files when they live under the configured local storage dir.

        Raises :class:`shotclassify_store.legal_holds.LegalHoldActive` if
        the resolved tenant has any active legal hold.
        """
        from pathlib import Path

        from shotclassify_common import get_settings

        from .legal_holds import guard_destructive

        guard_destructive(tenant_id)
        storage_root = Path(get_settings().storage_local_dir).resolve()
        with get_session() as s:
            stmt = select(ClassificationRow).where(
                ClassificationRow.principal == principal
            )
            stmt = self._scope_tenant(stmt, tenant_id)
            rows = list(s.execute(stmt).scalars())
            removed = 0
            for row in rows:
                if row.image_path:
                    try:
                        p = Path(row.image_path).resolve()
                        # Only unlink files inside the configured storage root
                        # to avoid traversal-induced deletes.
                        if str(p).startswith(str(storage_root)) and p.exists():
                            p.unlink()
                    except OSError:
                        pass
                s.delete(row)
                removed += 1
            s.commit()
        return removed

    def list_by_tenant(self, tenant_id: str) -> list[ClassificationRecord]:
        """Return every classification row that belongs to ``tenant_id``.

        Rows with a NULL ``tenant_id`` (pre-multi-tenancy) are also returned
        when the caller's tenant matches the deployment's default scope; we
        rely on ``_scope_tenant`` for that behavior to stay consistent with
        every read path.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required for tenant-wide export.")
        stmt = select(ClassificationRow).order_by(ClassificationRow.created_at.desc())
        stmt = self._scope_tenant(stmt, tenant_id)
        with get_session() as s:
            rows = list(s.execute(stmt).scalars())
        return [self._to_record(r) for r in rows]

    def delete_by_tenant(self, tenant_id: str) -> int:
        """Hard-delete every classification row owned by ``tenant_id``.

        Mirrors :meth:`delete_by_principal` but at workspace scope: used by
        the workspace-wide GDPR erasure endpoint. Also unlinks blob files
        inside the configured local storage root. Returns the row count.

        Raises :class:`shotclassify_store.legal_holds.LegalHoldActive` if
        the workspace has any active legal hold.
        """
        from pathlib import Path

        from shotclassify_common import get_settings

        from .legal_holds import guard_destructive

        if not tenant_id:
            raise ValueError("tenant_id is required for tenant-wide deletion.")
        guard_destructive(tenant_id)
        storage_root = Path(get_settings().storage_local_dir).resolve()
        with get_session() as s:
            stmt = select(ClassificationRow)
            stmt = self._scope_tenant(stmt, tenant_id)
            rows = list(s.execute(stmt).scalars())
            removed = 0
            for row in rows:
                if row.image_path:
                    try:
                        p = Path(row.image_path).resolve()
                        if str(p).startswith(str(storage_root)) and p.exists():
                            p.unlink()
                    except OSError:
                        pass
                s.delete(row)
                removed += 1
            s.commit()
        return removed

    def _list_stmt(
        self,
        category: Category | None = None,
        query: str | None = None,
        tenant_id: str | None = None,
        since: "datetime | None" = None,
        until: "datetime | None" = None,
        min_conf: float | None = None,
        max_conf: float | None = None,
        sort: str = "new",
        tag: str | None = None,
        pinned: bool | None = None,
    ):
        from sqlalchemy import asc, desc

        col_map = {
            "new": (ClassificationRow.created_at, desc),
            "old": (ClassificationRow.created_at, asc),
            "conf_desc": (ClassificationRow.confidence, desc),
            "conf_asc": (ClassificationRow.confidence, asc),
        }
        col, direction = col_map.get(sort, (ClassificationRow.created_at, desc))
        stmt = select(ClassificationRow).order_by(direction(col), ClassificationRow.id.desc())
        if category is not None:
            stmt = stmt.where(ClassificationRow.primary_category == category.value)
        if query:
            like = f"%{query.lower()}%"
            stmt = stmt.where(
                or_(
                    ClassificationRow.ocr_text.ilike(like),
                    ClassificationRow.filename.ilike(like),
                )
            )
        if since is not None:
            stmt = stmt.where(ClassificationRow.created_at >= since)
        if until is not None:
            stmt = stmt.where(ClassificationRow.created_at <= until)
        if min_conf is not None:
            stmt = stmt.where(ClassificationRow.confidence >= float(min_conf))
        if max_conf is not None:
            stmt = stmt.where(ClassificationRow.confidence <= float(max_conf))
        if tag:
            # JSON tag-membership match. SQLite stores JSON as text, so we
            # fall back to a substring LIKE on a quoted token, which is
            # adequate for the small, normalized tag vocabulary we write.
            needle = f'%"{tag.strip().lower()}"%'
            stmt = stmt.where(ClassificationRow.tags.cast(Text).ilike(needle))
        if pinned is not None:
            stmt = stmt.where(ClassificationRow.pinned == bool(pinned))
        stmt = self._scope_tenant(stmt, tenant_id)
        return stmt

    def list(
        self,
        limit: int = 50,
        category: Category | None = None,
        query: str | None = None,
        tenant_id: str | None = None,
        offset: int = 0,
        since: "datetime | None" = None,
        until: "datetime | None" = None,
        min_conf: float | None = None,
        max_conf: float | None = None,
        sort: str = "new",
        tag: str | None = None,
        pinned: bool | None = None,
    ) -> list[ClassificationRecord]:
        stmt = self._list_stmt(
            category=category,
            query=query,
            tenant_id=tenant_id,
            since=since,
            until=until,
            min_conf=min_conf,
            max_conf=max_conf,
            sort=sort,
            tag=tag,
            pinned=pinned,
        )
        if offset:
            stmt = stmt.offset(int(offset))
        stmt = stmt.limit(limit)
        with get_session() as s:
            rows = list(s.execute(stmt).scalars())
        return [self._to_record(r) for r in rows]

    def count_filtered(
        self,
        category: Category | None = None,
        query: str | None = None,
        tenant_id: str | None = None,
        since: "datetime | None" = None,
        until: "datetime | None" = None,
        min_conf: float | None = None,
        max_conf: float | None = None,
        tag: str | None = None,
        pinned: bool | None = None,
    ) -> int:
        from sqlalchemy import func

        stmt = self._list_stmt(
            category=category,
            query=query,
            tenant_id=tenant_id,
            since=since,
            until=until,
            min_conf=min_conf,
            max_conf=max_conf,
            tag=tag,
            pinned=pinned,
        ).order_by(None).with_only_columns(func.count(ClassificationRow.id))
        with get_session() as s:
            return int(s.execute(stmt).scalar() or 0)

    def get(
        self, item_id: str, tenant_id: str | None = None
    ) -> ClassificationRecord | None:
        with get_session() as s:
            row = s.get(ClassificationRow, item_id)
        if row is None:
            return None
        if tenant_id is not None and row.tenant_id not in (None, tenant_id):
            return None
        return self._to_record(row)

    def update_meta(
        self,
        item_id: str,
        label: str | None = None,
        tags: list[str] | None = None,
        tenant_id: str | None = None,
        clear_label: bool = False,
        pinned: bool | None = None,
    ) -> ClassificationRecord | None:
        """Update the user-editable label and/or tags on a single record.

        Passing ``clear_label=True`` removes the label. ``tags`` replaces the
        full list when provided (use an empty list to clear). The repository
        normalizes tag strings (trim, lowercase, dedupe, cap at 16 entries
        and 32 chars each) before writing.
        """
        with get_session() as s:
            row = s.get(ClassificationRow, item_id)
            if not row:
                return None
            if tenant_id is not None and row.tenant_id not in (None, tenant_id):
                return None
            if clear_label:
                row.label = None
            elif label is not None:
                cleaned = label.strip()
                row.label = cleaned[:256] if cleaned else None
            if tags is not None:
                seen: set[str] = set()
                cleaned_tags: list[str] = []
                for t in tags:
                    if not isinstance(t, str):
                        continue
                    norm = t.strip().lower()[:32]
                    if not norm or norm in seen:
                        continue
                    seen.add(norm)
                    cleaned_tags.append(norm)
                    if len(cleaned_tags) >= 16:
                        break
                row.tags = cleaned_tags
            if pinned is not None:
                row.pinned = bool(pinned)
            s.commit()
        return self.get(item_id, tenant_id=tenant_id)

    def correct(
        self,
        item_id: str,
        new_category: Category,
        tenant_id: str | None = None,
    ) -> ClassificationRecord | None:
        with get_session() as s:
            row = s.get(ClassificationRow, item_id)
            if not row:
                return None
            if tenant_id is not None and row.tenant_id not in (None, tenant_id):
                return None
            row.user_corrected_to = new_category.value
            s.commit()
        return self.get(item_id, tenant_id=tenant_id)

    def delete(self, item_id: str, tenant_id: str | None = None) -> bool:
        from .legal_holds import guard_destructive

        guard_destructive(tenant_id)
        with get_session() as s:
            row = s.get(ClassificationRow, item_id)
            if not row:
                return False
            if tenant_id is not None and row.tenant_id not in (None, tenant_id):
                return False
            s.delete(row)
            s.commit()
        return True

    def aggregate(
        self,
        tenant_id: str | None = None,
        hours: int = 24,
    ) -> dict:
        """Return rich rollups for the analytics dashboard.

        Computes per-category counts, mean confidence per class,
        latency percentiles (p50/p95/p99), a 24-bin hourly volume
        histogram, and a correction count. All numbers are derived
        from real rows scoped to ``tenant_id``.
        """
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        stmt = select(ClassificationRow)
        stmt = self._scope_tenant(stmt, tenant_id)
        with get_session() as s:
            rows = list(s.execute(stmt).scalars())

        total = len(rows)
        cat_counts: dict[str, int] = {}
        cat_conf_sum: dict[str, float] = {}
        latencies: list[int] = []
        confidences: list[float] = []
        corrections = 0
        hourly: dict[str, int] = {}
        recent_rows = []
        for r in rows:
            cat_counts[r.primary_category] = cat_counts.get(r.primary_category, 0) + 1
            cat_conf_sum[r.primary_category] = (
                cat_conf_sum.get(r.primary_category, 0.0) + float(r.confidence or 0.0)
            )
            confidences.append(float(r.confidence or 0.0))
            if r.user_corrected_to:
                corrections += 1
            created = r.created_at
            if isinstance(created, str):
                try:
                    created = datetime.fromisoformat(created)
                except ValueError:
                    created = None
            if created is not None:
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created >= cutoff:
                    recent_rows.append(r)
                    bucket = created.replace(minute=0, second=0, microsecond=0)
                    key = bucket.isoformat()
                    hourly[key] = hourly.get(key, 0) + 1
                    if r.elapsed_ms:
                        latencies.append(int(r.elapsed_ms))

        def _pct(arr: list[int], q: float) -> int:
            if not arr:
                return 0
            s2 = sorted(arr)
            idx = max(0, min(len(s2) - 1, int(round(q * (len(s2) - 1)))))
            return s2[idx]

        # Confidence histogram (10 bins, 0..1) across all rows
        conf_bins = [0] * 10
        for c in confidences:
            b = min(9, max(0, int(c * 10)))
            conf_bins[b] += 1

        per_class = [
            {
                "category": cat,
                "count": cnt,
                "mean_confidence": round(cat_conf_sum[cat] / cnt, 4) if cnt else 0.0,
            }
            for cat, cnt in sorted(cat_counts.items(), key=lambda kv: kv[1], reverse=True)
        ]

        hourly_series = [
            {"hour": k, "count": v}
            for k, v in sorted(hourly.items())
        ]

        return {
            "total": total,
            "window_hours": hours,
            "window_count": len(recent_rows),
            "corrections": corrections,
            "correction_rate": round(corrections / total, 4) if total else 0.0,
            "mean_confidence": round(sum(confidences) / total, 4) if total else 0.0,
            "latency_ms": {
                "p50": _pct(latencies, 0.50),
                "p95": _pct(latencies, 0.95),
                "p99": _pct(latencies, 0.99),
                "count": len(latencies),
            },
            "per_class": per_class,
            "confidence_histogram": [
                {"bin": i, "lo": round(i / 10, 1), "hi": round((i + 1) / 10, 1), "count": n}
                for i, n in enumerate(conf_bins)
            ],
            "hourly": hourly_series,
        }

    def count(self, tenant_id: str | None = None) -> int:
        with get_session() as s:
            q = s.query(ClassificationRow)
            if tenant_id is not None:
                from sqlalchemy import or_ as _or
                q = q.filter(
                    _or(
                        ClassificationRow.tenant_id == tenant_id,
                        ClassificationRow.tenant_id.is_(None),
                    )
                )
            return q.count()

    def _to_record(self, row: ClassificationRow) -> ClassificationRecord:
        created_at = row.created_at
        if isinstance(created_at, str):  # sqlite returns str sometimes
            created_at = datetime.fromisoformat(created_at)
        return ClassificationRecord(
            id=row.id,
            filename=row.filename,
            created_at=created_at,
            primary_category=Category(row.primary_category),
            confidence=row.confidence,
            ocr_text=row.ocr_text,
            extracted=ExtractedFields.model_validate(row.extracted or {}),
            route=RouteDecision.model_validate(row.route or {"action": "none"}),
            image_path=row.image_path,
            user_corrected_to=Category(row.user_corrected_to) if row.user_corrected_to else None,
            label=row.label,
            tags=list(row.tags or []),
            pinned=bool(getattr(row, "pinned", False) or False),
        )
