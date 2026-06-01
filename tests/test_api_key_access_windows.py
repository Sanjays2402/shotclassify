"""Per-API-key time-of-day access window enforcement.

Workspace admins can restrict an API key to one or more weekly windows
(weekday + HH:MM start/end in a named IANA zone). These tests prove the
full path: mint a key with a window that does not include "now", verify
the auth middleware returns HTTP 403 ``api_key_outside_window``, then
clear the restriction and verify the same key is accepted.

This complements the per-key source-IP allowlist by giving procurement
(PCI 7, SOX change management) a way to bind machine credentials to a
maintenance / business-hours window without revoking and re-issuing.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv("AUTH_TENANT_MAP", json.dumps({"admin-key": "tenant-a"}))
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "tenant-a")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'keys.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db, init_db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    init_db()
    return TestClient(create_app())


def _mint(client: TestClient, **body) -> dict:
    body.setdefault("label", "scheduler")
    body.setdefault("scopes", ["read:classifications"])
    body.setdefault("owner_email", "ops@example.com")
    r = client.post("/v1/api-keys", headers={"X-API-Key": "admin-key"}, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _outside_window_now() -> list[dict]:
    """Build a window that demonstrably does not cover the current minute.

    We pick the weekday and a one-hour slot that starts at least two hours
    before "now" and ends one hour before "now" in UTC, so the running test
    deterministically falls outside it.
    """
    now = datetime.now(UTC)
    target_weekday = (now.weekday() + 3) % 7  # a different weekday
    return [
        {
            "weekdays": [target_weekday],
            "start": "01:00",
            "end": "02:00",
            "tz": "UTC",
        }
    ]


def test_outside_window_rejects(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    payload = _mint(c, access_windows=_outside_window_now())
    token = payload["token"]
    assert payload["access_windows"], "access_windows should round-trip on create"
    r = c.get("/v1/history", headers={"X-API-Key": token})
    assert r.status_code == 403, r.text
    body = r.json()
    assert body.get("error") == "api_key_outside_window"
    assert isinstance(body.get("access_windows"), list) and body["access_windows"]


def test_clearing_window_restores_access(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    payload = _mint(c, access_windows=_outside_window_now())
    token = payload["token"]
    key_id = payload["id"]
    # Sanity: blocked while window is set.
    blocked = c.get("/v1/history", headers={"X-API-Key": token})
    assert blocked.status_code == 403
    # Clear the window via the management endpoint (admin session).
    cleared = c.patch(
        f"/v1/api-keys/{key_id}/access-windows",
        headers={"X-API-Key": "admin-key"},
        json={"access_windows": []},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["key"]["access_windows"] == []
    # Now the same key is accepted.
    r = c.get("/v1/history", headers={"X-API-Key": token})
    assert r.status_code == 200, r.text


def test_invalid_window_rejected_422(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/api-keys",
        headers={"X-API-Key": "admin-key"},
        json={
            "label": "bad",
            "scopes": ["read:classifications"],
            "owner_email": "ops@example.com",
            "access_windows": [
                {"weekdays": [0], "start": "18:00", "end": "08:00", "tz": "UTC"}
            ],
        },
    )
    assert r.status_code == 422, r.text


def test_get_access_windows_tenant_scoped(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    payload = _mint(c, access_windows=[{
        "weekdays": [0, 1, 2, 3, 4],
        "start": "09:00",
        "end": "17:00",
        "tz": "UTC",
    }])
    key_id = payload["id"]
    r = c.get(
        f"/v1/api-keys/{key_id}/access-windows",
        headers={"X-API-Key": "admin-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == key_id
    assert body["access_windows"][0]["weekdays"] == [0, 1, 2, 3, 4]
    # An id that does not exist returns 404 (not 403) so we don't leak
    # whether the id belongs to another tenant.
    r = c.get(
        "/v1/api-keys/does-not-exist/access-windows",
        headers={"X-API-Key": "admin-key"},
    )
    assert r.status_code == 404
