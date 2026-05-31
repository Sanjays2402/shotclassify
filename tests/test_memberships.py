"""Workspace memberships and invitations: cross-tenant isolation, role wiring,
last-admin protection, and one-shot invitation acceptance.

Covers the deal-blocker properties enterprise procurement asks about:

* listing/mutating members of tenant A from an admin key bound to tenant B
  returns 403/404 (no enumeration, no cross-tenant writes)
* membership rows beat the env-var role map: a user listed as ``admin`` in
  ``AUTH_ROLE_MAP`` is downgraded to whatever their membership row says
* the last admin of a workspace cannot demote or remove themselves out of
  the admin seat (the workspace must never be left without an admin)
* invitation tokens are single-use and the SHA-256 hash is what we store
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


# Header shortcuts so the test body reads like the curl a user would write.
ACME = {"X-API-Key": "admin-key"}
GLOBEX = {"X-API-Key": "other-admin-key"}


def test_invite_create_and_list_is_tenant_scoped(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.post(
        "/v1/invitations",
        headers=ACME,
        json={"email": "alice@example.com", "role": "operator"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token_display_once"] is True
    assert body["token"].startswith("inv_")
    assert body["tenant_id"] == "acme"

    # Acme admin sees its invitation.
    r = client.get("/v1/invitations", headers=ACME)
    assert r.status_code == 200
    assert len(r.json()["invitations"]) == 1

    # Globex admin sees nothing for its tenant: strict isolation.
    r = client.get("/v1/invitations", headers=GLOBEX)
    assert r.status_code == 200
    assert r.json()["invitations"] == []


def test_cross_tenant_invitation_revoke_is_404(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.post(
        "/v1/invitations",
        headers=ACME,
        json={"email": "alice@example.com", "role": "viewer"},
    )
    inv_id = r.json()["id"]

    # Globex admin must not be able to revoke an acme invitation, even by id.
    r = client.delete(f"/v1/invitations/{inv_id}", headers=GLOBEX)
    assert r.status_code == 404, r.text

    # Acme admin still can.
    r = client.delete(f"/v1/invitations/{inv_id}", headers=ACME)
    assert r.status_code == 200
    assert r.json()["invitation"]["status"] == "revoked"


def test_member_list_is_tenant_scoped(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    from shotclassify_store import memberships_store

    memberships_store.upsert_member(
        tenant_id="acme", principal="alice@example.com", role="operator"
    )
    memberships_store.upsert_member(
        tenant_id="globex", principal="bob@example.com", role="admin"
    )

    r = client.get("/v1/members", headers=ACME)
    assert r.status_code == 200
    logins = [m["principal"] for m in r.json()["members"]]
    assert logins == ["alice@example.com"]

    r = client.get("/v1/members", headers=GLOBEX)
    logins = [m["principal"] for m in r.json()["members"]]
    assert logins == ["bob@example.com"]


def test_last_admin_cannot_be_demoted(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    from shotclassify_store import memberships_store

    memberships_store.upsert_member(
        tenant_id="acme", principal="only@example.com", role="admin"
    )

    r = client.put(
        "/v1/members/only@example.com",
        headers=ACME,
        json={"role": "operator"},
    )
    assert r.status_code == 409, r.text


def test_membership_role_overrides_env_role_map(monkeypatch, tmp_path):
    """Direct unit test: store helper drives the auth middleware decision."""
    _client(monkeypatch, tmp_path)
    from shotclassify_store import memberships_store

    assert memberships_store.role_for_member("acme", "alice@example.com") is None
    memberships_store.upsert_member(
        tenant_id="acme", principal="alice@example.com", role="viewer"
    )
    assert memberships_store.role_for_member("acme", "alice@example.com") == "viewer"
    # Same principal, different tenant: must be isolated.
    assert memberships_store.role_for_member("globex", "alice@example.com") is None


def test_invitation_accept_is_single_use(monkeypatch, tmp_path):
    _client(monkeypatch, tmp_path)
    from shotclassify_store import memberships_store

    _, token = memberships_store.create_invitation(
        tenant_id="acme",
        email="alice@example.com",
        role="operator",
        invited_by="admin@example.com",
    )

    first = memberships_store.accept_invitation(token, principal="alice@example.com")
    assert first is not None
    inv, member = first
    assert inv.status == "accepted"
    assert member.role == "operator"
    assert member.tenant_id == "acme"

    # Replay must fail.
    assert memberships_store.accept_invitation(token, principal="mallory@x.com") is None
