"""End-to-end smoke test using the heuristic classifier (no LLM needed)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import make_samples
from shotclassify_common import Category
from shotclassify_common.pipeline import process_image


def test_end_to_end_on_samples(tmp_path, monkeypatch):
    # Isolated DB
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'e2e.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:1")  # force LLM failure -> heuristic
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()

    paths = make_samples.make_all()
    for p in paths:
        result = process_image(str(p), save=True)
        assert result.id
        # heuristic should at least find receipt or error for those samples
        if p.name == "fake-receipt.png":
            assert result.classification.primary in {Category.receipt, Category.other}
        if p.name == "fake-error.png":
            assert result.classification.primary in {Category.error_stacktrace, Category.other}
