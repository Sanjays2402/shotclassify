"""Per-API-key monthly call quota enforcement.

Workspace admins can cap the total number of calls a single API key may
make within a UTC calendar month. The rate limit middleware atomically
charges a counter on every authenticated request and returns HTTP 429
with ``X-RateLimit-Scope: api_key_month`` and a ``Retry-After`` pointing
at the next month boundary once the cap is reached. NULL quota preserves
the legacy unlimited behaviour so existing keys are unaffected.

These tests exercise the full path: mint a key with a quota, burn through
it, verify the 429 carries the required headers, verify a sibling key in
the same tenant is unaffected, and verify clearing the quota immediately
restores access.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv("AUTH_TENANT_MAP", json.dumps({"admin-key": "tenant-a"}))
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "tenant-a")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'mq.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    # Generous bucket so the per-minute limiter never trips during the
    # 5-request burn-through; we are testing the monthly cap, not RPM.
    monkeypatch.setenv("RATE_LIMIT_PER_KEY_RPM", "10000")
    monkeypatch.setenv("RATE_LIMIT_PER_WORKSPACE_RPM", "10000")
    monkeypatch.setenv("RATE_LIMIT_PER_IP_RPM", "10000")
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


def _mint(client: TestClient, **body) -> dict:
    body.setdefault("label", "ci")
    body.setdefault("scopes", ["read:classifications"])
    r = client.post("/v1/api-keys", headers={"X-API-Key": "admin-key"}, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _hit(client: TestClient, token: str):
    return client.get("/v1/history", headers={"X-API-Key": token})


def test_monthly_quota_returns_429_with_standard_headers(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    minted = _mint(c, monthly_quota=3)
    token = minted["token"]
    assert minted["monthly_quota"] == 3

    # Three calls succeed.
    for i in range(3):
        r = _hit(c, token)
        assert r.status_code == 200, f"call {i} expected 200, got {r.status_code}"

    # Fourth call hits the monthly cap.
    r = _hit(c, token)
    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "monthly_quota_exceeded"
    assert r.headers["X-RateLimit-Scope"] == "api_key_month"
    assert r.headers["X-RateLimit-Limit"] == "3"
    assert r.headers["X-RateLimit-Remaining"] == "0"
    retry_after = int(r.headers["Retry-After"])
    assert retry_after >= 1
    # Reset header should agree with Retry-After (seconds until next UTC month).
    assert int(r.headers["X-RateLimit-Reset"]) == retry_after


def test_monthly_quota_is_per_key_not_per_tenant(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    capped = _mint(c, label="capped", monthly_quota=1)
    sibling = _mint(c, label="sibling")

    # Burn the capped key.
    assert _hit(c, capped["token"]).status_code == 200
    assert _hit(c, capped["token"]).status_code == 429

    # Sibling key in the same tenant must still work; the cap is per-key,
    # not per-tenant, so noisy neighbours cannot starve quiet ones.
    assert _hit(c, sibling["token"]).status_code == 200
    assert _hit(c, sibling["token"]).status_code == 200


def test_clearing_quota_restores_access(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    minted = _mint(c, monthly_quota=1)
    token = minted["token"]
    key_id = minted["id"]

    assert _hit(c, token).status_code == 200
    assert _hit(c, token).status_code == 429

    # Admin lifts the cap; the very next call succeeds without waiting.
    r = c.patch(
        f"/v1/api-keys/{key_id}/monthly-quota",
        headers={"X-API-Key": "admin-key"},
        json={"quota": None},
    )
    assert r.status_code == 200, r.text
    assert r.json()["key"]["monthly_quota"] is None
    assert _hit(c, token).status_code == 200


def test_monthly_usage_endpoint_reports_counter(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    minted = _mint(c, monthly_quota=10)
    token = minted["token"]
    key_id = minted["id"]

    for _ in range(4):
        assert _hit(c, token).status_code == 200

    r = c.get(
        f"/v1/api-keys/{key_id}/monthly-usage",
        headers={"X-API-Key": "admin-key"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["monthly_quota"] == 10
    assert body["monthly_usage"] == 4
    assert body["remaining"] == 6
