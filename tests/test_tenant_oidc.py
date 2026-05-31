"""Per-tenant OIDC IdP configuration.

Enterprise customers reject SaaS that asks them to surrender their
corporate Okta / Azure AD OIDC credentials to the vendor's shared
deployment IdP. These tests cover the per-tenant OIDC IdP that lets
each workspace register its own application.

What we exercise:

1. Admin can configure a per-tenant OIDC IdP and the response never
   leaks the client_secret (only fingerprint + last-four are returned).
2. Per-tenant IdP isolation: tenant B cannot read tenant A's config,
   and updating one tenant does not touch the other.
3. ``/auth/sso/config?email=...`` advertises the per-tenant IdP when
   the email domain matches a tenant with its own OIDC config, even
   when the deployment-level SSO env is *not* configured.
4. Partial configs are rejected (must supply both issuer and client_id;
   secret is required on first set).
5. Non-admin members cannot read or write the per-tenant OIDC config.
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
        json.dumps(
            {
                "acme-admin": "admin",
                "globex-admin": "admin",
                "acme-viewer": "viewer",
            }
        ),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps(
            {
                "acme-admin": "acme",
                "globex-admin": "globex",
                "acme-viewer": "acme",
            }
        ),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "default")
    # Deliberately leave AUTH_SSO_* unset: we want to prove the per-tenant
    # IdP works even when there is no deployment-level shared client.
    monkeypatch.setenv("AUTH_SSO_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'oidc.db'}")
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


def _configure_oidc(c, key, **overrides):
    body = {
        "issuer": "https://example.okta.com",
        "client_id": "0oa-acme-client",
        "client_secret": "super-secret-XYZ9",
        "scopes": "openid email profile",
    }
    body.update(overrides)
    return c.put("/v1/settings/security/oidc", headers={"x-api-key": key}, json=body)


def test_admin_can_configure_per_tenant_oidc_and_secret_is_never_returned(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = _configure_oidc(c, "acme-admin")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "acme"
    assert body["configured"] is True
    assert body["issuer"] == "https://example.okta.com"
    assert body["client_id"] == "0oa-acme-client"
    assert body["scopes"] == "openid email profile"
    # Critical: the plaintext secret must never appear in the response.
    assert "client_secret" not in body
    serialized = json.dumps(body)
    assert "super-secret-XYZ9" not in serialized
    # Fingerprint + last-four are surfaced for operator confirmation.
    assert body["client_secret_last_four"] == "XYZ9"
    assert len(body["client_secret_fingerprint"]) == 64

    # Read-back returns the same shape and still no secret.
    g = c.get("/v1/settings/security/oidc", headers={"x-api-key": "acme-admin"})
    assert g.status_code == 200
    gbody = g.json()
    assert gbody["configured"] is True
    assert "client_secret" not in gbody
    assert "super-secret-XYZ9" not in json.dumps(gbody)


def test_per_tenant_oidc_is_isolated_across_tenants(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert _configure_oidc(c, "acme-admin").status_code == 200
    assert _configure_oidc(
        c,
        "globex-admin",
        issuer="https://globex.auth0.com",
        client_id="globex-app",
        client_secret="globex-secret-1234",
    ).status_code == 200

    a = c.get("/v1/settings/security/oidc", headers={"x-api-key": "acme-admin"}).json()
    g = c.get("/v1/settings/security/oidc", headers={"x-api-key": "globex-admin"}).json()
    assert a["tenant_id"] == "acme"
    assert g["tenant_id"] == "globex"
    assert a["issuer"] != g["issuer"]
    assert a["client_id"] != g["client_id"]
    assert a["client_secret_fingerprint"] != g["client_secret_fingerprint"]
    # And neither response leaks the other tenant's secret.
    assert "globex-secret-1234" not in json.dumps(a)
    assert "super-secret-XYZ9" not in json.dumps(g)


def test_sso_config_endpoint_advertises_per_tenant_idp_by_email_domain(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Bind the email domain to tenant "acme" then configure that tenant's IdP.
    sso = c.put(
        "/v1/settings/security/sso",
        headers={"x-api-key": "acme-admin"},
        json={"enforced": False, "domain": "acme.com", "provider": "Okta"},
    )
    assert sso.status_code == 200, sso.text
    assert _configure_oidc(c, "acme-admin").status_code == 200

    # No email -> deployment fallback (and deployment is disabled in this test).
    r = c.get("/auth/sso/config")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "deployment"
    assert body["enabled"] is False

    # Matching email domain -> tenant-scoped advertisement, even though the
    # deployment IdP is unconfigured. This is what unblocks the sign-in
    # page from showing a customer-branded SSO button.
    r2 = c.get("/auth/sso/config", params={"email": "user@acme.com"})
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["enabled"] is True
    assert b2["source"] == "tenant"
    assert b2["tenant_id"] == "acme"
    assert b2["issuer"] == "https://example.okta.com"


def test_partial_oidc_config_is_rejected(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Missing client_id.
    r = c.put(
        "/v1/settings/security/oidc",
        headers={"x-api-key": "acme-admin"},
        json={"issuer": "https://example.okta.com", "client_secret": "s"},
    )
    assert r.status_code == 422
    # Missing secret on first-time configure.
    r2 = c.put(
        "/v1/settings/security/oidc",
        headers={"x-api-key": "acme-admin"},
        json={"issuer": "https://example.okta.com", "client_id": "x"},
    )
    assert r2.status_code == 422
    # Non-https issuer is rejected so we cannot exchange tokens over plain HTTP.
    r3 = c.put(
        "/v1/settings/security/oidc",
        headers={"x-api-key": "acme-admin"},
        json={
            "issuer": "http://insecure.example.com",
            "client_id": "x",
            "client_secret": "y",
        },
    )
    assert r3.status_code == 422


def test_non_admin_cannot_read_or_write_oidc(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Viewer in same tenant -> 403 on read and on write.
    r = c.get("/v1/settings/security/oidc", headers={"x-api-key": "acme-viewer"})
    assert r.status_code in (401, 403)
    w = c.put(
        "/v1/settings/security/oidc",
        headers={"x-api-key": "acme-viewer"},
        json={
            "issuer": "https://example.okta.com",
            "client_id": "x",
            "client_secret": "y",
        },
    )
    assert w.status_code in (401, 403)


def test_oidc_clear_restores_deployment_fallback(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Bind domain + configure per-tenant IdP.
    c.put(
        "/v1/settings/security/sso",
        headers={"x-api-key": "acme-admin"},
        json={"enforced": False, "domain": "acme.com", "provider": "Okta"},
    )
    assert _configure_oidc(c, "acme-admin").status_code == 200
    assert (
        c.get("/auth/sso/config", params={"email": "user@acme.com"}).json()["source"]
        == "tenant"
    )
    # Clear it. Now matching email falls back to deployment (which is off).
    d = c.delete("/v1/settings/security/oidc", headers={"x-api-key": "acme-admin"})
    assert d.status_code == 200
    assert d.json()["configured"] is False
    fb = c.get("/auth/sso/config", params={"email": "user@acme.com"}).json()
    assert fb["source"] == "deployment"
    assert fb["enabled"] is False
