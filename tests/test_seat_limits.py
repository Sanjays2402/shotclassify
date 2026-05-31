"""Per-workspace seat limits: enforcement on invites and member upserts,
cross-tenant isolation of the cap, and the GET/PUT /v1/workspace/seats
admin surface.

A seat = one active membership row OR one pending (non-expired,
non-revoked) invitation. Enforced inside the store so every code path
that adds a seat is gated (manual invite, SSO auto-join, SCIM).
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
        json.dumps({"admin-key": "acme", "other-admin-key": "globex"}),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "acme")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'seats.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("MFA_STEP_UP_REQUIRED", "false")
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


def test_seats_default_unlimited(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/v1/workspace/seats", headers=ACME)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "acme"
    assert body["seat_limit"] is None
    assert body["seats_available"] is None
    assert body["seats_in_use"]["total"] == 0


def test_set_seat_limit_then_blocks_new_invite(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    # Cap acme at 1 seat.
    r = client.put("/v1/workspace/seats", headers=ACME, json={"seat_limit": 1})
    assert r.status_code == 200, r.text
    assert r.json()["seat_limit"] == 1

    # First invite consumes the only seat.
    r = client.post(
        "/v1/invitations",
        headers=ACME,
        json={"email": "alice@example.com", "role": "operator"},
    )
    assert r.status_code == 201, r.text

    # Seats endpoint reflects the new usage.
    r = client.get("/v1/workspace/seats", headers=ACME)
    assert r.json()["seats_in_use"]["total"] == 1
    assert r.json()["seats_available"] == 0

    # Second invite is rejected with 402 and a structured payload.
    r = client.post(
        "/v1/invitations",
        headers=ACME,
        json={"email": "bob@example.com", "role": "operator"},
    )
    assert r.status_code == 402, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "seat_limit_exceeded"
    assert detail["seat_limit"] == 1
    assert detail["seats_in_use"] == 1

    # Manual member upsert via PUT /v1/members/{principal} is also blocked.
    r = client.put(
        "/v1/members/bob@example.com",
        headers=ACME,
        json={"role": "viewer"},
    )
    assert r.status_code == 402, r.text


def test_seat_limit_is_tenant_scoped(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    # Cap acme tightly.
    r = client.put("/v1/workspace/seats", headers=ACME, json={"seat_limit": 1})
    assert r.status_code == 200
    # Globex should still see the default unlimited cap; the acme cap
    # must not leak across tenants.
    r = client.get("/v1/workspace/seats", headers=GLOBEX)
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == "globex"
    assert body["seat_limit"] is None
    # And globex can invite freely even though acme is at its cap.
    r = client.post(
        "/v1/invitations",
        headers=GLOBEX,
        json={"email": "carol@example.com", "role": "operator"},
    )
    assert r.status_code == 201, r.text


def test_role_change_on_existing_member_does_not_consume_seat(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    from shotclassify_store import memberships_store

    # Two existing members on acme.
    memberships_store.upsert_member(
        tenant_id="acme", principal="alice@example.com", role="operator"
    )
    memberships_store.upsert_member(
        tenant_id="acme", principal="bob@example.com", role="viewer"
    )

    # Cap is now lower than current usage: lowering past usage is allowed,
    # it only blocks NEW seats.
    r = client.put("/v1/workspace/seats", headers=ACME, json={"seat_limit": 2})
    assert r.status_code == 200

    # Promoting an existing member must succeed -- no new seat used.
    r = client.put(
        "/v1/members/bob@example.com",
        headers=ACME,
        json={"role": "operator"},
    )
    assert r.status_code == 200, r.text


def test_set_seat_limit_rejects_invalid(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.put("/v1/workspace/seats", headers=ACME, json={"seat_limit": 0})
    assert r.status_code == 422
    r = client.put("/v1/workspace/seats", headers=ACME, json={"seat_limit": -5})
    assert r.status_code == 422


def test_set_seat_limit_null_means_unlimited(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.put("/v1/workspace/seats", headers=ACME, json={"seat_limit": 1})
    r = client.put("/v1/workspace/seats", headers=ACME, json={"seat_limit": None})
    assert r.status_code == 200
    assert r.json()["seat_limit"] is None
    # And invites flow again.
    for email in ("a@example.com", "b@example.com", "c@example.com"):
        rr = client.post(
            "/v1/invitations",
            headers=ACME,
            json={"email": email, "role": "viewer"},
        )
        assert rr.status_code == 201, rr.text
