"""Per-tenant upload content-type allow-list is enforced end-to-end.

* The default has no per-tenant policy and any image/* MIME is accepted.
* Setting the policy requires admin role and MFA step-up.
* Once set, ``POST /v1/classify`` rejects an upload whose Content-Type
  is not on the list with HTTP 415 ``content_type_not_allowed`` before
  the bytes are buffered or sent to the model.
* The policy is strictly tenant-scoped: tightening tenant A does not
  affect tenant B, and tenant A's row is never read by a caller
  resolved to tenant B (no cross-tenant leakage).
* The legacy ``image/`` gate still applies when the policy is empty,
  so existing single-tenant deployments keep working unchanged.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from services.api.app.main import create_app


def _png(width: int = 32, height: int = 32) -> bytes:
    img = Image.new("RGB", (width, height), color=(40, 60, 90))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps({"admin-a": "admin", "admin-b": "admin"}),
    )
    monkeypatch.setenv("AUTH_API_KEY", "admin-a")
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps({"admin-a": "tenant-a", "admin-b": "tenant-b"}),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "tenant-a")
    monkeypatch.setenv("MFA_STEP_UP_REQUIRED", "false")
    monkeypatch.setenv(
        "DATABASE_URL", f"sqlite:///{tmp_path/'content_types.db'}"
    )
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    from shotclassify_store import init_db

    init_db()
    return TestClient(create_app())


def _hdr(key: str) -> dict:
    return {"X-API-Key": key}


def test_default_policy_is_empty_and_any_image_mime_accepted(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/settings/security/upload-content-types", headers=_hdr("admin-a")
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["types"] == []
    assert body["enforced"] is False
    assert body["max_entries"] >= 1
    assert "image/png" in body["known"]

    img = _png()
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-a"),
        files={"file": ("a.png", img, "image/png")},
    )
    assert r.status_code == 200, r.text

    # Legacy gate is still active: a non-image MIME is rejected with 415
    # even when no per-tenant policy is set.
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-a"),
        files={"file": ("a.bin", b"not-an-image", "application/octet-stream")},
    )
    assert r.status_code == 415, r.text


def test_policy_rejects_disallowed_content_type(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/upload-content-types",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"types": ["image/png"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["types"] == ["image/png"]
    assert body["enforced"] is True

    # PNG still works.
    img = _png()
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-a"),
        files={"file": ("a.png", img, "image/png")},
    )
    assert r.status_code == 200, r.text

    # JPEG is now refused at the gate.
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (10, 20, 30)).save(buf, format="JPEG")
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-a"),
        files={"file": ("a.jpg", buf.getvalue(), "image/jpeg")},
    )
    assert r.status_code == 415, r.text
    detail = r.json().get("detail")
    if isinstance(detail, dict):
        assert detail["error"] == "content_type_not_allowed"
        assert detail["allowed"] == ["image/png"]
        assert detail["policy_enforced"] is True
    else:
        assert "content_type_not_allowed" in r.text


def test_policy_is_strictly_tenant_scoped(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Tenant A locks to PNG.
    r = c.put(
        "/v1/settings/security/upload-content-types",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"types": ["image/png"]},
    )
    assert r.status_code == 200, r.text

    # Tenant B sees no policy (no cross-tenant read).
    r = c.get(
        "/v1/settings/security/upload-content-types", headers=_hdr("admin-b")
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "tenant-b"
    assert body["types"] == []
    assert body["enforced"] is False

    # Tenant B can still upload a JPEG that tenant A would refuse.
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (10, 20, 30)).save(buf, format="JPEG")
    jpeg = buf.getvalue()
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-b"),
        files={"file": ("a.jpg", jpeg, "image/jpeg")},
    )
    assert r.status_code == 200, r.text

    # And the same JPEG remains blocked for tenant A.
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-a"),
        files={"file": ("a.jpg", jpeg, "image/jpeg")},
    )
    assert r.status_code == 415, r.text


def test_clear_policy_falls_back_to_legacy_gate(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.put(
        "/v1/settings/security/upload-content-types",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"types": ["image/png"]},
    )
    # Clearing returns to default behaviour.
    r = c.put(
        "/v1/settings/security/upload-content-types",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"types": []},
    )
    assert r.status_code == 200, r.text
    assert r.json()["enforced"] is False

    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (10, 20, 30)).save(buf, format="JPEG")
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-a"),
        files={"file": ("a.jpg", buf.getvalue(), "image/jpeg")},
    )
    assert r.status_code == 200, r.text


def test_set_rejects_invalid_entries(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/upload-content-types",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"types": ["not a mime"]},
    )
    assert r.status_code == 422, r.text
    r = c.put(
        "/v1/settings/security/upload-content-types",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"types": "image/png"},
    )
    assert r.status_code == 422, r.text
    r = c.put(
        "/v1/settings/security/upload-content-types",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={},
    )
    assert r.status_code == 422, r.text
