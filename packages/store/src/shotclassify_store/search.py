"""SQLite full-text search helper (FTS5 when available)."""
from __future__ import annotations

from sqlalchemy import text

from .db import get_engine


def ensure_fts() -> bool:
    eng = get_engine()
    if not str(eng.url).startswith("sqlite"):
        return False
    with eng.begin() as conn:
        try:
            conn.execute(
                text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS classifications_fts "
                    "USING fts5(id, ocr_text, primary_category)"
                )
            )
            return True
        except Exception:
            return False
