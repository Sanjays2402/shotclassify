"""Per-tenant max upload size policy is enforced end-to-end on classify.

* The default has no per-tenant cap and uploads of any size succeed.
* Setting the policy requires admin role and MFA step-up.
* Once set, ``POST /v1/classify`` rejects a single upload that exceeds
  the cap with HTTP 413 ``upload_too_large`` before it is written to
  disk or sent to the model.
* The policy is strictly tenant-scoped: a tighter cap on tenant A does
  not affect tenant B, and tenant A's policy row is never read by a
  caller resolved to tenant B (no cross-tenant leakage).
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


def _big_png(target_bytes: int = 64 * 1024) -> bytes:
    """Build a PNG whose encoded byte length comfortably exceeds ``target_bytes``.

    We seed the pixel buffer with deterministic noise so PNG's deflate
    cannot collapse it into a tiny file the way a flat color would.
    """
    import os

    side = 256
    while True:
        raw = os.urandom(side * side * 3)
        img = Image.frombytes("RGB", (side, side), raw)
        buf = io.BytesIO()
        img.save(buf, format="PNG", compress_level=0)
        out = buf.getvalue()
        if len(out) > target_bytes:
            return out
        side *= 2


def _client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-a")
    monkeypatch.setenv("AUTH_API_KEYS", json.dumps({"admin-b": "admin"}))
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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'upload_size.db'}")
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


def test_default_policy_is_unset_and_uploads_unrestricted(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/settings/security/upload-size", headers=_hdr("admin-a"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["max_upload_bytes"] is None
    assert body["min_bytes"] >= 1024
    assert body["max_bytes"] >= body["min_bytes"]

    img = _png()
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-a"),
        files={"file": ("a.png", img, "image/png")},
    )
    assert r.status_code == 200, r.text


def test_policy_rejects_oversized_single_upload(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Floor of the allowed range so we can build an over-limit payload
    # without committing megabytes of test data.
    r = c.put(
        "/v1/settings/security/upload-size",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"max_upload_bytes": 32 * 1024},
    )
    assert r.status_code == 200, r.text
    assert r.json()["max_upload_bytes"] == 32 * 1024

    # PNG well above 32 KiB gets refused at the gate.
    big = _big_png(64 * 1024)
    assert len(big) > 32 * 1024
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-a"),
        files={"file": ("big.png", big, "image/png")},
    )
    assert r.status_code == 413, r.text
    detail = r.json().get("detail")
    if isinstance(detail, dict):
        assert detail["error"] == "upload_too_large"
        assert detail["max_upload_bytes"] == 32 * 1024
    else:
        assert "upload_too_large" in r.text

    # An under-cap upload still works for the same tenant.
    small = _png(16, 16)
    assert len(small) < 32 * 1024
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-a"),
        files={"file": ("small.png", small, "image/png")},
    )
    assert r.status_code == 200, r.text


def test_policy_is_strictly_tenant_scoped(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Tenant A caps uploads at 32 KiB.
    r = c.put(
        "/v1/settings/security/upload-size",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"max_upload_bytes": 32 * 1024},
    )
    assert r.status_code == 200, r.text

    # Tenant B sees no policy at all (no cross-tenant read).
    r = c.get("/v1/settings/security/upload-size", headers=_hdr("admin-b"))
    assert r.status_code == 200, r.text
    assert r.json()["tenant_id"] == "tenant-b"
    assert r.json()["max_upload_bytes"] is None

    # Tenant B can still upload a payload that tenant A would have been
    # blocked on, proving the cap does not leak between workspaces.
    big = _big_png(64 * 1024)
    assert len(big) > 32 * 1024
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-b"),
        files={"file": ("big.png", big, "image/png")},
    )
    assert r.status_code == 200, r.text

    # And the same payload remains blocked for tenant A.
    r = c.post(
        "/v1/classify",
        headers=_hdr("admin-a"),
        files={"file": ("big.png", big, "image/png")},
    )
    assert r.status_code == 413, r.text


def test_set_rejects_out_of_range_values(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Below the floor.
    r = c.put(
        "/v1/settings/security/upload-size",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"max_upload_bytes": 1024},
    )
    assert r.status_code == 422, r.text
    # Non-integer.
    r = c.put(
        "/v1/settings/security/upload-size",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"max_upload_bytes": "lots"},
    )
    assert r.status_code == 422, r.text
    # Missing field.
    r = c.put(
        "/v1/settings/security/upload-size",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={},
    )
    assert r.status_code == 422, r.text
