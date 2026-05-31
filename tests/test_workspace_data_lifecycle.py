"""Workspace-wide GDPR data lifecycle tests.

Verifies that ``/v1/workspace/data`` (export + erasure):

* requires admin role + tenant context
* exports rows for the caller's tenant only (no cross-tenant leakage)
* hard-deletes only the caller's tenant on confirm=erase
* supports ?dry_run=true without mutating
* returns a real ZIP bundle with the expected file entries
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path, *, mfa_off: bool = True):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    # operator role for a second key so we can test 403
    monkeypatch.setenv(
        "AUTH_API_KEYS", json.dumps({"viewer-key": "viewer", "op-key": "operator"})
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'wsdata.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    if mfa_off:
        # MFA step-up dependency is a no-op when MFA is globally disabled.
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
        ocr=OCRResult(text="hello", language="en"),
        extracted=ExtractedFields(),
        route=RouteDecision(action=RouteAction.none),
        elapsed_ms=1,
        image_url=None,
    )
    Repository().save_result(
        result, image_path=None, principal=principal, tenant_id=tenant_id
    )
    return rid


def test_export_requires_admin_role(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # viewer key -> 403
    r = c.get("/v1/workspace/data", headers={"x-api-key": "viewer-key"})
    assert r.status_code == 403, r.text
    # operator key -> 403
    r = c.get("/v1/workspace/data", headers={"x-api-key": "op-key"})
    assert r.status_code == 403


def test_export_scoped_to_tenant_and_returns_zip(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    mine = _seed("alice", "tenant-a")
    other = _seed("bob", "tenant-b", filename="other.png")

    headers = {"x-api-key": "admin-key", "x-tenant": "tenant-a"}
    r = c.get("/v1/workspace/data", headers=headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"].startswith("attachment;")

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert {
        "manifest.json",
        "classifications.json",
        "audit_log.json",
        "saved_views.json",
        "members.json",
        "api_keys.json",
        "settings.json",
    }.issubset(names)

    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["tenant_id"] == "tenant-a"

    rows = json.loads(zf.read("classifications.json"))
    ids = {row["id"] for row in rows}
    # Cross-tenant isolation: bob's row in tenant-b must not leak.
    assert mine in ids
    assert other not in ids


def test_delete_workspace_data_isolates_tenant(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    mine = _seed("alice", "tenant-a")
    other = _seed("bob", "tenant-b")

    # Missing confirm -> 400
    r = c.delete(
        "/v1/workspace/data",
        headers={"x-api-key": "admin-key", "x-tenant": "tenant-a"},
    )
    assert r.status_code == 400

    # dry_run -> no mutation
    r = c.delete(
        "/v1/workspace/data?dry_run=true",
        headers={"x-api-key": "admin-key", "x-tenant": "tenant-a"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["would_delete"]["classifications"] >= 1

    # Real erase, scoped to tenant-a
    r = c.delete(
        "/v1/workspace/data?confirm=erase",
        headers={"x-api-key": "admin-key", "x-tenant": "tenant-a"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "tenant-a"
    assert body["deleted"]["classifications"] >= 1

    # tenant-b's row must still exist.
    from shotclassify_store import Repository

    remaining_b = {row.id for row in Repository().list_by_tenant("tenant-b")}
    assert other in remaining_b
    remaining_a = {row.id for row in Repository().list_by_tenant("tenant-a")}
    assert mine not in remaining_a
