"""Dual-control (two-person rule) for high-privilege API key issuance.

Proves the enterprise gate: when a workspace enables dual-control, a
request to mint a key with the ``admin`` scope does not return a token.
It returns HTTP 202 + a pending issuance request id. A *different*
admin must then call ``/approve`` for the key to be minted. Self
approval is rejected. The policy is strictly per-tenant: enabling it on
workspace A does not affect workspace B.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "alice-key")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps(
            {
                "bob-key": "admin",
                "globex-admin-key": "admin",
            }
        ),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps(
            {
                "alice-key": "acme",
                "bob-key": "acme",
                "globex-admin-key": "globex",
            }
        ),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "acme")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'mem.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("MFA_REQUIRED_FOR_ADMIN", "false")
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


ALICE = {"X-API-Key": "alice-key"}  # acme admin
BOB = {"X-API-Key": "bob-key"}      # acme admin (peer)
GLOBEX = {"X-API-Key": "globex-admin-key"}


def test_policy_defaults_to_disabled(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/v1/settings/security/dual-control", headers=ALICE)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert "admin" in body["protected_scopes"]


def test_disabled_policy_mints_admin_key_directly(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.post(
        "/v1/api-keys",
        headers=ALICE,
        json={"label": "ci", "scopes": ["admin"], "owner_email": "alice@acme.test"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "token" in body and body["token"]


def test_enabled_policy_queues_admin_request_instead_of_minting(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    # Alice enables the policy on her tenant.
    r = client.put(
        "/v1/settings/security/dual-control",
        headers=ALICE,
        json={"enabled": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True

    # Alice now requests an admin-scoped key. No token is returned;
    # the request is queued for peer approval.
    r = client.post(
        "/v1/api-keys",
        headers=ALICE,
        json={
            "label": "production-admin",
            "scopes": ["admin"],
            "justification": "Backfill audit pipeline through Q4 budget cycle.",
            "owner_email": "alice@acme.test",
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["pending_approval"] is True
    assert "token" not in body
    queued_id = body["request"]["id"]

    # The queue is visible to admins of the same tenant only.
    r = client.get("/v1/key-issuance-requests", headers=ALICE)
    assert r.status_code == 200
    listed = r.json()
    assert listed["policy_enabled"] is True
    assert any(req["id"] == queued_id for req in listed["requests"])

    # Now exercise the peer-approval gate directly against the store so
    # the two principals are distinguishable (env-key auth collapses every
    # API-key caller to the literal "api-key" principal).
    from shotclassify_store import dual_control_store

    seeded = dual_control_store.create_request(
        tenant_id="acme",
        requested_by="alice@acme.test",
        label="peer-gate-probe",
        scopes=["admin"],
        ttl_days=30,
        owner_email="alice@acme.test",
        justification="Probe the peer approval gate end to end.",
    )

    # Self-approval (same principal as requester) is rejected.
    from shotclassify_store.dual_control import DualControlError

    with pytest.raises(DualControlError, match="self-approval"):
        dual_control_store.approve(
            seeded.id, tenant_id="acme", approver="alice@acme.test"
        )

    # A different admin approving succeeds.
    decided = dual_control_store.approve(
        seeded.id, tenant_id="acme", approver="bob@acme.test"
    )
    assert decided.status == "approved"
    assert decided.decided_by == "bob@acme.test"

    # Re-approving a decided request is a conflict.
    with pytest.raises(DualControlError, match="already"):
        dual_control_store.approve(
            seeded.id, tenant_id="acme", approver="carol@acme.test"
        )


def test_enabled_policy_does_not_gate_non_admin_scopes(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.put(
        "/v1/settings/security/dual-control",
        headers=ALICE,
        json={"enabled": True},
    )
    # Non-admin scope is not in PROTECTED_SCOPES, so the key mints directly.
    r = client.post(
        "/v1/api-keys",
        headers=ALICE,
        json={"label": "read-only", "scopes": ["read:classifications"], "owner_email": "alice@acme.test"},
    )
    assert r.status_code == 201
    assert r.json().get("token")


def test_policy_is_strictly_tenant_scoped(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    # Acme enables the policy.
    client.put(
        "/v1/settings/security/dual-control",
        headers=ALICE,
        json={"enabled": True},
    )
    # Globex's admin is unaffected and mints normally.
    r = client.post(
        "/v1/api-keys",
        headers=GLOBEX,
        json={"label": "globex-ci", "scopes": ["admin"], "owner_email": "alice@acme.test"},
    )
    assert r.status_code == 201, r.text
    assert r.json().get("token")
    # Globex cannot see Acme's queue either (tenant isolation at list).
    r = client.get("/v1/key-issuance-requests", headers=GLOBEX)
    assert r.status_code == 200
    assert r.json()["requests"] == []


def test_short_justification_is_rejected(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.put(
        "/v1/settings/security/dual-control",
        headers=ALICE,
        json={"enabled": True},
    )
    r = client.post(
        "/v1/api-keys",
        headers=ALICE,
        json={"label": "x", "scopes": ["admin"], "justification": "too short", "owner_email": "x@x.test"},
    )
    assert r.status_code == 422
