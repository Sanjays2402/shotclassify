"""Per-tenant brute-force authentication lockout policy.

Asserts the deal-blocker behaviours an enterprise procurement reviewer
checks for:

* When no policy is configured, repeated bad API keys keep returning
  401 forever (legacy behaviour preserved).
* When a tenant configures threshold/window/cooldown, the (tenant, IP)
  bucket trips at the threshold and every subsequent request from that
  IP returns HTTP 423 with a ``Retry-After`` header, *even when the
  caller now presents a valid API key for that same tenant*. A locked
  IP is locked, period.
* The lockout is strictly scoped to (tenant, IP). A noisy attacker
  against tenant A coming from IP X does not lock out a *different*
  tenant B reachable from the same IP X. This is the cross-tenant
  isolation guarantee the lockout store promises.
* An admin can list active lockouts and clear one, after which the
  same IP can authenticate again.
* Setting a half-configured policy (threshold without cooldown) is
  rejected with 422 so a UI misclick cannot silently disable
  enforcement.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-a")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps({"admin-a": "admin", "admin-b": "admin"}),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps({"admin-a": "tenant-a", "admin-b": "tenant-b"}),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "tenant-a")
    monkeypatch.setenv("MFA_STEP_UP_REQUIRED", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'lockout.db'}")
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


def _hdr(key: str, ip: str = "203.0.113.7") -> dict:
    return {"X-API-Key": key, "X-Forwarded-For": ip}


def test_default_policy_is_disabled_and_no_lockouts_occur(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/settings/security/auth-lockout", headers=_hdr("admin-a"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["threshold"] == 0

    # Many bad attempts should still all be 401, not 423: lockout is off.
    for _ in range(20):
        r = c.get(
            "/v1/history",
            headers={"X-API-Key": "nope-not-real", "X-Forwarded-For": "1.2.3.4"},
        )
        assert r.status_code == 401, r.text


def test_locked_ip_cannot_use_even_a_valid_key_for_that_tenant(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Tenant A enables a 3-strike policy in a 60-minute window with a
    # 30-minute cooldown.
    r = c.put(
        "/v1/settings/security/auth-lockout",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"threshold": 3, "window_minutes": 60, "cooldown_minutes": 30},
    )
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True

    bad = {"X-API-Key": "totally-bogus", "X-Forwarded-For": "198.51.100.9"}
    # First two are plain 401s as the counter climbs to 2.
    for i in range(2):
        r = c.get("/v1/history", headers=bad)
        assert r.status_code == 401, f"attempt {i}: {r.text}"

    # Third failure crosses the threshold; this same request is
    # answered 423 and every later one is too.
    r = c.get("/v1/history", headers=bad)
    assert r.status_code == 423, r.text
    assert int(r.headers.get("retry-after", "0")) > 0
    r = c.get("/v1/history", headers=bad)
    assert r.status_code == 423, r.text

    # A *valid* admin-a API key from the *same* locked IP is also
    # refused. The lockout is per (tenant, IP), not per credential, so
    # even legitimate traffic from that IP is shut out until cooldown.
    r = c.get(
        "/v1/history",
        headers={"X-API-Key": "admin-a", "X-Forwarded-For": "198.51.100.9"},
    )
    assert r.status_code == 423, r.text
    assert int(r.headers.get("retry-after", "0")) > 0


def test_lockout_does_not_bleed_across_tenants(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/auth-lockout",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"threshold": 3, "window_minutes": 60, "cooldown_minutes": 30},
    )
    assert r.status_code == 200, r.text

    bad = {"X-API-Key": "spray-spray", "X-Forwarded-For": "192.0.2.55"}
    for _ in range(5):
        c.get("/v1/history", headers=bad)

    # Tenant A from that IP: locked.
    r = c.get(
        "/v1/history",
        headers={"X-API-Key": "admin-a", "X-Forwarded-For": "192.0.2.55"},
    )
    assert r.status_code == 423

    # Tenant B is untouched. Even from the *same* attacking IP, a valid
    # tenant-B key still works (auth succeeds, route returns its own
    # status). The lockout key includes the tenant, so tenant B's
    # authentication is not affected. This is the cross-tenant isolation
    # guarantee: anything other than 401 or 423 proves auth passed.
    r = c.get(
        "/v1/history",
        headers={"X-API-Key": "admin-b", "X-Forwarded-For": "192.0.2.55"},
    )
    assert r.status_code not in (401, 423), r.text


def test_admin_can_list_and_clear_a_lockout(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/auth-lockout",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"threshold": 3, "window_minutes": 60, "cooldown_minutes": 30},
    )
    assert r.status_code == 200, r.text

    bad = {"X-API-Key": "wrong", "X-Forwarded-For": "203.0.113.42"}
    for _ in range(4):
        c.get("/v1/history", headers=bad)

    # Admin lists lockouts from a *different* IP so the listing call
    # itself does not trip the lockout we are inspecting.
    r = c.get(
        "/v1/admin/lockouts",
        headers={"X-API-Key": "admin-a", "X-Forwarded-For": "10.0.0.1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    active = [x for x in body["lockouts"] if x["active"]]
    assert len(active) >= 1
    target = next(x for x in active if x["ip"] == "203.0.113.42")

    # Clear the lockout.
    r = c.delete(
        f"/v1/admin/lockouts/{target['id']}",
        headers={"X-API-Key": "admin-a", "X-Forwarded-For": "10.0.0.1"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cleared"] is True

    # The previously-locked IP can now authenticate again (anything
    # other than 401/423 proves the auth middleware let it through).
    r = c.get(
        "/v1/history",
        headers={"X-API-Key": "admin-a", "X-Forwarded-For": "203.0.113.42"},
    )
    assert r.status_code not in (401, 423), r.text


def test_half_configured_policy_is_rejected(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/auth-lockout",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"threshold": 5, "window_minutes": 30, "cooldown_minutes": None},
    )
    assert r.status_code == 422, r.text

    # Out-of-range threshold also refused.
    r = c.put(
        "/v1/settings/security/auth-lockout",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"threshold": 1, "window_minutes": 30, "cooldown_minutes": 10},
    )
    assert r.status_code == 422, r.text


def test_clearing_other_tenants_lockout_is_refused(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Tenant A configures policy and gets a real lockout row.
    c.put(
        "/v1/settings/security/auth-lockout",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"threshold": 3, "window_minutes": 60, "cooldown_minutes": 30},
    )
    for _ in range(4):
        c.get(
            "/v1/history",
            headers={"X-API-Key": "junk", "X-Forwarded-For": "203.0.113.77"},
        )
    r = c.get(
        "/v1/admin/lockouts",
        headers={"X-API-Key": "admin-a", "X-Forwarded-For": "10.0.0.2"},
    )
    assert r.status_code == 200
    rows = r.json()["lockouts"]
    assert rows, "expected at least one lockout"
    target_id = rows[0]["id"]

    # Tenant B tries to clear tenant A's row. The store refuses with 404
    # so an admin cannot use a guessed id to muck with another workspace.
    r = c.delete(
        f"/v1/admin/lockouts/{target_id}",
        headers={"X-API-Key": "admin-b", "X-Forwarded-For": "10.0.0.3"},
    )
    assert r.status_code == 404, r.text
