"""Tests for the POST /v1/history/tags/merge endpoint."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'api.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def _seed(filename: str, tags: list[str], tenant_id: str | None = None) -> str:
    from shotclassify_store.db import ClassificationRow, get_session, init_db
    from shotclassify_common import Category

    init_db()
    rid = uuid.uuid4().hex
    with get_session() as s:
        s.add(
            ClassificationRow(
                id=rid,
                created_at=datetime.now(timezone.utc),
                filename=filename,
                primary_category=Category.receipt.value,
                confidence=0.9,
                ocr_text="",
                image_path=None,
                tenant_id=tenant_id,
                label=None,
                tags=tags,
                pinned=False,
            )
        )
        s.commit()
    return rid


def _tags_of(rid: str) -> list[str]:
    from shotclassify_store.db import ClassificationRow, get_session

    with get_session() as s:
        return list(s.get(ClassificationRow, rid).tags or [])


def test_merge_tags_collapses_sources_into_target(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    a = _seed("a.png", ["finace", "q1"])
    b = _seed("b.png", ["financ"])
    cc = _seed("c.png", ["fin", "ops"])
    other = _seed("d.png", ["ops"])

    r = c.post(
        "/v1/history/tags/merge",
        headers={"X-API-Key": "k"},
        json={"sources": ["finace", "financ", "fin"], "target": "finance"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated"] == 3
    assert body["target"] == "finance"
    assert body["sources"] == ["fin", "finace", "financ"]
    assert _tags_of(a) == ["finance", "q1"]
    assert _tags_of(b) == ["finance"]
    assert _tags_of(cc) == ["finance", "ops"]
    assert _tags_of(other) == ["ops"]


def test_merge_tags_dedupes_when_target_already_present(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    rid = _seed("a.png", ["finance", "finace", "financ", "q1"])
    r = c.post(
        "/v1/history/tags/merge",
        headers={"X-API-Key": "k"},
        json={"sources": ["finace", "financ"], "target": "finance"},
    )
    assert r.status_code == 200
    assert r.json()["updated"] == 1
    # First occurrence of finance kept, dupes from merged sources dropped, q1 preserved.
    assert _tags_of(rid) == ["finance", "q1"]


def test_merge_tags_normalizes_inputs(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    rid = _seed("a.png", ["money", "q1"])
    r = c.post(
        "/v1/history/tags/merge",
        headers={"X-API-Key": "k"},
        json={"sources": ["  CASH  ", "Money"], "target": "Funds"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sources"] == ["cash", "money"]
    assert body["target"] == "funds"
    assert body["updated"] == 1
    assert _tags_of(rid) == ["funds", "q1"]


def test_merge_tags_dry_run_does_not_mutate(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    rid = _seed("a.png", ["finace"])
    r = c.post(
        "/v1/history/tags/merge?dry_run=true",
        headers={"X-API-Key": "k"},
        json={"sources": ["finace"], "target": "finance"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["applied"] is False
    assert body["would_update"] == 1
    assert r.headers.get("X-Dry-Run") == "true"
    assert _tags_of(rid) == ["finace"]


def test_merge_tags_noop_when_all_sources_match_target(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"])
    r = c.post(
        "/v1/history/tags/merge",
        headers={"X-API-Key": "k"},
        json={"sources": ["FINANCE", "  finance "], "target": "finance"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"updated": 0, "sources": [], "target": "finance"}


def test_merge_tags_validates_body(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Missing target.
    r = c.post(
        "/v1/history/tags/merge",
        headers={"X-API-Key": "k"},
        json={"sources": ["x"]},
    )
    assert r.status_code == 400
    # Sources not a list.
    r = c.post(
        "/v1/history/tags/merge",
        headers={"X-API-Key": "k"},
        json={"sources": "x", "target": "y"},
    )
    assert r.status_code == 400
    # Empty target normalizes away.
    r = c.post(
        "/v1/history/tags/merge",
        headers={"X-API-Key": "k"},
        json={"sources": ["x"], "target": "   "},
    )
    assert r.status_code == 400
    # Empty sources list.
    r = c.post(
        "/v1/history/tags/merge",
        headers={"X-API-Key": "k"},
        json={"sources": [], "target": "x"},
    )
    assert r.status_code == 400
    # Unknown field.
    r = c.post(
        "/v1/history/tags/merge",
        headers={"X-API-Key": "k"},
        json={"sources": ["a"], "target": "b", "extra": 1},
    )
    assert r.status_code == 400


def test_merge_tags_is_tenant_scoped(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    a = _seed("a.png", ["finace"], tenant_id="acme")
    b = _seed("b.png", ["finace"], tenant_id="globex")
    r = c.post(
        "/v1/history/tags/merge",
        headers={"X-API-Key": "k", "X-Tenant": "acme"},
        json={"sources": ["finace"], "target": "finance"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 1
    assert _tags_of(a) == ["finance"]
    assert _tags_of(b) == ["finace"]


def test_merge_tags_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/history/tags/merge",
        json={"sources": ["a"], "target": "b"},
    )
    assert r.status_code in (401, 403)
