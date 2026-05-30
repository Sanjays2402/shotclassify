"""RBAC: per-route role enforcement.

The default ``AUTH_API_KEY`` is treated as ``admin``. Additional keys are
provisioned via ``AUTH_API_KEYS`` (JSON ``{key: role}``). Routes declare a
minimum role through ``require_role``; lower-privilege callers see HTTP 403,
unauthenticated callers see 401.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path, extra_env: dict[str, str] | None = None):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps({"op-key": "operator", "view-key": "viewer"}),
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'rbac.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))
    if extra_env:
        for k, v in extra_env.items():
            monkeypatch.setenv(k, v)

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def test_unknown_api_key_is_unauthorized(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/v1/history", headers={"X-API-Key": "nope"}).status_code == 401


def test_viewer_can_read_history(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/v1/history", headers={"X-API-Key": "view-key"}).status_code == 200


def test_viewer_cannot_delete_history(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.delete("/v1/history/abc", headers={"X-API-Key": "view-key"})
    assert r.status_code == 403
    assert "operator" in r.json()["detail"]


def test_viewer_cannot_read_settings(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/settings/rules", headers={"X-API-Key": "view-key"})
    assert r.status_code == 403


def test_operator_can_read_but_not_write_settings(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/v1/settings/rules", headers={"X-API-Key": "op-key"}).status_code == 200
    r = c.put(
        "/v1/settings/rules",
        json={"yaml": "defaults: {dry_run: true}\nrules: []\n"},
        headers={"X-API-Key": "op-key"},
    )
    assert r.status_code == 403


def test_admin_can_write_settings(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/rules",
        json={"yaml": "defaults: {dry_run: true}\nrules: []\n"},
        headers={"X-API-Key": "admin-key"},
    )
    assert r.status_code == 200


def test_audit_requires_admin(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/v1/audit", headers={"X-API-Key": "op-key"}).status_code == 403
    assert c.get("/v1/audit", headers={"X-API-Key": "view-key"}).status_code == 403
    assert c.get("/v1/audit", headers={"X-API-Key": "admin-key"}).status_code == 200


def test_viewer_cannot_classify(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    files = {"file": ("x.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    r = c.post("/v1/classify", files=files, headers={"X-API-Key": "view-key"})
    assert r.status_code == 403


def test_gdpr_endpoint_open_to_any_authenticated_role(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Viewer should still be able to export their own data.
    r = c.get("/v1/me/data", headers={"X-API-Key": "view-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["principal"] == "api-key"


def test_malformed_auth_api_keys_does_not_crash(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, extra_env={"AUTH_API_KEYS": "not-json{"})
    # Admin key still works; the bad JSON is ignored.
    assert c.get("/v1/audit", headers={"X-API-Key": "admin-key"}).status_code == 200
    assert c.get("/v1/audit", headers={"X-API-Key": "view-key"}).status_code == 401
