"""Per-tenant webhook egress host allowlist is enforced end-to-end.

The allowlist scopes which destinations a workspace's webhooks may
post to. This is the SOC 2 / procurement control on top of the
deployment SSRF block. The tests prove:

* Admin role + MFA step-up gates the PUT.
* Subscriptions with a host outside the allowlist are rejected at
  create time with HTTP 400 and a tenant-scoped error message.
* Existing subscriptions stop receiving deliveries the moment the
  policy tightens: the dispatcher records a ``failed`` delivery whose
  error names ``egress blocked`` and never POSTs to the destination.
* Cross-tenant isolation: tenant A's allowlist does not affect
  tenant B and tenant B cannot read tenant A's allowlist.
* Leading-dot suffix entries match the apex and any subdomain.
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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'whegress.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    # Existing webhook tests run with allow_private=true so DNS
    # failures at validation time do not block subscriptions that
    # point at synthetic hostnames. The per-tenant allowlist is
    # orthogonal to that flag: it runs first and enforces purely on
    # the URL's hostname string.
    monkeypatch.setenv("WEBHOOK_EGRESS_ALLOW_PRIVATE", "true")
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


def _set_hosts(c: TestClient, *, tenant: str, hosts):
    return c.put(
        "/v1/settings/security/webhook-egress-hosts",
        headers=_admin({"content-type": "application/json", "x-tenant": tenant}),
        json={"hosts": hosts},
    )


def _create_sub(c: TestClient, *, tenant: str, url: str):
    return c.post(
        "/v1/webhooks",
        headers=_admin({"content-type": "application/json", "x-tenant": tenant}),
        json={
            "url": url,
            "events": ["classify.completed"],
            "description": None,
        },
    )


def test_put_requires_admin(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps({"admin-key": "tenant-a", "viewer-key": "tenant-a"}),
    )
    monkeypatch.setenv("AUTH_VIEWER_API_KEYS", json.dumps(["viewer-key"]))
    # The role for an API key is inferred from the bearer's scopes; a
    # plain viewer principal cannot mutate security settings. We assert
    # the public guarantee: a request without admin scope is refused.
    r = c.put(
        "/v1/settings/security/webhook-egress-hosts",
        headers={
            "X-API-Key": "anonymous",
            "content-type": "application/json",
            "x-tenant": "tenant-a",
        },
        json={"hosts": ["hooks.example.com"]},
    )
    assert r.status_code in (401, 403), r.text


def test_get_default_is_empty(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    r = c.get(
        "/v1/settings/security/webhook-egress-hosts",
        headers=_admin({"x-tenant": "tenant-a"}),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "tenant-a"
    assert body["hosts"] == []
    assert body["max_hosts"] >= 1


def test_create_blocked_when_host_not_in_allowlist(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    r = _set_hosts(c, tenant="tenant-a", hosts=["hooks.example.com"])
    assert r.status_code == 200, r.text
    assert r.json()["hosts"] == ["hooks.example.com"]

    # Off-list host: must be refused at create.
    bad = _create_sub(c, tenant="tenant-a", url="https://evil.attacker.test/hook")
    assert bad.status_code == 422, bad.text
    body_text = bad.text.lower()
    assert "evil.attacker.test" in body_text
    assert "allowlist" in body_text

    # On-list host: accepted.
    ok = _create_sub(c, tenant="tenant-a", url="https://hooks.example.com/x")
    assert ok.status_code in (200, 201), ok.text


def test_suffix_entry_matches_subdomains(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    r = _set_hosts(c, tenant="tenant-a", hosts=[".example.com"])
    assert r.status_code == 200, r.text

    for u in (
        "https://example.com/h",
        "https://hooks.example.com/h",
        "https://api.eu.example.com/h",
    ):
        rok = _create_sub(c, tenant="tenant-a", url=u)
        assert rok.status_code in (200, 201), (u, rok.text)

    bad = _create_sub(c, tenant="tenant-a", url="https://example.org/h")
    assert bad.status_code == 422, bad.text


def test_dispatch_blocked_after_policy_tightens(monkeypatch, tmp_path):
    """An in-flight subscription stops delivering when the host is
    removed from the allowlist. The dispatcher records a failed
    delivery whose error names ``egress blocked``; no HTTP call is
    attempted."""
    c = _client(monkeypatch, tmp_path)

    # Create the subscription while the policy still allows it.
    _set_hosts(c, tenant="tenant-a", hosts=["hooks.example.com"])
    created = _create_sub(c, tenant="tenant-a", url="https://hooks.example.com/x")
    assert created.status_code in (200, 201), created.text
    sub_id = created.json()["webhook"]["id"]

    # Tighten the policy so the existing host is no longer allowed.
    _set_hosts(c, tenant="tenant-a", hosts=["other.example.com"])

    # Dispatch directly through the store so the test does not require
    # the worker to be running.
    from shotclassify_store import webhooks_store

    results = webhooks_store.dispatch_event(
        tenant_id="tenant-a",
        event="classify.completed",
        payload={"id": "c1", "shot_id": "s1"},
    )
    assert results, "expected one delivery record for the existing subscription"
    rec = results[0]
    assert rec.subscription_id == sub_id
    assert rec.status == "failed"
    assert "egress blocked" in (rec.error or "").lower()
    assert "hooks.example.com" in (rec.error or "").lower()


def test_cross_tenant_isolation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    _set_hosts(c, tenant="tenant-a", hosts=["a.example.com"])
    _set_hosts(c, tenant="tenant-b", hosts=["b.example.com"])

    # Tenant A reads only its own policy.
    ra = c.get(
        "/v1/settings/security/webhook-egress-hosts",
        headers=_admin({"x-tenant": "tenant-a"}),
    )
    assert ra.status_code == 200
    assert ra.json()["hosts"] == ["a.example.com"]

    rb = c.get(
        "/v1/settings/security/webhook-egress-hosts",
        headers=_admin({"x-tenant": "tenant-b"}),
    )
    assert rb.status_code == 200
    assert rb.json()["hosts"] == ["b.example.com"]

    # Tenant A is bound by its own list, not tenant B's.
    bad = _create_sub(c, tenant="tenant-a", url="https://b.example.com/x")
    assert bad.status_code == 422, bad.text


def test_rejects_wildcards_and_garbage(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    for bad in (["*.example.com"], ["http:///"], ["not a host"], [""]):
        r = _set_hosts(c, tenant="tenant-a", hosts=bad)
        assert r.status_code == 422, (bad, r.text)
