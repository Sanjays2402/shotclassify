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

    def count_by_principal_grouped(
        self,
        tenant_id: str,
        since: datetime | None = None,
    ) -> list[dict]:
        """Per-principal classification counts and last-activity timestamps.

        Returned rows are dicts with ``principal``, ``count``, and
        ``last_at`` (ISO 8601 str or None). Strictly tenant-scoped: callers
        must supply ``tenant_id`` so this can never be used to enumerate
        rows across tenants. Used by the seat-usage admin endpoint to
        render per-seat billing/usage breakdowns.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required for per-principal usage.")
        stmt = (
            select(
                ClassificationRow.principal,
                func.count(ClassificationRow.id).label("n"),
                func.max(ClassificationRow.created_at).label("last_at"),
            )
            .where(ClassificationRow.principal.is_not(None))
            .group_by(ClassificationRow.principal)
        )
        stmt = self._scope_tenant(stmt, tenant_id)
        if since is not None:
            stmt = stmt.where(ClassificationRow.created_at >= since)
        out: list[dict] = []
        with get_session() as s:
            for principal, n, last_at in s.execute(stmt).all():
                if isinstance(last_at, str):
                    try:
                        last_at = datetime.fromisoformat(last_at)
                    except ValueError:
                        last_at = None
                out.append(
                    {
                        "principal": principal,
                        "count": int(n or 0),
                        "last_at": last_at.isoformat() if last_at else None,
                    }
                )
        return out

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
        tags: list[str] | None = None,
        untagged: bool | None = None,
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
        # JSON tag-membership match. SQLite stores JSON as text, so we
        # fall back to a substring LIKE on a quoted token, which is
        # adequate for the small, normalized tag vocabulary we write.
        # `tag` is the legacy single-tag filter; `tags` is the multi-tag
        # AND filter (every tag must be present on the record).
        tag_terms: list[str] = []
        if tag:
            tag_terms.append(tag.strip().lower())
        if tags:
            for t in tags:
                if not isinstance(t, str):
                    continue
                norm = t.strip().lower()
                if norm and norm not in tag_terms:
                    tag_terms.append(norm)
        for term in tag_terms:
            needle = f'%"{term}"%'
            stmt = stmt.where(ClassificationRow.tags.cast(Text).ilike(needle))
        if pinned is not None:
            stmt = stmt.where(ClassificationRow.pinned == bool(pinned))
        # `untagged=true` returns rows with no tags (NULL or empty list);
        # `untagged=false` returns rows with at least one tag. Backs an
        # "unlabeled queue" UI for triage. Stored as JSON, so an empty
        # list serializes to the literal text "[]".
        if untagged is not None:
            tags_text = ClassificationRow.tags.cast(Text)
            # SQLAlchemy's JSON type serializes Python None to the JSON
            # literal "null" rather than SQL NULL, so check both the
            # text payload and the column being SQL NULL to be safe
            # across SQLite, Postgres, and rows written before the JSON
            # type defaulting changed.
            empty_payload = tags_text.in_(("null", "[]"))
            if untagged:
                stmt = stmt.where(
                    or_(
                        ClassificationRow.tags.is_(None),
                        empty_payload,
                    )
                )
            else:
                stmt = stmt.where(ClassificationRow.tags.is_not(None))
                stmt = stmt.where(~empty_payload)
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
        tags: list[str] | None = None,
        untagged: bool | None = None,
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
            tags=tags,
            untagged=untagged,
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
        tags: list[str] | None = None,
        untagged: bool | None = None,
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
            tags=tags,
            untagged=untagged,
        ).order_by(None).with_only_columns(func.count(ClassificationRow.id))
        with get_session() as s:
            return int(s.execute(stmt).scalar() or 0)

    def list_tags(
        self,
        tenant_id: str | None = None,
        q: str | None = None,
        limit: int = 100,
        min_count: int = 1,
        sort: str = "count",
        order: str | None = None,
    ) -> list[dict]:
        """Return distinct tags in scope with their usage counts.

        Powers tag autocomplete and tag-cloud UIs so users discover the
        vocabulary that is already in use instead of guessing. Each item
        is ``{"tag": str, "count": int}``, sorted by count desc then tag
        asc. ``q`` filters tags by case-insensitive substring. ``limit``
        is clamped to ``[1, 500]``. Tags are stored as a small JSON list
        per row, so we aggregate in Python after a tenant-scoped scan,
        which is fine for the small vocabularies this product targets.
        """
        capped = max(1, min(int(limit), 500))
        floor = max(1, int(min_count))
        needle = (q or "").strip().lower()
        stmt = select(ClassificationRow.tags)
        stmt = self._scope_tenant(stmt, tenant_id)
        counts: dict[str, int] = {}
        with get_session() as s:
            for (raw,) in s.execute(stmt):
                if not raw:
                    continue
                for t in raw:
                    if not isinstance(t, str):
                        continue
                    norm = t.strip().lower()
                    if not norm:
                        continue
                    if needle and needle not in norm:
                        continue
                    counts[norm] = counts.get(norm, 0) + 1
        if floor > 1:
            counts = {t: c for t, c in counts.items() if c >= floor}
        sort_key = (sort or "count").strip().lower()
        if sort_key not in {"count", "name"}:
            raise ValueError("`sort` must be 'count' or 'name'.")
        if order is None:
            ord_key = "asc" if sort_key == "name" else "desc"
        else:
            ord_key = order.strip().lower()
        if ord_key not in {"asc", "desc"}:
            raise ValueError("`order` must be 'asc' or 'desc'.")
        reverse = ord_key == "desc"
        if sort_key == "count":
            # Stable alphabetical tie-break: tag asc regardless of order.
            if reverse:
                items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            else:
                items = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]))
        else:
            items = sorted(counts.items(), key=lambda kv: kv[0], reverse=reverse)
        return [{"tag": t, "count": c} for t, c in items[:capped]]

    def tag_detail(
        self,
        tag: str,
        tenant_id: str | None = None,
    ) -> dict:
        """Return usage summary for a single tag in the tenant scope.

        Backs a tag detail page (``GET /v1/history/tags/{tag}``) so the UI
        can show "used N times, first on X, last on Y" before the user
        decides to rename, merge or delete the tag. ``first_seen`` and
        ``last_seen`` are ISO 8601 UTC strings, or ``None`` if the tag is
        not present in the scope. The tag is normalized the same way as
        write-time (trim, lowercase, 32 char cap).
        """
        norm = (tag or "").strip().lower()[:32]
        if not norm:
            raise ValueError("`tag` must be a non-empty tag name.")
        stmt = select(ClassificationRow.tags, ClassificationRow.created_at)
        stmt = self._scope_tenant(stmt, tenant_id)
        count = 0
        first_seen: datetime | None = None
        last_seen: datetime | None = None
        with get_session() as s:
            for raw, created in s.execute(stmt):
                if not isinstance(raw, list):
                    continue
                hit = False
                for t in raw:
                    if not isinstance(t, str):
                        continue
                    if t.strip().lower() == norm:
                        hit = True
                        break
                if not hit:
                    continue
                count += 1
                if created is None:
                    continue
                if first_seen is None or created < first_seen:
                    first_seen = created
                if last_seen is None or created > last_seen:
                    last_seen = created
        from datetime import timezone as _tz
        def _iso(dt: datetime | None) -> str | None:
            if dt is None:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_tz.utc)
            return dt.isoformat()
        return {
            "tag": norm,
            "count": count,
            "first_seen": _iso(first_seen),
            "last_seen": _iso(last_seen),
        }

    def tag_timeseries(
        self,
        tag: str,
        tenant_id: str | None = None,
        days: int = 30,
        until: "datetime | None" = None,
    ) -> dict:
        """Per-day usage counts for ``tag`` over a trailing window.

        Backs a sparkline on the tag detail page so an operator can see
        whether a tag is trending up, dying off, or steady before deciding
        to merge, rename, or retire it. Returns a dense series with one
        bucket per UTC day in the window (zero-filled), oldest first, so
        the caller does not have to fill gaps client-side.

        ``days`` is clamped to ``[1, 365]``. ``until`` defaults to "now"
        in UTC; the window is the ``days`` calendar days ending on that
        day inclusive. The tag is normalized the same way as on write
        (trim, lowercase, 32 char cap).

        Response shape::

            {
              "tag": "finance",
              "start": "2025-01-01",
              "end":   "2025-01-30",
              "days":  30,
              "total": 17,
              "series": [{"date": "2025-01-01", "count": 0}, ...]
            }
        """
        from datetime import date as _date, timedelta as _td, timezone as _tz

        norm = (tag or "").strip().lower()[:32]
        if not norm:
            raise ValueError("`tag` must be a non-empty tag name.")
        window = max(1, min(int(days), 365))
        if until is None:
            end_day = datetime.now(_tz.utc).date()
        else:
            u = until if until.tzinfo is not None else until.replace(tzinfo=_tz.utc)
            end_day = u.astimezone(_tz.utc).date()
        start_day = end_day - _td(days=window - 1)
        start_dt = datetime.combine(start_day, datetime.min.time(), tzinfo=_tz.utc)
        end_dt = datetime.combine(end_day, datetime.max.time(), tzinfo=_tz.utc)

        stmt = select(ClassificationRow.tags, ClassificationRow.created_at).where(
            ClassificationRow.created_at >= start_dt,
            ClassificationRow.created_at <= end_dt,
        )
        stmt = self._scope_tenant(stmt, tenant_id)
        buckets: dict[_date, int] = {}
        with get_session() as s:
            for raw, created in s.execute(stmt):
                if not isinstance(raw, list) or created is None:
                    continue
                hit = False
                for t in raw:
                    if isinstance(t, str) and t.strip().lower() == norm:
                        hit = True
                        break
                if not hit:
                    continue
                c = created if created.tzinfo is not None else created.replace(tzinfo=_tz.utc)
                day = c.astimezone(_tz.utc).date()
                buckets[day] = buckets.get(day, 0) + 1
        series = []
        total = 0
        for i in range(window):
            d = start_day + _td(days=i)
            n = int(buckets.get(d, 0))
            total += n
            series.append({"date": d.isoformat(), "count": n})
        return {
            "tag": norm,
            "start": start_day.isoformat(),
            "end": end_day.isoformat(),
            "days": window,
            "total": total,
            "series": series,
        }

    def related_tags(
        self,
        tag: str,
        tenant_id: str | None = None,
        limit: int = 50,
        min_count: int = 1,
    ) -> dict:
        """Return tags that most often co-occur with ``tag`` in the tenant scope.

        Powers a "related tags" sidebar on the tag detail UI and surfaces
        merge candidates (typos, near-duplicates) when cleaning up a tag
        taxonomy. The seed tag itself is excluded from the result. Each
        item is ``{"tag": str, "count": int}`` where ``count`` is the
        number of rows that carry both the seed tag and the related tag.
        Sorted by count desc then tag asc. ``limit`` is clamped to
        ``[1, 500]``. ``base_count`` reports how many rows carry the seed
        tag at all, so the UI can show "X of N rows" without a second call.
        """
        norm = (tag or "").strip().lower()[:32]
        if not norm:
            raise ValueError("`tag` must be a non-empty tag name.")
        capped = max(1, min(int(limit), 500))
        floor = max(1, int(min_count))
        stmt = select(ClassificationRow.tags)
        stmt = self._scope_tenant(stmt, tenant_id)
        base = 0
        counts: dict[str, int] = {}
        with get_session() as s:
            for (raw,) in s.execute(stmt):
                if not isinstance(raw, list):
                    continue
                normed: set[str] = set()
                for t in raw:
                    if not isinstance(t, str):
                        continue
                    n = t.strip().lower()
                    if n:
                        normed.add(n)
                if norm not in normed:
                    continue
                base += 1
                for n in normed:
                    if n == norm:
                        continue
                    counts[n] = counts.get(n, 0) + 1
        if floor > 1:
            counts = {t: c for t, c in counts.items() if c >= floor}
        items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return {
            "tag": norm,
            "base_count": base,
            "items": [{"tag": t, "count": c} for t, c in items[:capped]],
        }

    def rename_tag(
        self,
        old: str,
        new: str,
        tenant_id: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Rename a tag across every classification in the tenant scope.

        Fixes typos and consolidates near-duplicates (``finace`` -> ``finance``)
        in one call instead of patching records one by one. Both names are
        normalized the same way as on write (trim, lowercase, 32 char cap).
        If a row already has both the old and new tag, the old one is dropped
        and the new one is kept once. Tag order is preserved otherwise.
        Returns ``{"updated": int, "old": str, "new": str}``. When
        ``dry_run=True`` no rows are written and ``updated`` reflects what
        would have changed.
        """
        old_norm = (old or "").strip().lower()[:32]
        new_norm = (new or "").strip().lower()[:32]
        if not old_norm or not new_norm:
            raise ValueError("`old` and `new` must be non-empty tag names.")
        if old_norm == new_norm:
            return {"updated": 0, "old": old_norm, "new": new_norm}
        stmt = select(ClassificationRow)
        stmt = self._scope_tenant(stmt, tenant_id)
        updated = 0
        with get_session() as s:
            for row in s.execute(stmt).scalars():
                tags = row.tags or []
                if not isinstance(tags, list) or old_norm not in tags:
                    continue
                seen: set[str] = set()
                new_tags: list[str] = []
                for t in tags:
                    if not isinstance(t, str):
                        continue
                    norm = t.strip().lower()[:32]
                    if norm == old_norm:
                        norm = new_norm
                    if not norm or norm in seen:
                        continue
                    seen.add(norm)
                    new_tags.append(norm)
                if new_tags == tags:
                    continue
                updated += 1
                if not dry_run:
                    row.tags = new_tags
            if not dry_run:
                s.commit()
        return {"updated": updated, "old": old_norm, "new": new_norm}

    def merge_tags(
        self,
        sources: list[str],
        target: str,
        tenant_id: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Merge several source tags into one target tag in a single pass.

        Useful for taxonomy cleanup where many near-duplicate tags collapse
        into one canonical name (e.g. ``["finace", "financ", "FIN"]`` ->
        ``"finance"``) without issuing one rename call per source. All names
        are normalized the same way as on write (trim, lowercase, 32 char cap).
        Duplicate sources, blanks, and any source equal to the target are
        ignored. If a row already has the target alongside one or more
        sources, the sources are dropped and the target is kept once. Tag
        order is preserved otherwise. Returns
        ``{"updated": int, "sources": list[str], "target": str}``. When
        ``dry_run=True`` no rows are written and ``updated`` reflects what
        would have changed.
        """
        target_norm = (target or "").strip().lower()[:32]
        if not target_norm:
            raise ValueError("`target` must be a non-empty tag name.")
        if not isinstance(sources, list) or not sources:
            raise ValueError("`sources` must be a non-empty list of tag names.")
        source_set: set[str] = set()
        for s_ in sources:
            if not isinstance(s_, str):
                raise ValueError("`sources` entries must be strings.")
            n = s_.strip().lower()[:32]
            if not n or n == target_norm:
                continue
            source_set.add(n)
        if not source_set:
            return {"updated": 0, "sources": [], "target": target_norm}
        sources_sorted = sorted(source_set)
        stmt = select(ClassificationRow)
        stmt = self._scope_tenant(stmt, tenant_id)
        updated = 0
        with get_session() as s:
            for row in s.execute(stmt).scalars():
                tags = row.tags or []
                if not isinstance(tags, list):
                    continue
                if not any(t in source_set for t in tags if isinstance(t, str)):
                    continue
                seen: set[str] = set()
                new_tags: list[str] = []
                for t in tags:
                    if not isinstance(t, str):
                        continue
                    norm = t.strip().lower()[:32]
                    if norm in source_set:
                        norm = target_norm
                    if not norm or norm in seen:
                        continue
                    seen.add(norm)
                    new_tags.append(norm)
                if new_tags == tags:
                    continue
                updated += 1
                if not dry_run:
                    row.tags = new_tags
            if not dry_run:
                s.commit()
        return {"updated": updated, "sources": sources_sorted, "target": target_norm}

    def delete_tag(
        self,
        tag: str,
        tenant_id: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Remove a tag from every classification in the tenant scope.

        Mirror of :meth:`rename_tag` for retiring an obsolete tag entirely.
        The tag name is normalized the same way as on write (trim, lowercase,
        32 char cap). Other tags on each row are preserved in their original
        order. Returns ``{"updated": int, "tag": str}``. When ``dry_run=True``
        no rows are written and ``updated`` reflects what would have changed.
        """
        norm = (tag or "").strip().lower()[:32]
        if not norm:
            raise ValueError("`tag` must be a non-empty tag name.")
        stmt = select(ClassificationRow)
        stmt = self._scope_tenant(stmt, tenant_id)
        updated = 0
        with get_session() as s:
            for row in s.execute(stmt).scalars():
                tags = row.tags or []
                if not isinstance(tags, list) or norm not in tags:
                    continue
                new_tags = [
                    t for t in tags
                    if isinstance(t, str) and t.strip().lower()[:32] != norm
                ]
                if new_tags == tags:
                    continue
                updated += 1
                if not dry_run:
                    row.tags = new_tags
            if not dry_run:
                s.commit()
        return {"updated": updated, "tag": norm}

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
