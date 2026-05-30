"""GDPR data lifecycle endpoint tests.

Verifies that an authenticated principal can export everything stored
about them and erase it permanently via ``/v1/me/data``.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'gdpr.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def _seed_classification(principal: str, image_path: str) -> str:
    """Insert a classification directly via the repo so we don't need the
    full vision pipeline available during tests."""
    from datetime import UTC, datetime

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

    rid = new_id()
    result = ProcessResult(
        id=rid,
        filename="fake.png",
        created_at=datetime.now(UTC),
        classification=Classification(
            primary=Category.other,
            confidences=[Confidence(category=Category.other, score=0.9)],
        ),
        ocr=OCRResult(text="hello world", language="en"),
        extracted=ExtractedFields(),
        route=RouteDecision(action=RouteAction.none),
        elapsed_ms=1,
        image_url=None,
    )
    Repository().save_result(result, image_path=image_path, principal=principal)
    return rid


def test_export_my_data_returns_principal_scoped_payload(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    # Seed two rows: one owned by "api-key" (our caller), one by someone else.
    blob = tmp_path / "storage" / "mine.png"
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(b"\x89PNG\r\n\x1a\n")
    mine_id = _seed_classification("api-key", str(blob))
    other_id = _seed_classification("someone-else", str(blob.parent / "other.png"))

    # Generate at least one audited mutation owned by "api-key".
    r = c.put(
        "/v1/settings/rules",
        json={"yaml": "defaults: {dry_run: true}\nrules: []\n"},
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200

    r = c.get("/v1/me/data", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["principal"] == "api-key"
    cls_ids = {row["id"] for row in body["classifications"]}
    assert mine_id in cls_ids
    assert other_id not in cls_ids
    assert body["counts"]["classifications"] == 1
    # The PUT above should have produced at least one audit row.
    assert body["counts"]["audit_log"] >= 1
    assert all(row["principal"] == "api-key" for row in body["audit_log"])


def test_delete_my_data_requires_confirm_and_erases_only_caller_rows(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    mine_blob = tmp_path / "storage" / "mine.png"
    mine_blob.parent.mkdir(parents=True, exist_ok=True)
    mine_blob.write_bytes(b"\x89PNG\r\n\x1a\n")
    other_blob = tmp_path / "storage" / "other.png"
    other_blob.write_bytes(b"\x89PNG\r\n\x1a\n")

    mine_id = _seed_classification("api-key", str(mine_blob))
    other_id = _seed_classification("someone-else", str(other_blob))

    # Without confirm -> 400, nothing erased.
    r = c.delete("/v1/me/data", headers={"X-API-Key": "k"})
    assert r.status_code == 400
    from shotclassify_store import Repository

    assert Repository().get(mine_id) is not None

    # With confirm -> erases only the caller's rows and unlinks their blob.
    r = c.delete("/v1/me/data?confirm=erase", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"]["classifications"] == 1
    repo = Repository()
    assert repo.get(mine_id) is None
    assert repo.get(other_id) is not None
    assert not mine_blob.exists()
    assert other_blob.exists()


def test_me_data_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/v1/me/data").status_code == 401
    assert c.delete("/v1/me/data?confirm=erase").status_code == 401
