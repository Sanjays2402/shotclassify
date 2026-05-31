"""Cross-tenant isolation on the authenticated blob endpoint.

The previous ``/blob/<filename>`` static mount returned the raw bytes of
any upload to any caller. The new ``/v1/blobs/{record_id}`` endpoint
must:

* refuse callers without a valid session or API key (401),
* refuse callers whose tenant does not own the record (404, same as a
  missing record so tenant existence does not leak),
* return the file to the owning tenant.

This test reuses the multi-tenant harness pattern from
``tests/test_multitenant.py``.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps({
            "acme-op-key": "operator",
            "globex-op-key": "operator",
        }),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps({
            "acme-op-key": "acme",
            "globex-op-key": "globex",
        }),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "default")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'blobs.db'}")
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


# A minimal 1x1 PNG so FileResponse has real bytes to serve.
_PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d4944415478da6300010000000005000169f70e9c0000000049454e44ae426082"
)


def _seed_with_blob(tmp_path, tenant_id, principal):
    """Save a real classification row with a real blob file on disk."""
    from shotclassify_common import (
        Category,
        Classification,
        Confidence,
        ExtractedFields,
        OCRResult,
        ProcessResult,
        RouteDecision,
    )
    from shotclassify_common.utils import new_id, utcnow
    from shotclassify_store import Repository

    rid = new_id()
    blob_dir = tmp_path / "storage" / "uploads"
    blob_dir.mkdir(parents=True, exist_ok=True)
    blob_path = blob_dir / f"{rid}.png"
    blob_path.write_bytes(_PNG_1X1)

    rec = ProcessResult(
        id=rid,
        filename=f"{tenant_id}.png",
        created_at=utcnow(),
        classification=Classification(
            primary=Category.other,
            confidences=[Confidence(category=Category.other, score=1.0)],
        ),
        ocr=OCRResult(text="", language="en"),
        extracted=ExtractedFields(),
        route=RouteDecision(action="none"),
        elapsed_ms=1,
        image_url=None,
    )
    Repository().save_result(
        rec, image_path=str(blob_path), principal=principal, tenant_id=tenant_id
    )
    return rid


def test_blob_requires_authentication(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    rid = _seed_with_blob(tmp_path, "acme", "acme-op-key")
    # No key at all.
    r = c.get(f"/v1/blobs/{rid}")
    assert r.status_code == 401


def test_owning_tenant_can_fetch_blob(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    rid = _seed_with_blob(tmp_path, "acme", "acme-op-key")
    r = c.get(f"/v1/blobs/{rid}", headers={"X-API-Key": "acme-op-key"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.headers["cache-control"] == "private, no-store"
    assert r.content == _PNG_1X1


def test_other_tenant_gets_404_not_image(monkeypatch, tmp_path):
    """The critical regression test: a different tenant must not be able
    to read another tenant's screenshot by guessing or harvesting the id.
    """
    c = _client(monkeypatch, tmp_path)
    rid = _seed_with_blob(tmp_path, "acme", "acme-op-key")
    r = c.get(f"/v1/blobs/{rid}", headers={"X-API-Key": "globex-op-key"})
    assert r.status_code == 404
    # Bytes must not leak even in the error body.
    assert _PNG_1X1 not in r.content


def test_unknown_id_is_404(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/blobs/00000000000000000000000000000000",
        headers={"X-API-Key": "acme-op-key"},
    )
    assert r.status_code == 404


def test_static_blob_mount_is_gone(monkeypatch, tmp_path):
    """The old unauthenticated /blob/<filename> route must no longer exist.
    If somebody re-adds StaticFiles at /blob, this test should fail.
    """
    c = _client(monkeypatch, tmp_path)
    rid = _seed_with_blob(tmp_path, "acme", "acme-op-key")
    r = c.get(f"/blob/{rid}.png")
    assert r.status_code in (401, 404)
    assert _PNG_1X1 not in r.content
