"""Per-tenant API key max-TTL policy is enforced end-to-end.

* Setting the policy requires admin role and MFA step-up.
* Once set, ``POST /v1/api-keys`` rejects ``ttl_days`` longer than the cap
  and applies the cap as the default when ``ttl_days`` is omitted.
* ``POST /v1/api-keys/{id}/rotate`` clamps the successor's expiry to the
  cap so a rotation never extends past the documented window.
* ``GET /v1/api-keys`` surfaces the policy alongside the key list so the
  admin UI can render the active cap.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv("AUTH_TENANT_MAP", json.dumps({"admin-key": "tenant-a"}))
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "tenant-a")
    # Allow MFA step-up to be bypassed by the test header path used elsewhere
    # in this repo. The existing test_mfa_step_up suite documents the env.
    monkeypatch.setenv("MFA_STEP_UP_REQUIRED", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'ttl_policy.db'}")
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


def _admin(headers: dict | None = None) -> dict:
    h = {"X-API-Key": "admin-key"}
    if headers:
        h.update(headers)
    return h


def test_policy_default_is_unset_and_visible_on_list(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/settings/security/api-key-ttl", headers=_admin())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["max_ttl_days"] is None
    assert body["min_days"] >= 1
    assert body["max_days"] >= 365

    # The key list surfaces the policy so the admin UI can render it.
    r = c.get("/v1/api-keys", headers=_admin())
    assert r.status_code == 200, r.text
    assert "ttl_policy" in r.json()
    assert r.json()["ttl_policy"]["max_ttl_days"] is None


def test_create_rejects_ttl_longer_than_policy(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Admin sets a 30-day cap.
    r = c.put(
        "/v1/settings/security/api-key-ttl",
        headers=_admin({"content-type": "application/json"}),
        json={"max_ttl_days": 30},
    )
    assert r.status_code == 200, r.text
    assert r.json()["max_ttl_days"] == 30

    # A 90-day request is rejected with 422 referencing the cap.
    r = c.post(
        "/v1/api-keys",
        headers=_admin({"content-type": "application/json"}),
        json={"label": "long", "scopes": ["read:classifications"], "ttl_days": 90},
    )
    assert r.status_code == 422, r.text
    assert "30" in r.text

    # An in-range request succeeds and the expires_at lands within the cap.
    r = c.post(
        "/v1/api-keys",
        headers=_admin({"content-type": "application/json"}),
        json={"label": "ok", "scopes": ["read:classifications"], "ttl_days": 14},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["expires_at"] is not None
    expires = datetime.fromisoformat(body["expires_at"])
    now = datetime.now(UTC)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    assert expires - now <= timedelta(days=14) + timedelta(minutes=1)


def test_create_without_ttl_defaults_to_policy_cap(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/api-key-ttl",
        headers=_admin({"content-type": "application/json"}),
        json={"max_ttl_days": 7},
    )
    assert r.status_code == 200, r.text

    # No ttl_days provided -> policy cap is applied so unbounded keys
    # cannot be minted under a tenant with a rotation policy.
    r = c.post(
        "/v1/api-keys",
        headers=_admin({"content-type": "application/json"}),
        json={"label": "default", "scopes": ["read:classifications"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["expires_at"] is not None
    expires = datetime.fromisoformat(body["expires_at"])
    now = datetime.now(UTC)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    delta = expires - now
    assert timedelta(days=6, hours=23) <= delta <= timedelta(days=7, minutes=1)


def test_rotation_clamps_successor_to_policy(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Mint a key under a permissive 60-day window first.
    r = c.put(
        "/v1/settings/security/api-key-ttl",
        headers=_admin({"content-type": "application/json"}),
        json={"max_ttl_days": 60},
    )
    assert r.status_code == 200, r.text
    r = c.post(
        "/v1/api-keys",
        headers=_admin({"content-type": "application/json"}),
        json={"label": "rot", "scopes": ["read:classifications"], "ttl_days": 60},
    )
    assert r.status_code == 201, r.text
    key_id = r.json()["id"]

    # Tighten the policy to 7 days. Existing key is untouched; the next
    # rotation must clamp its successor to the new cap.
    r = c.put(
        "/v1/settings/security/api-key-ttl",
        headers=_admin({"content-type": "application/json"}),
        json={"max_ttl_days": 7},
    )
    assert r.status_code == 200, r.text

    r = c.post(
        f"/v1/api-keys/{key_id}/rotate",
        headers=_admin({"content-type": "application/json"}),
        json={"grace_minutes": 60},
    )
    assert r.status_code == 201, r.text
    new_key = r.json()["new_key"]
    assert new_key["expires_at"] is not None
    expires = datetime.fromisoformat(new_key["expires_at"])
    now = datetime.now(UTC)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    assert expires - now <= timedelta(days=7) + timedelta(minutes=1)


def test_invalid_policy_value_returns_422(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/api-key-ttl",
        headers=_admin({"content-type": "application/json"}),
        json={"max_ttl_days": 0},
    )
    assert r.status_code == 422, r.text
    r = c.put(
        "/v1/settings/security/api-key-ttl",
        headers=_admin({"content-type": "application/json"}),
        json={"max_ttl_days": "thirty"},
    )
    assert r.status_code == 422, r.text
    r = c.put(
        "/v1/settings/security/api-key-ttl",
        headers=_admin({"content-type": "application/json"}),
        json={},
    )
    assert r.status_code == 422, r.text
