"""Tests for Repository.aggregate analytics rollups."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_aggregate_returns_real_rollups(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'agg.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db
    from shotclassify_store.db import ClassificationRow, get_session
    from shotclassify_store.repository import Repository

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()

    now = datetime.now(timezone.utc)
    repo = Repository()  # initialises schema
    rows = [
        ClassificationRow(
            id=f"r{i}",
            filename=f"f{i}.png",
            created_at=now - timedelta(hours=i % 6),
            primary_category="receipt" if i % 2 == 0 else "code_snippet",
            confidence=0.7 + (i % 3) * 0.1,
            ocr_text="",
            ocr_lang="en",
            extracted={},
            route={"action": "none"},
            elapsed_ms=200 + i * 10,
            user_corrected_to="code_snippet" if i == 1 else None,
        )
        for i in range(8)
    ]
    with get_session() as s:
        for r in rows:
            s.add(r)
        s.commit()

    agg = repo.aggregate(tenant_id=None, hours=24)

    assert agg["total"] == 8
    assert agg["window_count"] == 8
    assert agg["corrections"] == 1
    assert 0.0 < agg["mean_confidence"] <= 1.0
    cats = {p["category"]: p["count"] for p in agg["per_class"]}
    assert cats.get("receipt") == 4
    assert cats.get("code_snippet") == 4
    assert agg["latency_ms"]["p50"] > 0
    assert agg["latency_ms"]["p95"] >= agg["latency_ms"]["p50"]
    assert len(agg["confidence_histogram"]) == 10
    assert sum(b["count"] for b in agg["confidence_histogram"]) == 8
    assert len(agg["hourly"]) >= 1
