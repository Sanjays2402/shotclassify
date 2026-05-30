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
from sqlalchemy import or_, select

from .db import ClassificationRow, get_session, init_db


class Repository:
    def __init__(self) -> None:
        init_db()

    def save_result(
        self,
        result: ProcessResult,
        image_path: str | None = None,
        principal: str | None = None,
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
        )
        with get_session() as s:
            s.merge(row)
            s.commit()

    def list_by_principal(self, principal: str) -> list[ClassificationRecord]:
        stmt = (
            select(ClassificationRow)
            .where(ClassificationRow.principal == principal)
            .order_by(ClassificationRow.created_at.desc())
        )
        with get_session() as s:
            rows = list(s.execute(stmt).scalars())
        return [self._to_record(r) for r in rows]

    def delete_by_principal(self, principal: str) -> int:
        """Hard-delete all classifications owned by a principal.

        Returns the number of rows removed. Also unlinks the associated blob
        files when they live under the configured local storage dir.
        """
        from pathlib import Path

        from shotclassify_common import get_settings

        storage_root = Path(get_settings().storage_local_dir).resolve()
        with get_session() as s:
            rows = list(
                s.execute(
                    select(ClassificationRow).where(
                        ClassificationRow.principal == principal
                    )
                ).scalars()
            )
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

    def list(
        self,
        limit: int = 50,
        category: Category | None = None,
        query: str | None = None,
    ) -> list[ClassificationRecord]:
        stmt = select(ClassificationRow).order_by(ClassificationRow.created_at.desc())
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
        stmt = stmt.limit(limit)
        with get_session() as s:
            rows = list(s.execute(stmt).scalars())
        return [self._to_record(r) for r in rows]

    def get(self, item_id: str) -> ClassificationRecord | None:
        with get_session() as s:
            row = s.get(ClassificationRow, item_id)
        return self._to_record(row) if row else None

    def correct(self, item_id: str, new_category: Category) -> ClassificationRecord | None:
        with get_session() as s:
            row = s.get(ClassificationRow, item_id)
            if not row:
                return None
            row.user_corrected_to = new_category.value
            s.commit()
        return self.get(item_id)

    def delete(self, item_id: str) -> bool:
        with get_session() as s:
            row = s.get(ClassificationRow, item_id)
            if not row:
                return False
            s.delete(row)
            s.commit()
        return True

    def count(self) -> int:
        with get_session() as s:
            return s.query(ClassificationRow).count()

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
        )
