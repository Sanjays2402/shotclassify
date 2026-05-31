"""OIDC SSO + per-tenant enforce-SSO.

Covers three deal-blocker behaviors enterprise buyers ask about:

1. Admin can configure SSO for their workspace via the API.
2. Domain uniqueness: two tenants cannot claim the same email domain
   (otherwise tenant B could phish tenant A's users into the wrong
   workspace at sign-in).
3. enforce_sso=True rejects any session for that tenant that was not
   minted via the SSO callback, while leaving other tenants and
   service-to-service API-key callers unaffected.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps({"acme-admin": "admin", "globex-admin": "admin"}),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps({"acme-admin": "acme", "globex-admin": "globex"}),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "default")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'sso.db'}")
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


def test_admin_can_configure_sso(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/sso",
        headers={"x-api-key": "acme-admin"},
        json={"enforced": False, "domain": "acme.com", "provider": "Okta"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "acme"
    assert body["enforced"] is False
    assert body["domain"] == "acme.com"
    assert body["provider"] == "Okta"

    # Read-back returns the same shape.
    g = c.get("/v1/settings/security/sso", headers={"x-api-key": "acme-admin"})
    assert g.status_code == 200
    assert g.json()["domain"] == "acme.com"


def test_sso_domain_is_unique_across_tenants(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r1 = c.put(
        "/v1/settings/security/sso",
        headers={"x-api-key": "acme-admin"},
        json={"enforced": False, "domain": "shared.example", "provider": None},
    )
    assert r1.status_code == 200

    # Globex tries to grab the same domain. Must be refused so they cannot
    # hijack acme's email-based routing at /auth/sso/login.
    r2 = c.put(
        "/v1/settings/security/sso",
        headers={"x-api-key": "globex-admin"},
        json={"enforced": False, "domain": "shared.example", "provider": None},
    )
    assert r2.status_code == 422, r2.text
    assert "another tenant" in r2.json()["detail"].lower()


def test_enforce_sso_blocks_non_sso_session_for_tenant(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Turn on enforcement for acme only.
    r = c.put(
        "/v1/settings/security/sso",
        headers={"x-api-key": "acme-admin"},
        json={"enforced": True, "domain": "acme.com", "provider": "Google"},
    )
    assert r.status_code == 200

    # Mint a legacy (oauth) session for an acme user via the dev-only helper.
    issue = c.post(
        "/auth/sso/_test/issue",
        params={"principal": "alice@acme.com", "tenant_id": "acme", "auth_method": "oauth"},
    )
    assert issue.status_code == 200, issue.text
    # The cookie is now in the client jar. A protected endpoint must reject it.
    me = c.get("/auth/whoami")
    # The middleware should reject the legacy session for an enforce-SSO tenant.
    assert me.status_code == 401, me.text
    assert me.json()["error"] == "sso_required"

    # An SSO-minted session for the SAME tenant works.
    c.cookies.clear()
    issue2 = c.post(
        "/auth/sso/_test/issue",
        params={"principal": "alice@acme.com", "tenant_id": "acme", "auth_method": "sso"},
    )
    assert issue2.status_code == 200
    ok = c.get("/auth/whoami")
    assert ok.status_code == 200
    assert ok.json()["principal"] == "alice@acme.com"

    # A legacy session for a DIFFERENT tenant (globex) is unaffected.
    c.cookies.clear()
    issue3 = c.post(
        "/auth/sso/_test/issue",
        params={"principal": "bob@globex.example", "tenant_id": "globex", "auth_method": "oauth"},
    )
    assert issue3.status_code == 200
    other = c.get("/auth/whoami")
    assert other.status_code == 200
    assert other.json()["principal"] == "bob@globex.example"


def test_non_admin_cannot_configure_sso(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps({"acme-viewer": "viewer"}),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps({"acme-viewer": "acme"}),
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'sso2.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    c = TestClient(create_app())
    r = c.put(
        "/v1/settings/security/sso",
        headers={"x-api-key": "acme-viewer"},
        json={"enforced": True, "domain": "acme.com", "provider": "Okta"},
    )
    assert r.status_code == 403, r.text


def test_sso_config_public_endpoint(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/auth/sso/config")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False  # not configured in tests
    assert "issuer" in body
