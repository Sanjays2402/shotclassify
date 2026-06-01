"""Per-tenant allowed upload content-types policy is enforced end-to-end.

* The default has no per-tenant allow-list and any ``image/*`` upload
  succeeds (legacy single-tenant behaviour).
* Setting the policy requires admin role.
* Once set, ``POST /v1/classify`` rejects an upload whose declared
  Content-Type is not on the list with HTTP 415
  ``content_type_not_allowed`` before the file is buffered to disk or
  routed to the model.
* The policy is strictly tenant-scoped: a tight allow-list on tenant A
  does not affect tenant B, and tenant A's policy row is never read by
  a caller resolved to tenant B (no cross-tenant leakage).
* Invalid MIME entries are rejected at write time so the audit log
  never records a value the gate could not parse later.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from services.api.app.main import create_app


def _png(width: int = 64, height: int = 64) -> bytes:
    img = Image.new("RGB", (width, height), color=(40, 60, 90))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(width: int = 64, height: int = 64) -> bytes:
    img = Image.new("RGB", (width, height), color=(120, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def _client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-a")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps({"admin-a": "admin", "admin-b": "admin"}),
    )
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


def test_default_policy_is_empty_and_any_image_uploads(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/settings/security/upload-content-types", headers=_hdr("admin-a")
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["types"] == []
    assert body["enforced"] is False
    assert "image/png" in body["known"]
    assert body["max_entries"] >= 8

    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-a"),
        files={"file": ("a.jpg", _jpeg(), "image/jpeg")},
    )
    assert r.status_code == 200, r.text


def test_policy_rejects_disallowed_content_type(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Lock tenant A down to PNG only. JPEG and SVG must be refused.
    r = c.put(
        "/v1/settings/security/upload-content-types",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"types": ["image/png"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["types"] == ["image/png"]
    assert r.json()["enforced"] is True

    # JPEG upload refused with structured 415 before disk write.
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-a"),
        files={"file": ("a.jpg", _jpeg(), "image/jpeg")},
    )
    assert r.status_code == 415, r.text
    detail = r.json().get("detail")
    if isinstance(detail, dict):
        assert detail["error"] == "content_type_not_allowed"
        assert detail["content_type"] == "image/jpeg"
        assert detail["allowed"] == ["image/png"]
    else:
        assert "content_type_not_allowed" in r.text

    # SVG (active content) is refused even though it is image/*.
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-a"),
        files={"file": ("a.svg", b"<svg/>", "image/svg+xml")},
    )
    assert r.status_code == 415, r.text

    # An allowed PNG still succeeds.
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-a"),
        files={"file": ("ok.png", _png(), "image/png")},
    )
    assert r.status_code == 200, r.text


def test_policy_is_strictly_tenant_scoped(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Tenant A: PNG only.
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
    assert r.json()["tenant_id"] == "tenant-b"
    assert r.json()["types"] == []
    assert r.json()["enforced"] is False

    # Tenant B can still upload JPEG (tenant A's policy does not leak).
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-b"),
        files={"file": ("a.jpg", _jpeg(), "image/jpeg")},
    )
    assert r.status_code == 200, r.text

    # And tenant A is still blocked on the same payload.
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-a"),
        files={"file": ("a.jpg", _jpeg(), "image/jpeg")},
    )
    assert r.status_code == 415, r.text


def test_batch_classify_honours_policy(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/upload-content-types",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"types": ["image/png"]},
    )
    assert r.status_code == 200, r.text

    # Mixed batch: one PNG (ok), one JPEG (blocked). Whole batch must
    # 415 because any disallowed entry trips the gate before any work.
    r = c.post(
        "/v1/classify/batch",
        headers=_hdr("admin-a"),
        files=[
            ("files", ("a.png", _png(), "image/png")),
            ("files", ("b.jpg", _jpeg(), "image/jpeg")),
        ],
    )
    assert r.status_code == 415, r.text


def test_set_rejects_invalid_and_oversize_lists(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Not a list.
    r = c.put(
        "/v1/settings/security/upload-content-types",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"types": "image/png"},
    )
    assert r.status_code == 422, r.text
    # Missing field.
    r = c.put(
        "/v1/settings/security/upload-content-types",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={},
    )
    assert r.status_code == 422, r.text
    # Invalid MIME.
    r = c.put(
        "/v1/settings/security/upload-content-types",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"types": ["not a mime"]},
    )
    assert r.status_code == 422, r.text
    # Over the cap.
    r = c.put(
        "/v1/settings/security/upload-content-types",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"types": [f"image/x-{i}" for i in range(64)]},
    )
    assert r.status_code == 422, r.text


def test_clear_policy_restores_legacy_behaviour(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Set then clear.
    r = c.put(
        "/v1/settings/security/upload-content-types",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"types": ["image/png"]},
    )
    assert r.status_code == 200, r.text
    r = c.put(
        "/v1/settings/security/upload-content-types",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"types": None},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["types"] == []
    assert body["enforced"] is False

    # JPEG accepted again (legacy any-image gate).
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-a"),
        files={"file": ("a.jpg", _jpeg(), "image/jpeg")},
    )
    assert r.status_code == 200, r.text
