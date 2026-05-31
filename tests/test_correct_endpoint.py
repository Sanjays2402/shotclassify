"""Tests for the user-correction endpoint used by the shot detail UI."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def _bootstrap(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'correct.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    # Force heuristic path so we do not hit a real LLM.
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()


def test_correct_updates_record_and_history(monkeypatch, tmp_path):
    _bootstrap(monkeypatch, tmp_path)

    import make_samples
    from services.api.app.main import create_app
    from shotclassify_common.pipeline import process_image

    # Seed one real record via the heuristic pipeline.
    sample = make_samples.make_all()[0]
    seeded = process_image(str(sample), save=True)
    assert seeded.id

    client = TestClient(create_app())
    headers = {"X-API-Key": "k"}

    # Unknown category rejected with structured 422.
    bad = client.post(
        f"/v1/classify/{seeded.id}/correct",
        data={"category": "not_a_class"},
        headers=headers,
    )
    assert bad.status_code == 422

    # Valid correction persists.
    ok = client.post(
        f"/v1/classify/{seeded.id}/correct",
        data={"category": "chart"},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["ok"] is True
    assert body["user_corrected_to"] == "chart"

    # Read-back through history reflects the correction.
    got = client.get(f"/v1/history/{seeded.id}", headers=headers).json()
    assert got["user_corrected_to"] == "chart"

    # Unknown id is a clean 404.
    missing = client.post(
        "/v1/classify/does-not-exist/correct",
        data={"category": "chart"},
        headers=headers,
    )
    assert missing.status_code == 404
