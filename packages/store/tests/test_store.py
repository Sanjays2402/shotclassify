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
