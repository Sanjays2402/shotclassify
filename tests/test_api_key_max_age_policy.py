"""Per-tenant API key mandatory rotation (max age) policy is enforced end-to-end.

Companion control to the inactivity policy: that one keys off last-use,
this one keys off ``created_at`` so an actively used but stale key still
gets caught.

* Default policy is unset (legacy behaviour: keys live forever).
* Setting the policy validates input range and requires admin role.
* When set, presenting a DB-backed API key whose ``created_at`` is older
  than the cap auto-revokes the key and rejects the request with 401
  ``api_key_rotation_required``.
* The same key presented again 401s under the standard inactive-key
  shape because the row is now revoked.
* The policy is tenant-scoped: setting it on tenant-a does not affect
  tenant-b's keys.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'maxage.db'}")
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
    r = client.post(
        "/v1/api-keys",
        headers=_admin({"content-type": "application/json", "x-tenant": tenant}),
        json={
            "label": label,
            "scopes": ["write:classifications"],
            "owner_email": "ci-bot@example.com",
        },
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["token"]


def _backdate_created(token: str, *, days_old: int) -> None:
    """Backdate only ``created_at`` so the inactivity policy is not triggered."""
    from shotclassify_store.api_keys import _hash
    from shotclassify_store.db import ApiKeyRow, get_session

    h = _hash(token)
    backdate = datetime.now(UTC) - timedelta(days=days_old)
    with get_session() as ses:
        ses.execute(
            update(ApiKeyRow)
            .where(ApiKeyRow.token_hash == h)
            .values(created_at=backdate, last_used_at=datetime.now(UTC)),
        )
        ses.commit()


def test_max_age_policy_default_is_unset(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/settings/security/api-key-max-age", headers=_admin())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["max_age_days"] is None
    assert body["min_days"] >= 1
    assert body["max_days"] >= 365


def test_set_max_age_rejects_out_of_range(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/api-key-max-age",
        headers=_admin({"content-type": "application/json"}),
        json={"max_age_days": 0},
    )
    assert r.status_code == 422


def test_set_max_age_requires_field(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/api-key-max-age",
        headers=_admin({"content-type": "application/json"}),
        json={},
    )
    assert r.status_code == 422


def test_stale_key_is_auto_revoked_and_rejected(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/api-key-max-age",
        headers=_admin({"content-type": "application/json"}),
        json={"max_age_days": 90},
    )
    assert r.status_code == 200, r.text

    token = _mint_key(c, tenant="tenant-a", label="rotate-me")
    # Active but old: created 180 days ago, last_used right now.
    _backdate_created(token, days_old=180)

    r = c.get("/v1/api-keys", headers={"X-API-Key": token})
    assert r.status_code == 401, r.text
    body = r.json()
    assert body["error"] == "api_key_rotation_required"
    assert body["max_age_days"] == 90
    assert body["key_id"]

    # Second request: row is now revoked, normal inactive-key path.
    r2 = c.get("/v1/api-keys", headers={"X-API-Key": token})
    assert r2.status_code == 401


def test_max_age_policy_is_tenant_scoped(monkeypatch, tmp_path):
    """A policy on tenant-a must not auto-revoke a tenant-b key."""
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/api-key-max-age",
        headers=_admin({"content-type": "application/json", "x-tenant": "tenant-a"}),
        json={"max_age_days": 30},
    )
    assert r.status_code == 200

    token_b = _mint_key(c, tenant="tenant-b", label="other")
    _backdate_created(token_b, days_old=365)

    r = c.get("/v1/api-keys", headers={"X-API-Key": token_b})
    assert r.status_code in (200, 403), r.text
    if r.status_code == 401:
        assert r.json().get("error") != "api_key_rotation_required"
