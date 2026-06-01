"""Auto-disable circuit-breaker tests for outbound webhooks.

Per-tenant policy ``webhook_autodisable_threshold`` pauses a subscription
after N consecutive failed deliveries so the dispatcher stops hammering a
downstream receiver that is clearly down. The signing secret and delivery
history survive (pause, not revoke) so an operator can resume once the
receiver is healthy.

These tests exercise the breaker end-to-end through the public HTTP API
and prove three properties enterprise procurement asks about:

* The breaker fires only after the configured threshold is reached.
* Tenants cannot read or write each other's policy.
* Resuming a paused subscription clears the auto-disable metadata and
  the consecutive-failure counter (clean state for the next trip).
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
                "globex-admin-key": "admin",
            }
        ),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps(
            {
                "acme-admin-key": "acme",
                "globex-admin-key": "globex",
            }
        ),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "default")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'autodis.db'}")
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


def _record_failure(tenant_id: str, sub_id: str) -> None:
    """Simulate one failed delivery by going through the dispatch helper."""
    from shotclassify_store import webhooks as wh

    wh._record_delivery(
        tenant_id=tenant_id,
        subscription_id=sub_id,
        event="classify.completed",
        url="http://example.com/h",
        status="failed",
        attempt=4,
        http_status=503,
        error="HTTP 503",
        latency_ms=12,
        payload_preview="{}",
        signature="sig",
        request_id=None,
    )


def _record_success(tenant_id: str, sub_id: str) -> None:
    from shotclassify_store import webhooks as wh

    wh._record_delivery(
        tenant_id=tenant_id,
        subscription_id=sub_id,
        event="classify.completed",
        url="http://example.com/h",
        status="success",
        attempt=1,
        http_status=200,
        error=None,
        latency_ms=5,
        payload_preview="{}",
        signature="sig",
        request_id=None,
    )


def test_threshold_pauses_after_n_consecutive_failures(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    # Configure a tight threshold (3) for acme.
    r = c.put(
        "/v1/settings/security/webhook-autodisable",
        headers=_admin("acme"),
        json={"threshold": 3},
    )
    assert r.status_code == 200, r.text
    assert r.json()["threshold"] == 3

    # Create a subscription.
    r = c.post(
        "/v1/webhooks",
        headers=_admin("acme"),
        json={"url": "http://example.com/h", "events": ["classify.completed"]},
    )
    assert r.status_code in (200, 201), r.text
    wid = r.json()["webhook"]["id"]

    # Two failures: still active, counter advances.
    _record_failure("acme", wid)
    _record_failure("acme", wid)
    listed = c.get("/v1/webhooks", headers=_admin("acme")).json()["webhooks"]
    sub = next(s for s in listed if s["id"] == wid)
    assert sub["status"] == "active"
    assert sub["consecutive_failure_count"] == 2
    assert sub["auto_disabled_at"] is None

    # Third failure trips the breaker.
    _record_failure("acme", wid)
    listed = c.get("/v1/webhooks", headers=_admin("acme")).json()["webhooks"]
    sub = next(s for s in listed if s["id"] == wid)
    assert sub["status"] == "paused"
    assert sub["consecutive_failure_count"] == 3
    assert sub["auto_disabled_at"] is not None
    assert "consecutive" in (sub["auto_disabled_reason"] or "").lower()


def test_success_resets_counter_before_threshold(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.put(
        "/v1/settings/security/webhook-autodisable",
        headers=_admin("acme"),
        json={"threshold": 3},
    )
    r = c.post(
        "/v1/webhooks",
        headers=_admin("acme"),
        json={"url": "http://example.com/h", "events": ["*"]},
    )
    wid = r.json()["webhook"]["id"]

    _record_failure("acme", wid)
    _record_failure("acme", wid)
    _record_success("acme", wid)
    _record_failure("acme", wid)
    _record_failure("acme", wid)

    listed = c.get("/v1/webhooks", headers=_admin("acme")).json()["webhooks"]
    sub = next(s for s in listed if s["id"] == wid)
    # Two consecutive failures after the success: breaker has NOT tripped.
    assert sub["status"] == "active"
    assert sub["consecutive_failure_count"] == 2


def test_resume_clears_autodisable_state(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.put(
        "/v1/settings/security/webhook-autodisable",
        headers=_admin("acme"),
        json={"threshold": 2},
    )
    r = c.post(
        "/v1/webhooks",
        headers=_admin("acme"),
        json={"url": "http://example.com/h", "events": ["*"]},
    )
    wid = r.json()["webhook"]["id"]

    _record_failure("acme", wid)
    _record_failure("acme", wid)
    sub = next(
        s for s in c.get("/v1/webhooks", headers=_admin("acme")).json()["webhooks"]
        if s["id"] == wid
    )
    assert sub["status"] == "paused"
    assert sub["auto_disabled_at"] is not None

    # Resume.
    r = c.post(f"/v1/webhooks/{wid}/resume", headers=_admin("acme"))
    assert r.status_code == 200, r.text
    sub = next(
        s for s in c.get("/v1/webhooks", headers=_admin("acme")).json()["webhooks"]
        if s["id"] == wid
    )
    assert sub["status"] == "active"
    assert sub["auto_disabled_at"] is None
    assert sub["auto_disabled_reason"] is None
    assert sub["consecutive_failure_count"] == 0


def test_cross_tenant_isolation_of_policy_and_breaker(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    # acme sets a policy; globex must not see it.
    c.put(
        "/v1/settings/security/webhook-autodisable",
        headers=_admin("acme"),
        json={"threshold": 3},
    )
    g = c.get("/v1/settings/security/webhook-autodisable", headers=_admin("globex")).json()
    assert g["threshold"] is None
    assert g["tenant_id"] == "globex"

    # globex creates a subscription and racks up failures; with no policy
    # the breaker must NOT trip.
    r = c.post(
        "/v1/webhooks",
        headers=_admin("globex"),
        json={"url": "http://example.com/h", "events": ["*"]},
    )
    gwid = r.json()["webhook"]["id"]
    for _ in range(10):
        _record_failure("globex", gwid)
    sub = next(
        s for s in c.get("/v1/webhooks", headers=_admin("globex")).json()["webhooks"]
        if s["id"] == gwid
    )
    assert sub["status"] == "active"
    assert sub["consecutive_failure_count"] == 10
    assert sub["auto_disabled_at"] is None


def test_threshold_validation_bounds(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Below minimum.
    r = c.put(
        "/v1/settings/security/webhook-autodisable",
        headers=_admin("acme"),
        json={"threshold": 1},
    )
    assert r.status_code == 422
    # Wrong type.
    r = c.put(
        "/v1/settings/security/webhook-autodisable",
        headers=_admin("acme"),
        json={"threshold": "many"},
    )
    assert r.status_code == 422
    # Missing field.
    r = c.put(
        "/v1/settings/security/webhook-autodisable",
        headers=_admin("acme"),
        json={},
    )
    assert r.status_code == 422
    # Null clears policy.
    r = c.put(
        "/v1/settings/security/webhook-autodisable",
        headers=_admin("acme"),
        json={"threshold": None},
    )
    assert r.status_code == 200
    assert r.json()["threshold"] is None
