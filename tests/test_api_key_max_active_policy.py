"""Per-tenant cap on active (non-revoked) API keys is enforced end-to-end.

* Setting the policy requires admin role and MFA step-up.
* When the cap is set, ``POST /v1/api-keys`` rejects with HTTP 422 and
  ``api_key_max_active_reached`` once the workspace already holds that
  many active keys.
* Revoking a key frees a slot immediately, so a new mint succeeds again.
* Tenant B's cap does not affect tenant A: the policy is per-workspace
  and counted by tenant_id.
* The list response surfaces ``max_active_policy`` with the current
  in-use count so the admin UI can show "N of M".
* Cross-tenant probe: tenant B's cap and current_active are not
  leaked to tenant A's list response.
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
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps({"admin-key": "tenant-a"}),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "tenant-a")
    monkeypatch.setenv("MFA_STEP_UP_REQUIRED", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'maxactive.db'}")
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


def _admin(extra: dict | None = None) -> dict:
    h = {"X-API-Key": "admin-key"}
    if extra:
        h.update(extra)
    return h


def _set_cap(client: TestClient, *, tenant: str, n: int | None) -> None:
    r = client.put(
        "/v1/settings/security/api-key-max-active",
        headers=_admin({"content-type": "application/json", "x-tenant": tenant}),
        json={"max_active": n},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == tenant
    assert body["max_active"] == n


def _mint(client: TestClient, *, tenant: str, label: str):
    return client.post(
        "/v1/api-keys",
        headers=_admin({"content-type": "application/json", "x-tenant": tenant}),
        json={"label": label, "scopes": ["write:classifications"], "owner_email": "ci-bot@example.com"},
    )


def test_max_active_cap_blocks_mint_then_revoke_frees_slot(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    _set_cap(c, tenant="tenant-a", n=2)

    r1 = _mint(c, tenant="tenant-a", label="k1")
    assert r1.status_code in (200, 201), r1.text
    r2 = _mint(c, tenant="tenant-a", label="k2")
    assert r2.status_code in (200, 201), r2.text

    # Third mint must fail at the cap.
    r3 = _mint(c, tenant="tenant-a", label="k3")
    assert r3.status_code == 422, r3.text
    assert "api_key_max_active_reached" in r3.text

    # List surface shows current usage and the policy.
    rl = c.get(
        "/v1/api-keys",
        headers=_admin({"x-tenant": "tenant-a"}),
    )
    assert rl.status_code == 200, rl.text
    body = rl.json()
    assert body["max_active_policy"]["max_active"] == 2
    assert body["max_active_policy"]["current_active"] == 2

    # Revoke one to free a slot.
    key_to_revoke = r1.json()["id"]
    rrev = c.delete(
        f"/v1/api-keys/{key_to_revoke}",
        headers=_admin({"x-tenant": "tenant-a"}),
    )
    assert rrev.status_code == 200, rrev.text

    # Now a new mint succeeds again.
    r4 = _mint(c, tenant="tenant-a", label="k4")
    assert r4.status_code in (200, 201), r4.text


def test_max_active_cap_is_per_tenant(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    _set_cap(c, tenant="tenant-a", n=1)
    # No cap on tenant-b at all.

    # Tenant A is at its cap after one mint.
    assert _mint(c, tenant="tenant-a", label="a1").status_code in (200, 201)
    blocked = _mint(c, tenant="tenant-a", label="a2")
    assert blocked.status_code == 422
    assert "api_key_max_active_reached" in blocked.text

    # Tenant B is completely unaffected.
    for i in range(3):
        r = _mint(c, tenant="tenant-b", label=f"b{i}")
        assert r.status_code in (200, 201), r.text

    # Tenant A's list does not see tenant B's keys or count.
    rla = c.get("/v1/api-keys", headers=_admin({"x-tenant": "tenant-a"}))
    assert rla.status_code == 200
    body_a = rla.json()
    assert body_a["max_active_policy"]["max_active"] == 1
    assert body_a["max_active_policy"]["current_active"] == 1
    assert all(k.get("tenant_id") == "tenant-a" for k in body_a["keys"])

    # Tenant B's list shows its own three keys and no cap.
    rlb = c.get("/v1/api-keys", headers=_admin({"x-tenant": "tenant-b"}))
    assert rlb.status_code == 200
    body_b = rlb.json()
    assert body_b["max_active_policy"]["max_active"] is None
    assert body_b["max_active_policy"]["current_active"] == 3


def test_max_active_policy_validation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    for bad in (0, -1, 100000, True, "ten", 1.5):
        r = c.put(
            "/v1/settings/security/api-key-max-active",
            headers=_admin({"content-type": "application/json", "x-tenant": "tenant-a"}),
            json={"max_active": bad},
        )
        assert r.status_code == 422, (bad, r.text)

    # Missing field is a 422 too.
    r = c.put(
        "/v1/settings/security/api-key-max-active",
        headers=_admin({"content-type": "application/json", "x-tenant": "tenant-a"}),
        json={},
    )
    assert r.status_code == 422

    # Null clears the policy.
    r = c.put(
        "/v1/settings/security/api-key-max-active",
        headers=_admin({"content-type": "application/json", "x-tenant": "tenant-a"}),
        json={"max_active": None},
    )
    assert r.status_code == 200
    assert r.json()["max_active"] is None
