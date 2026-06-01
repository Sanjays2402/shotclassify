"""Workspace access-review campaigns (SOC2 CC6.3 / ISO 27001 A.9.2.5).

Covers the deal-blocker properties enterprise procurement asks about:

* an admin in tenant A can open a review, decide each item, dry-run
  preview the apply, then apply and revoke the chosen members
* an admin in tenant B cannot see, decide on, or apply a review owned by
  tenant A: cross-tenant access returns 404 (same as a missing review)
  so the existence of a review id never leaks across the workspace
  boundary
* applying a review that would leave the workspace with zero admins is
  refused, even when every individual decision is internally valid
* the CSV export carries the seal (status, applied_at, decisions) so
  auditors can attach it to evidence packages
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "acme-admin")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps({"globex-admin": "admin"}),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps({"acme-admin": "acme", "globex-admin": "globex"}),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "acme")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'ar.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db, init_db, memberships_store

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    init_db()

    # Seed memberships so list_members() returns real rows for the snapshot.
    # The API-key principals themselves must be members and admins so the
    # last-admin guard kicks in correctly.
    memberships_store.upsert_member(
        tenant_id="acme", principal="acme-admin", role="admin",
        invited_by="bootstrap", enforce_seat_limit=False,
    )
    memberships_store.upsert_member(
        tenant_id="acme", principal="alice@example.com", role="operator",
        invited_by="acme-admin", enforce_seat_limit=False,
    )
    memberships_store.upsert_member(
        tenant_id="acme", principal="bob@example.com", role="viewer",
        invited_by="acme-admin", enforce_seat_limit=False,
    )
    memberships_store.upsert_member(
        tenant_id="globex", principal="globex-admin", role="admin",
        invited_by="bootstrap", enforce_seat_limit=False,
    )

    from services.api.app.main import create_app

    return TestClient(create_app())


ACME = {"X-API-Key": "acme-admin"}
GLOBEX = {"X-API-Key": "globex-admin"}


def _open_review(client) -> dict:
    r = client.post(
        "/v1/access-reviews",
        headers=ACME,
        json={"title": "2026 Q2 access review"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["review"]["status"] == "open"
    assert body["review"]["tenant_id"] == "acme"
    # One item per seeded acme member.
    principals = {i["principal"] for i in body["items"]}
    assert principals == {"acme-admin", "alice@example.com", "bob@example.com"}
    return body


def test_open_snapshot_decide_apply_full_lifecycle(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    body = _open_review(client)
    review_id = body["review"]["id"]

    # Two open reviews at once is refused so the audit trail stays clean.
    dup = client.post(
        "/v1/access-reviews", headers=ACME, json={"title": "dup"}
    )
    assert dup.status_code == 409

    items = {i["principal"]: i for i in body["items"]}

    # Decide: keep admin and alice, revoke bob.
    for principal, decision in (
        ("acme-admin", "keep"),
        ("alice@example.com", "keep"),
        ("bob@example.com", "revoke"),
    ):
        r = client.put(
            f"/v1/access-reviews/{review_id}/items/{items[principal]['id']}",
            headers=ACME,
            json={"decision": decision, "note": f"verified-{principal}"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["item"]["decision"] == decision

    # Dry-run preview must report exactly what apply will do.
    pre = client.post(
        f"/v1/access-reviews/{review_id}/apply?dry_run=true", headers=ACME
    )
    assert pre.status_code == 200, pre.text
    pre_body = pre.json()
    assert pre_body.get("dry_run") is True
    assert pre_body["would_revoke"] == ["bob@example.com"]
    assert sorted(pre_body["would_keep"]) == ["acme-admin", "alice@example.com"]
    assert pre_body["blocker"] is None

    # Bob is still on the roster before apply.
    members_before = client.get("/v1/members", headers=ACME).json()
    assert any(
        m["principal"] == "bob@example.com" for m in members_before["members"]
    )

    # Apply for real.
    done = client.post(f"/v1/access-reviews/{review_id}/apply", headers=ACME)
    assert done.status_code == 200, done.text
    sealed = done.json()["review"]
    assert sealed["status"] == "applied"
    assert sealed["applied_by"] == "api-key"
    assert sealed["applied_at"]

    # Bob is gone from the roster.
    members_after = client.get("/v1/members", headers=ACME).json()
    assert not any(
        m["principal"] == "bob@example.com" for m in members_after["members"]
    )

    # A second apply is refused (review is sealed).
    again = client.post(f"/v1/access-reviews/{review_id}/apply", headers=ACME)
    assert again.status_code == 409


def test_cross_tenant_access_is_404_not_403(monkeypatch, tmp_path):
    """Critical regression: tenant B must not be able to read, decide on,
    apply, cancel, or export a review owned by tenant A. The response must
    be 404, not 403, so the existence of the id does not leak.
    """
    client = _client(monkeypatch, tmp_path)
    body = _open_review(client)
    review_id = body["review"]["id"]
    item_id = body["items"][0]["id"]

    # Read paths.
    r = client.get(f"/v1/access-reviews/{review_id}", headers=GLOBEX)
    assert r.status_code == 404
    r = client.get(
        f"/v1/access-reviews/{review_id}/export.csv", headers=GLOBEX
    )
    assert r.status_code == 404

    # Listing from tenant B never reveals tenant A's review id.
    r = client.get("/v1/access-reviews", headers=GLOBEX)
    assert r.status_code == 200
    listed_ids = [rv["id"] for rv in r.json()["reviews"]]
    assert review_id not in listed_ids

    # Mutation paths must fail too.
    r = client.put(
        f"/v1/access-reviews/{review_id}/items/{item_id}",
        headers=GLOBEX,
        json={"decision": "revoke"},
    )
    assert r.status_code == 404
    r = client.post(
        f"/v1/access-reviews/{review_id}/apply", headers=GLOBEX
    )
    assert r.status_code == 404
    r = client.post(
        f"/v1/access-reviews/{review_id}/cancel", headers=GLOBEX
    )
    assert r.status_code == 404

    # And tenant A's review is untouched: still open with all items pending.
    r = client.get(f"/v1/access-reviews/{review_id}", headers=ACME)
    assert r.status_code == 200
    assert r.json()["review"]["status"] == "open"


def test_apply_refuses_to_revoke_the_last_admin(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    body = _open_review(client)
    review_id = body["review"]["id"]
    admin_item = next(
        i for i in body["items"] if i["principal"] == "acme-admin"
    )

    # Marking the sole admin for revocation is allowed at decision time
    # (a reviewer can change their mind), but apply must refuse.
    r = client.put(
        f"/v1/access-reviews/{review_id}/items/{admin_item['id']}",
        headers=ACME,
        json={"decision": "revoke"},
    )
    assert r.status_code == 200

    # Dry-run flags the blocker.
    pre = client.post(
        f"/v1/access-reviews/{review_id}/apply?dry_run=true", headers=ACME
    )
    assert pre.status_code == 200
    assert pre.json()["blocker"] == "acme-admin"

    # Apply is refused with the structured last-admin error.
    done = client.post(f"/v1/access-reviews/{review_id}/apply", headers=ACME)
    assert done.status_code == 409
    detail = done.json()["detail"]
    assert detail["error"] == "access_review_last_admin"
    assert detail["principal"] == "acme-admin"

    # Acme-admin must still be an admin afterwards.
    members = client.get("/v1/members", headers=ACME).json()
    admin_roles = [
        m["role"] for m in members["members"] if m["principal"] == "acme-admin"
    ]
    assert admin_roles == ["admin"]


def test_csv_export_carries_the_seal(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    body = _open_review(client)
    review_id = body["review"]["id"]
    items = {i["principal"]: i for i in body["items"]}

    for principal in ("acme-admin", "alice@example.com", "bob@example.com"):
        decision = "revoke" if principal == "bob@example.com" else "keep"
        client.put(
            f"/v1/access-reviews/{review_id}/items/{items[principal]['id']}",
            headers=ACME,
            json={"decision": decision},
        )

    apply_r = client.post(
        f"/v1/access-reviews/{review_id}/apply", headers=ACME
    )
    assert apply_r.status_code == 200

    r = client.get(
        f"/v1/access-reviews/{review_id}/export.csv", headers=ACME
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    text = r.text
    # Header + every principal row.
    assert "review_id,tenant_id,title,status" in text
    assert "bob@example.com" in text and ",revoke," in text
    assert "alice@example.com" in text and ",keep," in text
    assert "applied" in text
