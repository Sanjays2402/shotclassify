"""Pause/resume tests for webhook subscriptions.

Pausing is operationally distinct from revoking: the subscription, its
signing secret, and its delivery history all survive. Dispatch must skip
paused subscriptions. Cross-tenant pause/resume must be impossible.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv("WEBHOOK_EGRESS_ALLOW_HTTP", "true")
    monkeypatch.setenv("WEBHOOK_EGRESS_ALLOW_PRIVATE", "true")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps(
            {
                "acme-admin-key": "admin",
                "acme-op-key": "operator",
                "globex-admin-key": "admin",
            }
        ),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps(
            {
                "acme-admin-key": "acme",
                "acme-op-key": "acme",
                "globex-admin-key": "globex",
            }
        ),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "default")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'pause.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("MFA_REQUIRED_FOR_ADMIN", "false")
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()

    from services.api.app.main import create_app

    return TestClient(create_app())


def _admin(t: str) -> dict[str, str]:
    return {"X-API-Key": f"{t}-admin-key"}


def _create(c: TestClient, tenant: str, url: str = "http://example.com/h") -> str:
    r = c.post(
        "/v1/webhooks",
        headers=_admin(tenant),
        json={"url": url, "events": ["classify.completed"], "description": "d"},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["webhook"]["id"]


def test_pause_then_resume_round_trip(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    wid = _create(c, "acme")

    # Initial state is active.
    listed = c.get("/v1/webhooks", headers=_admin("acme")).json()["webhooks"]
    assert listed[0]["status"] == "active"
    assert listed[0]["active"] is True

    # Pause.
    r = c.post(f"/v1/webhooks/{wid}/pause", headers=_admin("acme"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["webhook"]["status"] == "paused"
    assert body["webhook"]["active"] is False
    assert body["webhook"]["revoked_at"] is None

    # Dispatch must skip paused subscriptions.
    from shotclassify_store import webhooks_store

    results = webhooks_store.dispatch_event(
        tenant_id="acme",
        event="classify.completed",
        payload={"id": "x"},
        sleep=lambda *_: None,
    )
    assert results == []

    # Double-pause is a 409.
    r = c.post(f"/v1/webhooks/{wid}/pause", headers=_admin("acme"))
    assert r.status_code == 409

    # Resume.
    r = c.post(f"/v1/webhooks/{wid}/resume", headers=_admin("acme"))
    assert r.status_code == 200
    assert r.json()["webhook"]["status"] == "active"

    # Double-resume is a 409.
    r = c.post(f"/v1/webhooks/{wid}/resume", headers=_admin("acme"))
    assert r.status_code == 409


def test_revoked_subscription_cannot_be_resumed(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    wid = _create(c, "acme")
    assert c.delete(f"/v1/webhooks/{wid}", headers=_admin("acme")).status_code == 200
    r = c.post(f"/v1/webhooks/{wid}/resume", headers=_admin("acme"))
    assert r.status_code == 410
    r = c.post(f"/v1/webhooks/{wid}/pause", headers=_admin("acme"))
    assert r.status_code == 410


def test_pause_dry_run_does_not_change_state(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    wid = _create(c, "acme")
    r = c.post(f"/v1/webhooks/{wid}/pause?dry_run=true", headers=_admin("acme"))
    assert r.status_code == 200
    body = r.json()
    assert body.get("dry_run") is True
    assert body["would_set"]["from_status"] == "active"
    assert body["would_set"]["to_status"] == "paused"
    # State unchanged.
    listed = c.get("/v1/webhooks", headers=_admin("acme")).json()["webhooks"]
    assert listed[0]["status"] == "active"


def test_cross_tenant_pause_is_blocked(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    acme_id = _create(c, "acme")
    # globex admin cannot see or pause acme's subscription.
    r = c.post(f"/v1/webhooks/{acme_id}/pause", headers=_admin("globex"))
    assert r.status_code == 404
    r = c.post(f"/v1/webhooks/{acme_id}/resume", headers=_admin("globex"))
    assert r.status_code == 404
    # acme's own subscription is untouched.
    listed = c.get("/v1/webhooks", headers=_admin("acme")).json()["webhooks"]
    assert listed[0]["status"] == "active"


def test_operator_cannot_pause(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    wid = _create(c, "acme")
    r = c.post(
        f"/v1/webhooks/{wid}/pause",
        headers={"X-API-Key": "acme-op-key"},
    )
    assert r.status_code == 403
