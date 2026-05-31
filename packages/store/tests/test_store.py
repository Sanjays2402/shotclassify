from datetime import datetime, timezone

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
from shotclassify_store import Repository
from shotclassify_store.blobs import LocalBlobStore


def _result(rid="t1", cat=Category.receipt):
    return ProcessResult(
        id=rid,
        filename="t.png",
        created_at=datetime.now(timezone.utc),
        classification=Classification(
            primary=cat, confidences=[Confidence(category=cat, score=0.9)]
        ),
        ocr=OCRResult(text="hello world", language="en", word_count=2),
        extracted=ExtractedFields(),
        route=RouteDecision(action=RouteAction.none, dry_run=True),
        elapsed_ms=10,
    )


def test_repository_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db, repository

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()

    repo = Repository()
    repo.save_result(_result())
    got = repo.get("t1")
    assert got is not None
    assert got.primary_category == Category.receipt
    assert repo.count() == 1
    assert repo.list(query="hello")[0].id == "t1"
    repo.correct("t1", Category.meme)
    assert repo.get("t1").user_corrected_to == Category.meme
    assert repo.delete("t1") is True


def test_local_blob_store(tmp_path):
    store = LocalBlobStore(tmp_path)
    p = store.put("a/b.png", b"hello")
    assert open(p, "rb").read() == b"hello"


def test_repository_update_meta(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'meta.db'}")
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db, repository

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()

    repo = Repository()
    repo.save_result(_result(rid="m1", cat=Category.receipt))
    repo.save_result(_result(rid="m2", cat=Category.receipt))

    # Default state.
    assert repo.get("m1").label is None
    assert repo.get("m1").tags == []

    # Rename + add tags. Tags are normalized (lowercase, trim, dedupe).
    updated = repo.update_meta(
        "m1",
        label="  Q3 Receipts  ",
        tags=["Finance", "finance", "Reviewed", "  Tax  ", ""],
    )
    assert updated is not None
    assert updated.label == "Q3 Receipts"
    assert updated.tags == ["finance", "reviewed", "tax"]

    # Tag-filtered list returns only the tagged row.
    only_finance = repo.list(tag="finance")
    assert [r.id for r in only_finance] == ["m1"]
    assert repo.count_filtered(tag="finance") == 1
    assert repo.count_filtered(tag="missing-tag") == 0

    # Clearing label and tags works.
    cleared = repo.update_meta("m1", clear_label=True, tags=[])
    assert cleared.label is None
    assert cleared.tags == []

    # Missing record returns None.
    assert repo.update_meta("does-not-exist", label="x") is None
