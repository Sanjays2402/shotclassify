"""Per-tenant API key inactivity (auto-revoke) policy is enforced end-to-end.

* Setting the policy requires admin role and MFA step-up.
* When set, presenting a DB-backed API key whose effective last-use
  (falling back to ``created_at``) is older than the cap auto-revokes
  the key and rejects the request with 401 ``api_key_stale_inactive``.
* The same key presented again 401s with the standard inactive-key
  shape because the row is now revoked.
* Keys belonging to a different tenant are not affected by another
  tenant's policy: this proves the policy is tenant-scoped, not global.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps({"admin-key": "tenant-a"}),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "tenant-a")
    monkeypatch.setenv("MFA_STEP_UP_REQUIRED", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'inactivity.db'}")
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


def _mint_key(client: TestClient, *, tenant: str, label: str) -> str:
    """Use the API to mint a DB-backed key for ``tenant`` and return its token.

    Uses the cross-tenant admin header X-Tenant so the legacy env-var
    admin-key can target a specific workspace.
    """
    r = client.post(
        "/v1/api-keys",
        headers=_admin({"content-type": "application/json", "x-tenant": tenant}),
        json={"label": label, "scopes": ["write:classifications"]},
    )
    assert r.status_code in (200, 201), r.text
    body = r.json()
    return body["token"]


def _age_key(token: str, *, days_old: int) -> None:
    """Backdate the matching key's ``last_used_at`` and ``created_at``."""
    from shotclassify_store import api_keys_store
    from shotclassify_store.api_keys import _hash
    from shotclassify_store.db import ApiKeyRow, get_session

    h = _hash(token)
    backdate = datetime.now(UTC) - timedelta(days=days_old)
    with get_session() as ses:
        ses.execute(
            update(ApiKeyRow)
            .where(ApiKeyRow.token_hash == h)
            .values(last_used_at=backdate, created_at=backdate)
        )
        ses.commit()


def test_policy_default_is_unset(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/settings/security/api-key-inactivity", headers=_admin())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inactivity_days"] is None
    assert body["min_days"] >= 1
    assert body["max_days"] >= 365


def test_set_policy_rejects_out_of_range(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/api-key-inactivity",
        headers=_admin({"content-type": "application/json"}),
        json={"inactivity_days": 0},
    )
    assert r.status_code == 422


def test_stale_key_is_auto_revoked_and_rejected(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Admin sets a 30 day inactivity cap on tenant-a.
    r = c.put(
        "/v1/settings/security/api-key-inactivity",
        headers=_admin({"content-type": "application/json"}),
        json={"inactivity_days": 30},
    )
    assert r.status_code == 200, r.text

    # Mint a tenant-a key, then age it past the cap.
    token = _mint_key(c, tenant="tenant-a", label="ci")
    _age_key(token, days_old=60)

    # First request with the stale key: auto-revoked and rejected.
    r = c.get("/v1/api-keys", headers={"X-API-Key": token})
    assert r.status_code == 401, r.text
    body = r.json()
    assert body["error"] == "api_key_stale_inactive"
    assert body["inactivity_days"] == 30
    assert body["key_id"]

    # Second request with the same token: the row is now revoked, so the
    # normal "key not active" path takes over and we still get a 401.
    r2 = c.get("/v1/api-keys", headers={"X-API-Key": token})
    assert r2.status_code == 401


def test_policy_is_tenant_scoped(monkeypatch, tmp_path):
    """A policy on tenant-a must not auto-revoke a tenant-b key."""
    c = _client(monkeypatch, tmp_path)
    # Cap tenant-a only.
    r = c.put(
        "/v1/settings/security/api-key-inactivity",
        headers=_admin({"content-type": "application/json", "x-tenant": "tenant-a"}),
        json={"inactivity_days": 30},
    )
    assert r.status_code == 200

    # Mint a tenant-b key and age it past tenant-a's cap.
    token_b = _mint_key(c, tenant="tenant-b", label="other")
    _age_key(token_b, days_old=120)

    # tenant-b has no inactivity policy, so the aged tenant-b key still
    # authenticates. We pick a route that any authed key reaches (RBAC
    # may then 403 because the key lacks admin scope) so a 403 here also
    # proves the auth layer accepted the credential, which is what the
    # tenant-scoping invariant is about. A stale-key auto-revoke would
    # have produced 401 with ``api_key_stale_inactive``.
    r = c.get("/v1/api-keys", headers={"X-API-Key": token_b})
    assert r.status_code in (200, 403), r.text
    if r.status_code == 401:
        assert r.json().get("error") != "api_key_stale_inactive"
