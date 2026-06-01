"""Data Subject Access Requests: cross-tenant isolation + lifecycle.

These tests are the procurement-review proof that one workspace cannot
read, mutate, or fulfill another workspace's DSAR tickets, and that the
state machine refuses out-of-order transitions.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _bootstrap(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "key-a")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps({"key-a": "admin", "key-b": "admin"}),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps({"key-a": "tenant-a", "key-b": "tenant-b"}),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "tenant-a")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'dsar.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("IP_ALLOWLIST_ENABLED", "false")
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


def _auth(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


def test_public_intake_creates_ticket_in_target_tenant(monkeypatch, tmp_path):
    c = _bootstrap(monkeypatch, tmp_path)
    r = c.post(
        "/v1/trust/dsar",
        json={
            "tenant_id": "tenant-a",
            "request_type": "access",
            "subject_email": "Subject@Example.com",
            "subject_name": "Test Subject",
            "description": "Please export all data you hold on me.",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "received"
    assert body["tenant_id"] == "tenant-a"
    assert body["id"].startswith("dsr_")
    # Admin of tenant-a can see it.
    a = c.get("/v1/dsar", headers=_auth("key-a"))
    assert a.status_code == 200
    items = a.json()["items"]
    assert len(items) == 1
    assert items[0]["subject_email"] == "Subject@Example.com"
    assert items[0]["subject_identifier"] == "subject@example.com"


def test_cross_tenant_admin_cannot_see_or_mutate_ticket(monkeypatch, tmp_path):
    c = _bootstrap(monkeypatch, tmp_path)
    # File for tenant-a.
    r = c.post(
        "/v1/trust/dsar",
        json={
            "tenant_id": "tenant-a",
            "request_type": "erasure",
            "subject_email": "ghost@example.com",
        },
    )
    assert r.status_code == 201
    rid = r.json()["id"]

    # tenant-b admin cannot list it.
    b_list = c.get("/v1/dsar", headers=_auth("key-b"))
    assert b_list.status_code == 200
    assert b_list.json()["items"] == []

    # tenant-b admin gets 404 (not 200) when trying to fetch by id.
    b_get = c.get(f"/v1/dsar/{rid}", headers=_auth("key-b"))
    assert b_get.status_code == 404

    # tenant-b admin cannot transition it.
    b_patch = c.patch(
        f"/v1/dsar/{rid}",
        headers=_auth("key-b"),
        json={"status": "verified"},
    )
    assert b_patch.status_code == 404

    # tenant-b admin cannot fulfill it.
    b_fulfill = c.post(f"/v1/dsar/{rid}/fulfill", headers=_auth("key-b"))
    assert b_fulfill.status_code == 404

    # tenant-a admin still has access.
    a_get = c.get(f"/v1/dsar/{rid}", headers=_auth("key-a"))
    assert a_get.status_code == 200
    assert a_get.json()["tenant_id"] == "tenant-a"


def test_state_machine_rejects_skipping_verified(monkeypatch, tmp_path):
    c = _bootstrap(monkeypatch, tmp_path)
    r = c.post(
        "/v1/trust/dsar",
        json={
            "tenant_id": "tenant-a",
            "request_type": "access",
            "subject_email": "x@example.com",
        },
    )
    rid = r.json()["id"]
    # received -> closed is not allowed.
    bad = c.patch(
        f"/v1/dsar/{rid}",
        headers=_auth("key-a"),
        json={"status": "closed"},
    )
    assert bad.status_code == 409
    # received -> verified is allowed.
    ok = c.patch(
        f"/v1/dsar/{rid}",
        headers=_auth("key-a"),
        json={"status": "verified", "note": "ID confirmed via email"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "verified"
    history = ok.json()["state_history"]
    assert any(h["to"] == "verified" for h in history)


def test_access_fulfillment_requires_verified(monkeypatch, tmp_path):
    c = _bootstrap(monkeypatch, tmp_path)
    r = c.post(
        "/v1/trust/dsar",
        json={
            "tenant_id": "tenant-a",
            "request_type": "access",
            "subject_email": "x@example.com",
        },
    )
    rid = r.json()["id"]
    bad = c.post(f"/v1/dsar/{rid}/fulfill", headers=_auth("key-a"))
    assert bad.status_code == 409
    c.patch(
        f"/v1/dsar/{rid}",
        headers=_auth("key-a"),
        json={"status": "verified"},
    )
    ok = c.post(f"/v1/dsar/{rid}/fulfill", headers=_auth("key-a"))
    assert ok.status_code == 200
    body = ok.json()
    assert body["subject_email"] == "x@example.com"
    assert "classifications" in body
    assert "audit_log" in body
    # And the ticket flipped to fulfilled.
    final = c.get(f"/v1/dsar/{rid}", headers=_auth("key-a"))
    assert final.json()["status"] == "fulfilled"
    assert final.json()["fulfillment_summary"]["action"] == "access_export"


def test_public_intake_validates_input(monkeypatch, tmp_path):
    c = _bootstrap(monkeypatch, tmp_path)
    bad_type = c.post(
        "/v1/trust/dsar",
        json={
            "tenant_id": "tenant-a",
            "request_type": "weird",
            "subject_email": "x@example.com",
        },
    )
    assert bad_type.status_code == 422
    bad_email = c.post(
        "/v1/trust/dsar",
        json={
            "tenant_id": "tenant-a",
            "request_type": "access",
            "subject_email": "not-an-email",
        },
    )
    assert bad_email.status_code == 422
    missing_tenant = c.post(
        "/v1/trust/dsar",
        json={
            "request_type": "access",
            "subject_email": "x@example.com",
        },
    )
    assert missing_tenant.status_code == 422
