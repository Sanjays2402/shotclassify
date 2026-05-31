"""Tests for the per-principal usage and quota endpoint."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path, free_limit: str = "5"):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'usage.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("SHOTCLASSIFY_FREE_MONTHLY_LIMIT", free_limit)
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def _seed(principal: str, n: int) -> None:
    """Insert ``n`` classifications owned by ``principal`` in the current month."""
    from shotclassify_common import (
        Category,
        Classification,
        Confidence,
        ExtractedFields,
        OCRResult,
        ProcessResult,
        RouteAction,
        RouteDecision,
    )
    from shotclassify_common.utils import new_id
    from shotclassify_store import Repository

    repo = Repository()
    for _ in range(n):
        rid = new_id()
        repo.save_result(
            ProcessResult(
                id=rid,
                filename="fake.png",
                created_at=datetime.now(UTC),
                classification=Classification(
                    primary=Category.other,
                    confidences=[Confidence(category=Category.other, score=0.9)],
                ),
                ocr=OCRResult(text="", language="und"),
                extracted=ExtractedFields(),
                route=RouteDecision(action=RouteAction.none),
                elapsed_ms=1,
                image_url=None,
            ),
            image_path=None,
            principal=principal,
        )


def test_usage_endpoint_reports_current_month_counts(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, free_limit="10")
    _seed("api-key", 3)
    _seed("someone-else", 2)  # other principal's rows must not count

    r = c.get("/v1/me/usage", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["principal"] == "api-key"
    assert body["plan"] == "free"
    assert body["limit"] == 10
    assert body["used"] == 3
    assert body["remaining"] == 7
    assert body["over_limit"] is False
    assert 0.29 < body["percent"] < 0.31


def test_usage_requires_authentication(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/me/usage")
    assert r.status_code == 401


def test_classify_returns_402_when_over_quota(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, free_limit="2")
    _seed("api-key", 2)  # already at limit

    # A tiny valid PNG (1x1) so we get past content-type and into the quota
    # check rather than into the vision pipeline.
    png_1x1 = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    r = c.post(
        "/v1/classify",
        headers={"X-API-Key": "k"},
        files={"file": ("a.png", png_1x1, "image/png")},
    )
    assert r.status_code == 402, r.text
    detail = r.json().get("detail") or {}
    assert detail.get("error") == "quota_exceeded"
    assert detail.get("usage", {}).get("over_limit") is True
