"""Per-tenant allowed-email-domains policy for invitations and provisioning.

Proves the enterprise gate: when a workspace owner restricts the set of
email domains that may be invited or auto-joined, every entry path
(REST invitation, SCIM provision, store-layer call) refuses an out-of-
policy email. Also proves the policy is strictly tenant-scoped: the
policy on workspace A never affects an invitation in workspace B.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps({"other-admin-key": "admin"}),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps(
            {
                "admin-key": "acme",
                "other-admin-key": "globex",
            }
        ),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "acme")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'mem.db'}")
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
    from services.api.app.main import create_app

    return TestClient(create_app())


ACME = {"X-API-Key": "admin-key"}
GLOBEX = {"X-API-Key": "other-admin-key"}


def test_get_invite_domains_defaults_to_no_policy(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/v1/settings/security/invite-domains", headers=ACME)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "acme"
    assert body["allowed_domains"] == []
    assert body["max_entries"] > 0


def test_set_invite_domains_normalizes_and_persists(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.put(
        "/v1/settings/security/invite-domains",
        headers=ACME,
        json={"allowed_domains": ["ACME.com", " .corp.acme.com ", "acme.com"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Lowercased, whitespace stripped, duplicates dropped, dot-prefix kept.
    assert body["allowed_domains"] == ["acme.com", ".corp.acme.com"]

    # Read-back returns the same normalized list.
    r = client.get("/v1/settings/security/invite-domains", headers=ACME)
    assert r.status_code == 200
    assert r.json()["allowed_domains"] == ["acme.com", ".corp.acme.com"]


def test_invalid_domain_is_rejected(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.put(
        "/v1/settings/security/invite-domains",
        headers=ACME,
        json={"allowed_domains": ["not an email domain"]},
    )
    assert r.status_code == 422


def test_invitation_rejected_when_email_outside_policy(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.put(
        "/v1/settings/security/invite-domains",
        headers=ACME,
        json={"allowed_domains": ["acme.com"]},
    )
    assert r.status_code == 200

    # Personal address is refused with a structured payload.
    r = client.post(
        "/v1/invitations",
        headers=ACME,
        json={"email": "someone@gmail.com", "role": "viewer"},
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "invite_domain_not_allowed"
    assert detail["email"] == "someone@gmail.com"
    assert detail["allowed_domains"] == ["acme.com"]

    # No row was written: the invitation list stays empty.
    r = client.get("/v1/invitations", headers=ACME)
    assert r.status_code == 200
    assert r.json()["invitations"] == []


def test_invitation_accepted_when_email_matches_policy(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.put(
        "/v1/settings/security/invite-domains",
        headers=ACME,
        json={"allowed_domains": ["acme.com", ".corp.acme.com"]},
    )
    # Bare-domain match.
    r = client.post(
        "/v1/invitations",
        headers=ACME,
        json={"email": "alice@acme.com", "role": "operator"},
    )
    assert r.status_code == 201, r.text
    # Sub-domain match via leading-dot entry.
    r = client.post(
        "/v1/invitations",
        headers=ACME,
        json={"email": "bob@ops.corp.acme.com", "role": "viewer"},
    )
    assert r.status_code == 201, r.text


def test_policy_is_strictly_tenant_scoped(monkeypatch, tmp_path):
    """Acme's policy must never gate Globex's invitations."""
    client = _client(monkeypatch, tmp_path)
    # Acme locks down to acme.com only.
    r = client.put(
        "/v1/settings/security/invite-domains",
        headers=ACME,
        json={"allowed_domains": ["acme.com"]},
    )
    assert r.status_code == 200

    # Globex has no policy and accepts any address.
    r = client.get("/v1/settings/security/invite-domains", headers=GLOBEX)
    assert r.status_code == 200
    assert r.json()["allowed_domains"] == []

    r = client.post(
        "/v1/invitations",
        headers=GLOBEX,
        json={"email": "external@partner.io", "role": "viewer"},
    )
    assert r.status_code == 201, r.text


def test_scim_provision_refuses_out_of_policy_email(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    # Configure SCIM and the domain policy for acme.
    from shotclassify_store import tenant_settings

    tenant_settings.set_allowed_invite_domains(
        "acme", ["acme.com"], updated_by="admin"
    )
    from shotclassify_store import scim_store

    _cfg, token = scim_store.rotate_scim_token("acme", updated_by="admin")
    scim_store.set_scim_default_role("acme", "viewer", updated_by="admin")

    # Out-of-policy SCIM POST is 400 invalidValue.
    r = client.post(
        "/scim/v2/Users",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/scim+json",
        },
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "outsider@gmail.com",
            "active": True,
        },
    )
    assert r.status_code == 400, r.text

    # In-policy SCIM POST succeeds.
    r = client.post(
        "/scim/v2/Users",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/scim+json",
        },
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "alice@acme.com",
            "active": True,
        },
    )
    assert r.status_code == 201, r.text


def test_store_layer_enforces_policy_directly(monkeypatch, tmp_path):
    """Direct store call must raise even if a future caller skips the route."""
    _client(monkeypatch, tmp_path)
    from shotclassify_store import memberships_store, tenant_settings
    from shotclassify_store.memberships import InviteDomainNotAllowed

    tenant_settings.set_allowed_invite_domains(
        "acme", ["acme.com"], updated_by="admin"
    )
    try:
        memberships_store.create_invitation(
            tenant_id="acme",
            email="someone@gmail.com",
            role="viewer",
            invited_by="admin",
        )
    except InviteDomainNotAllowed as exc:
        assert exc.email == "someone@gmail.com"
        assert exc.allowed == ["acme.com"]
    else:
        raise AssertionError("create_invitation must refuse out-of-policy email")
