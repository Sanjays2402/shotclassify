"""Per-tenant Customer-Managed Encryption Key (CMEK) reference.

Procurement-required surface that records which key in which customer
KMS encrypts the workspace's data at rest. Covers:

* GET returns the default (``disabled``, no provider, no URI) when
  nothing has been configured for the tenant.
* Non-admin (operator role) cannot mutate the declaration.
* Setting ``mode=required`` without a provider or key URI is rejected.
* Setting ``mode=required`` with a mismatched URI prefix is rejected.
* Round-trip: PUT, then GET reflects the new values + audit metadata.
* The declaration is strictly tenant-scoped: tenant A's record is
  invisible to tenant B and tenant B can configure its own independently.
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
        json.dumps(
            {
                "admin-a": "admin",
                "admin-b": "admin",
                "op-a": "operator",
            }
        ),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps(
            {
                "admin-a": "tenant-a",
                "admin-b": "tenant-b",
                "op-a": "tenant-a",
            }
        ),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "tenant-a")
    # Mutating route requires MFA step-up; the policy bypass is the
    # documented test seam, matching the other security_settings tests.
    monkeypatch.setenv("MFA_STEP_UP_REQUIRED", "false")
    monkeypatch.setenv("MFA_STEP_UP_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'cmek.db'}")
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


def _hdr(key: str) -> dict:
    return {"X-API-Key": key}


def test_default_cmek_is_disabled(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/settings/security/cmek", headers=_hdr("admin-a"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "tenant-a"
    assert body["mode"] == "disabled"
    assert body["provider"] is None
    assert body["key_uri"] is None
    assert "aws-kms" in body["available_providers"]
    assert set(body["available_modes"]) == {"disabled", "advisory", "required"}


def test_operator_cannot_mutate(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/cmek",
        headers={**_hdr("op-a"), "content-type": "application/json"},
        json={
            "provider": "aws-kms",
            "key_uri": "arn:aws:kms:us-west-2:111111111111:key/abcd",
            "mode": "required",
        },
    )
    assert r.status_code == 403, r.text


def test_required_mode_demands_provider_and_uri(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/cmek",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"provider": None, "key_uri": None, "mode": "required"},
    )
    assert r.status_code == 422, r.text


def test_uri_prefix_validated_against_provider(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/cmek",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={
            "provider": "aws-kms",
            # GCP-style URI on aws-kms must be rejected.
            "key_uri": "projects/p/locations/global/keyRings/r/cryptoKeys/k",
            "mode": "required",
        },
    )
    assert r.status_code == 422, r.text


def test_round_trip_sets_and_reads_back(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    arn = "arn:aws:kms:us-west-2:111111111111:key/00000000-0000-0000-0000-0000000000aa"
    r = c.put(
        "/v1/settings/security/cmek",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"provider": "aws-kms", "key_uri": arn, "mode": "required"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "aws-kms"
    assert body["key_uri"] == arn
    assert body["mode"] == "required"
    assert body["updated_at"]

    r = c.get("/v1/settings/security/cmek", headers=_hdr("admin-a"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "aws-kms"
    assert body["key_uri"] == arn
    assert body["mode"] == "required"


def test_disabling_clears_provider_and_uri(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    arn = "arn:aws:kms:us-west-2:111111111111:key/abcd"
    c.put(
        "/v1/settings/security/cmek",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"provider": "aws-kms", "key_uri": arn, "mode": "advisory"},
    )
    r = c.put(
        "/v1/settings/security/cmek",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"provider": "aws-kms", "key_uri": arn, "mode": "disabled"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "disabled"
    assert body["provider"] is None
    assert body["key_uri"] is None


def test_cmek_is_strictly_tenant_scoped(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    arn = "arn:aws:kms:us-west-2:111111111111:key/secret-a"
    r = c.put(
        "/v1/settings/security/cmek",
        headers={**_hdr("admin-a"), "content-type": "application/json"},
        json={"provider": "aws-kms", "key_uri": arn, "mode": "required"},
    )
    assert r.status_code == 200, r.text

    # Tenant B sees nothing tenant A configured.
    r = c.get("/v1/settings/security/cmek", headers=_hdr("admin-b"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "tenant-b"
    assert body["mode"] == "disabled"
    assert body["provider"] is None
    assert body["key_uri"] is None

    # Tenant B configures a different key; tenant A keeps its own.
    arn_b = "arn:aws:kms:eu-west-1:222222222222:key/secret-b"
    r = c.put(
        "/v1/settings/security/cmek",
        headers={**_hdr("admin-b"), "content-type": "application/json"},
        json={"provider": "aws-kms", "key_uri": arn_b, "mode": "required"},
    )
    assert r.status_code == 200, r.text

    a = c.get("/v1/settings/security/cmek", headers=_hdr("admin-a")).json()
    b = c.get("/v1/settings/security/cmek", headers=_hdr("admin-b")).json()
    assert a["key_uri"] == arn
    assert b["key_uri"] == arn_b
    assert a["key_uri"] != b["key_uri"]
