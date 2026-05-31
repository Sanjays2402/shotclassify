"""Sandbox / dry-run mode for destructive endpoints.

Enterprise procurement reviewers require that destructive mutations can
be previewed without side effects. These tests assert that:

* ``DELETE /v1/history/{id}?dry_run=true`` does not delete the row,
  returns ``dry_run: true`` and the ``X-Dry-Run`` header.
* ``POST   /v1/history/bulk?dry_run=true`` (delete action) reports
  ``would_affect`` but leaves rows in place.
* ``DELETE /v1/me/data?dry_run=true`` previews counts and preserves data.
* Cross-tenant safety is preserved: a dry-run still cannot peek at rows
  in another tenant.
* The audit row written by the middleware tags the request with
  ``extra.dry_run = True``.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv("AUTH_API_KEYS", json.dumps({"op-key": "operator"}))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'dryrun.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("AUTH_MFA_REQUIRED", "false")
    monkeypatch.setenv("MFA_REQUIRED_FOR_ADMIN", "false")
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def _seed(principal: str, tenant_id: str, filename: str = "fake.png") -> str:
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
        filename=filename,
        created_at=datetime.now(UTC),
        classification=Classification(
            primary=Category.other,
            confidences=[Confidence(category=Category.other, score=0.9)],
        ),
        ocr=OCRResult(text="hi", language="en"),
        extracted=ExtractedFields(),
        route=RouteDecision(action=RouteAction.none),
        elapsed_ms=1,
        image_url=None,
    )
    Repository().save_result(
        result, image_path=None, principal=principal, tenant_id=tenant_id
    )
    return rid


def test_history_delete_dry_run_does_not_mutate(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    rid = _seed("alice", "tenant-a")

    headers = {"x-api-key": "admin-key", "x-tenant": "tenant-a"}
    r = c.delete(f"/v1/history/{rid}?dry_run=true", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["applied"] is False
    assert body["would_delete"]["id"] == rid
    assert r.headers.get("X-Dry-Run") == "true"

    # Row still present.
    g = c.get(f"/v1/history/{rid}", headers=headers)
    assert g.status_code == 200

    # Real delete still works.
    real = c.delete(f"/v1/history/{rid}", headers=headers)
    assert real.status_code == 200
    assert real.json() == {"ok": True}
    assert c.get(f"/v1/history/{rid}", headers=headers).status_code == 404


def test_history_bulk_delete_dry_run_preserves_rows(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    ids = [_seed("alice", "tenant-a") for _ in range(3)]
    headers = {"x-api-key": "admin-key", "x-tenant": "tenant-a"}

    r = c.post(
        "/v1/history/bulk?dry_run=true",
        headers=headers,
        json={"ids": ids, "action": "delete"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["applied"] is False
    assert body["would_affect"] == 3
    assert body["missing"] == []

    # All rows still present.
    for rid in ids:
        assert c.get(f"/v1/history/{rid}", headers=headers).status_code == 200


def test_dry_run_cannot_peek_other_tenant(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    other = _seed("bob", "tenant-b")

    # Admin in tenant-a previews a delete of bob's id in tenant-b.
    headers = {"x-api-key": "admin-key", "x-tenant": "tenant-a"}
    r = c.delete(f"/v1/history/{other}?dry_run=true", headers=headers)
    # Cross-tenant ids must not be reported as "would_delete" with any
    # information that betrays their existence.
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["would_delete"] is None

    # Bob's row is still present in tenant-b.
    bob = c.get(
        f"/v1/history/{other}",
        headers={"x-api-key": "admin-key", "x-tenant": "tenant-b"},
    )
    assert bob.status_code == 200


def test_me_data_dry_run_previews_without_erasing(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("api-key", "tenant-a")
    _seed("api-key", "tenant-a", filename="b.png")

    headers = {"x-api-key": "admin-key", "x-tenant": "tenant-a"}
    r = c.request("DELETE", "/v1/me/data", headers=headers, params={"dry_run": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["would_delete"]["classifications"] == 2
    assert r.headers.get("X-Dry-Run") == "true"

    # Rows still there.
    listing = c.get("/v1/history", headers=headers).json()
    rows = listing.get("items", listing) if isinstance(listing, dict) else listing
    assert len(rows) == 2


def test_dry_run_audit_row_tagged(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    rid = _seed("alice", "tenant-a")
    headers = {"x-api-key": "admin-key", "x-tenant": "tenant-a"}

    r = c.delete(f"/v1/history/{rid}?dry_run=true", headers=headers)
    assert r.status_code == 200

    from shotclassify_store import AuditRepository

    rows = AuditRepository().list(path_prefix="/v1/history", tenant_id="tenant-a", limit=20)
    matching = [row for row in rows if row["path"].endswith(rid) and row["method"] == "DELETE"]
    assert matching, "audit row for the dry-run delete was not recorded"
    assert matching[0]["extra"].get("dry_run") is True
