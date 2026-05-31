"""Tests for the security incident registry and per-tenant notification
subscriptions.

Covers:
* the public incidents feed is reachable without credentials
* cross-tenant isolation: tenant A cannot list, mutate, or delete a
  subscription owned by tenant B
* RBAC: a non-admin (operator) principal is rejected from the mutating
  routes
* validation: bad channel + endpoint combinations are rejected with 409
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
        json.dumps(
            {
                "acme-admin-key": "admin",
                "globex-admin-key": "admin",
                "acme-op-key": "operator",
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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'incidents.db'}")
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


def _h(key: str) -> dict:
    return {"x-api-key": key}


def test_public_incidents_feed_no_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/trust/incidents")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and isinstance(body["items"], list)
    assert "low" in body["valid_severities"]


def test_create_and_list_subscription_admin(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/incident-subscriptions",
        headers=_h("acme-admin-key"),
        json={
            "channel": "email",
            "endpoint": "security@acme.example",
            "severity_min": "high",
            "label": "SecOps",
        },
    )
    assert r.status_code == 201, r.text
    sub = r.json()["subscription"]
    assert sub["channel"] == "email"
    assert sub["severity_min"] == "high"
    assert sub["active"] is True

    r2 = c.get("/v1/incident-subscriptions", headers=_h("acme-admin-key"))
    assert r2.status_code == 200
    items = r2.json()["items"]
    assert len(items) == 1 and items[0]["id"] == sub["id"]


def test_operator_role_blocked_from_mutating(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/incident-subscriptions",
        headers=_h("acme-op-key"),
        json={"channel": "email", "endpoint": "ops@acme.example"},
    )
    assert r.status_code == 403, r.text
    r2 = c.get("/v1/incident-subscriptions", headers=_h("acme-op-key"))
    assert r2.status_code == 403


def test_cross_tenant_isolation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Acme creates one
    r = c.post(
        "/v1/incident-subscriptions",
        headers=_h("acme-admin-key"),
        json={"channel": "email", "endpoint": "a@acme.example"},
    )
    assert r.status_code == 201
    sub_id = r.json()["subscription"]["id"]

    # Globex creates its own
    r = c.post(
        "/v1/incident-subscriptions",
        headers=_h("globex-admin-key"),
        json={"channel": "webhook", "endpoint": "https://hooks.globex.example/sec"},
    )
    assert r.status_code == 201

    # Globex cannot see acme's subscription in its list.
    r = c.get("/v1/incident-subscriptions", headers=_h("globex-admin-key"))
    assert r.status_code == 200
    globex_ids = {s["id"] for s in r.json()["items"]}
    assert sub_id not in globex_ids
    assert len(globex_ids) == 1

    # Globex cannot patch acme's subscription.
    r = c.patch(
        f"/v1/incident-subscriptions/{sub_id}",
        headers=_h("globex-admin-key"),
        json={"active": False},
    )
    assert r.status_code == 404, r.text

    # Globex cannot delete acme's subscription.
    r = c.delete(
        f"/v1/incident-subscriptions/{sub_id}",
        headers=_h("globex-admin-key"),
    )
    assert r.status_code == 404, r.text

    # Acme can still see and delete its own.
    r = c.get("/v1/incident-subscriptions", headers=_h("acme-admin-key"))
    assert {s["id"] for s in r.json()["items"]} == {sub_id}
    r = c.delete(
        f"/v1/incident-subscriptions/{sub_id}",
        headers=_h("acme-admin-key"),
    )
    assert r.status_code == 200


def test_validation_rejects_bad_inputs(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # bad channel
    r = c.post(
        "/v1/incident-subscriptions",
        headers=_h("acme-admin-key"),
        json={"channel": "carrier-pigeon", "endpoint": "x@y.com"},
    )
    assert r.status_code == 409
    # bad email
    r = c.post(
        "/v1/incident-subscriptions",
        headers=_h("acme-admin-key"),
        json={"channel": "email", "endpoint": "not-an-email"},
    )
    assert r.status_code == 409
    # bad webhook scheme
    r = c.post(
        "/v1/incident-subscriptions",
        headers=_h("acme-admin-key"),
        json={"channel": "webhook", "endpoint": "ftp://nope.example/"},
    )
    assert r.status_code == 409
    # duplicate
    ok = c.post(
        "/v1/incident-subscriptions",
        headers=_h("acme-admin-key"),
        json={"channel": "email", "endpoint": "dup@acme.example"},
    )
    assert ok.status_code == 201
    dup = c.post(
        "/v1/incident-subscriptions",
        headers=_h("acme-admin-key"),
        json={"channel": "email", "endpoint": "dup@acme.example"},
    )
    assert dup.status_code == 409
