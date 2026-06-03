"""Tests for tagged/untagged split on /v1/history/stats."""
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


def _seed(
    filename: str,
    tags: list[str] | None,
    pinned: bool = False,
    confidence: float = 0.9,
) -> None:
    from shotclassify_store.db import ClassificationRow, get_session, init_db
    from shotclassify_common import Category

    init_db()
    with get_session() as s:
        s.add(
            ClassificationRow(
                id=uuid.uuid4().hex,
                created_at=datetime.now(timezone.utc),
                filename=filename,
                primary_category=Category.receipt.value,
                confidence=confidence,
                ocr_text="",
                image_path=None,
                tenant_id=None,
                label=None,
                tags=tags,
                pinned=pinned,
            )
        )
        s.commit()


def test_stats_reports_untagged_and_tagged_split(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["finance"])
    _seed("b.png", ["finance", "q1"])
    _seed("c.png", [])
    _seed("d.png", None)

    r = c.get("/v1/history/stats", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 4
    assert body["untagged"] == 2
    assert body["tagged"] == 2
    # Invariant: untagged + tagged == count, always.
    assert body["untagged"] + body["tagged"] == body["count"]
    # Nothing was pinned in this fixture.
    assert body["pinned"] == 0
    assert body["pinned_untagged"] == 0
    # All rows seeded at confidence 0.9, above the 0.7 default cutoff.
    assert body["low_confidence"] == 0
    assert body["pinned_low_confidence"] == 0
    assert body["untagged_low_confidence"] == 0
    assert body["tagged_low_confidence"] == 0


def test_stats_all_untagged_when_no_tags(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", None)
    _seed("b.png", [])

    body = c.get("/v1/history/stats", headers={"X-API-Key": "k"}).json()
    assert body == {
        "count": 2,
        "untagged": 2,
        "tagged": 0,
        "pinned": 0,
        "pinned_untagged": 0,
        "low_confidence": 0,
        "pinned_low_confidence": 0,
        "untagged_low_confidence": 0,
        "tagged_low_confidence": 0,
    }


def test_stats_all_tagged(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["x"])
    _seed("b.png", ["y", "z"])

    body = c.get("/v1/history/stats", headers={"X-API-Key": "k"}).json()
    assert body == {
        "count": 2,
        "untagged": 0,
        "tagged": 2,
        "pinned": 0,
        "pinned_untagged": 0,
        "low_confidence": 0,
        "pinned_low_confidence": 0,
        "untagged_low_confidence": 0,
        "tagged_low_confidence": 0,
    }


def test_stats_empty(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    from shotclassify_store.db import init_db
    init_db()

    body = c.get("/v1/history/stats", headers={"X-API-Key": "k"}).json()
    assert body == {
        "count": 0,
        "untagged": 0,
        "tagged": 0,
        "pinned": 0,
        "pinned_untagged": 0,
        "low_confidence": 0,
        "pinned_low_confidence": 0,
        "untagged_low_confidence": 0,
        "tagged_low_confidence": 0,
    }


def test_stats_low_confidence_uses_default_cutoff(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Below default 0.7 cutoff (inclusive): both count as low-confidence.
    _seed("a.png", ["x"], confidence=0.4)
    _seed("b.png", None, confidence=0.7)
    # Above cutoff: excluded.
    _seed("c.png", ["y"], confidence=0.71)
    _seed("d.png", ["z"], confidence=0.95)

    body = c.get("/v1/history/stats", headers={"X-API-Key": "k"}).json()
    assert body["count"] == 4
    # Independent of tagged/pinned splits; just confidence-bounded.
    assert body["low_confidence"] == 2
    assert body["low_confidence"] <= body["count"]


def test_stats_low_confidence_respects_threshold_query(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["x"], confidence=0.4)
    _seed("b.png", ["x"], confidence=0.6)
    _seed("c.png", ["x"], confidence=0.8)

    body = c.get(
        "/v1/history/stats",
        params={"low_conf_threshold": 0.5},
        headers={"X-API-Key": "k"},
    ).json()
    # Only the 0.4 row sits at or below 0.5.
    assert body["low_confidence"] == 1

    body = c.get(
        "/v1/history/stats",
        params={"low_conf_threshold": 0.9},
        headers={"X-API-Key": "k"},
    ).json()
    assert body["low_confidence"] == 3


def test_stats_rejects_threshold_out_of_range(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/history/stats",
        params={"low_conf_threshold": 1.5},
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 422


def test_stats_reports_pinned_count_independent_of_tagged(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Pinned + tagged.
    _seed("a.png", ["finance"], pinned=True)
    # Pinned + untagged (pinned should still count it).
    _seed("b.png", None, pinned=True)
    # Unpinned + tagged.
    _seed("c.png", ["q1"], pinned=False)
    # Unpinned + untagged.
    _seed("d.png", [], pinned=False)

    body = c.get("/v1/history/stats", headers={"X-API-Key": "k"}).json()
    assert body["count"] == 4
    assert body["tagged"] == 2
    assert body["untagged"] == 2
    assert body["pinned"] == 2
    # Pinned is independent of the tagged/untagged split; it can overlap
    # either bucket and is not required to sum with them.
    assert body["untagged"] + body["tagged"] == body["count"]
    # Only b.png is both pinned and untagged in this fixture.
    assert body["pinned_untagged"] == 1
    # The intersection can never exceed either side it intersects.
    assert body["pinned_untagged"] <= body["pinned"]
    assert body["pinned_untagged"] <= body["untagged"]


def test_stats_pinned_untagged_zero_when_all_pinned_are_tagged(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Every pinned row also has at least one tag.
    _seed("a.png", ["finance"], pinned=True)
    _seed("b.png", ["q1"], pinned=True)
    # Unpinned + untagged: not part of the intersection.
    _seed("c.png", None, pinned=False)

    body = c.get("/v1/history/stats", headers={"X-API-Key": "k"}).json()
    assert body["pinned"] == 2
    assert body["untagged"] == 1
    assert body["pinned_untagged"] == 0


def test_stats_pinned_low_confidence_intersection(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Pinned and low confidence: counted.
    _seed("a.png", ["x"], pinned=True, confidence=0.3)
    _seed("b.png", None, pinned=True, confidence=0.7)
    # Pinned but high confidence: excluded.
    _seed("c.png", ["y"], pinned=True, confidence=0.95)
    # Low confidence but unpinned: excluded.
    _seed("d.png", ["z"], pinned=False, confidence=0.4)

    body = c.get("/v1/history/stats", headers={"X-API-Key": "k"}).json()
    assert body["count"] == 4
    assert body["pinned"] == 3
    assert body["low_confidence"] == 3
    # Only a.png and b.png are both pinned and at-or-below the 0.7 cutoff.
    assert body["pinned_low_confidence"] == 2
    # Intersection never exceeds either side.
    assert body["pinned_low_confidence"] <= body["pinned"]
    assert body["pinned_low_confidence"] <= body["low_confidence"]


def test_stats_pinned_low_confidence_respects_threshold_query(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["x"], pinned=True, confidence=0.4)
    _seed("b.png", ["x"], pinned=True, confidence=0.6)
    _seed("c.png", ["x"], pinned=True, confidence=0.8)
    _seed("d.png", ["x"], pinned=False, confidence=0.2)

    body = c.get(
        "/v1/history/stats",
        params={"low_conf_threshold": 0.5},
        headers={"X-API-Key": "k"},
    ).json()
    # Only the pinned 0.4 row sits at or below 0.5.
    assert body["pinned_low_confidence"] == 1

    body = c.get(
        "/v1/history/stats",
        params={"low_conf_threshold": 0.9},
        headers={"X-API-Key": "k"},
    ).json()
    # All three pinned rows sit at or below 0.9.
    assert body["pinned_low_confidence"] == 3


def test_stats_untagged_low_confidence_intersection(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Untagged and low confidence: counted.
    _seed("a.png", None, confidence=0.3)
    _seed("b.png", [], confidence=0.7)
    # Untagged but high confidence: excluded.
    _seed("c.png", None, confidence=0.95)
    # Low confidence but tagged: excluded.
    _seed("d.png", ["z"], confidence=0.4)

    body = c.get("/v1/history/stats", headers={"X-API-Key": "k"}).json()
    assert body["count"] == 4
    assert body["untagged"] == 3
    assert body["low_confidence"] == 3
    # Only a.png and b.png are both untagged and at-or-below the 0.7 cutoff.
    assert body["untagged_low_confidence"] == 2
    # Intersection never exceeds either side.
    assert body["untagged_low_confidence"] <= body["untagged"]
    assert body["untagged_low_confidence"] <= body["low_confidence"]


def test_stats_untagged_low_confidence_respects_threshold_query(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", None, confidence=0.4)
    _seed("b.png", [], confidence=0.6)
    _seed("c.png", None, confidence=0.8)
    _seed("d.png", ["x"], confidence=0.2)

    body = c.get(
        "/v1/history/stats",
        params={"low_conf_threshold": 0.5},
        headers={"X-API-Key": "k"},
    ).json()
    # Only the untagged 0.4 row sits at or below 0.5.
    assert body["untagged_low_confidence"] == 1

    body = c.get(
        "/v1/history/stats",
        params={"low_conf_threshold": 0.9},
        headers={"X-API-Key": "k"},
    ).json()
    # All three untagged rows sit at or below 0.9; the tagged 0.2 row is excluded.
    assert body["untagged_low_confidence"] == 3


def test_stats_tagged_low_confidence_intersection(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Tagged and low confidence: counted.
    _seed("a.png", ["finance"], confidence=0.3)
    _seed("b.png", ["q1", "q2"], confidence=0.7)
    # Tagged but high confidence: excluded.
    _seed("c.png", ["finance"], confidence=0.95)
    # Low confidence but untagged: excluded.
    _seed("d.png", None, confidence=0.4)
    _seed("e.png", [], confidence=0.2)

    body = c.get("/v1/history/stats", headers={"X-API-Key": "k"}).json()
    assert body["count"] == 5
    assert body["tagged"] == 3
    assert body["low_confidence"] == 4
    # Only a.png and b.png are both tagged and at-or-below the 0.7 cutoff.
    assert body["tagged_low_confidence"] == 2
    # Intersection never exceeds either side.
    assert body["tagged_low_confidence"] <= body["tagged"]
    assert body["tagged_low_confidence"] <= body["low_confidence"]
    # The two low-confidence splits partition the low-confidence total.
    assert (
        body["tagged_low_confidence"] + body["untagged_low_confidence"]
        == body["low_confidence"]
    )


def test_stats_tagged_low_confidence_respects_threshold_query(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("a.png", ["x"], confidence=0.4)
    _seed("b.png", ["y"], confidence=0.6)
    _seed("c.png", ["z"], confidence=0.8)
    _seed("d.png", None, confidence=0.2)

    body = c.get(
        "/v1/history/stats",
        params={"low_conf_threshold": 0.5},
        headers={"X-API-Key": "k"},
    ).json()
    # Only the tagged 0.4 row sits at or below 0.5.
    assert body["tagged_low_confidence"] == 1

    body = c.get(
        "/v1/history/stats",
        params={"low_conf_threshold": 0.9},
        headers={"X-API-Key": "k"},
    ).json()
    # All three tagged rows sit at or below 0.9; the untagged 0.2 row is excluded.
    assert body["tagged_low_confidence"] == 3
