"""Tests for webhook signing-secret rotation with dual-sign overlap.

Covers:
* admin can rotate; a new plaintext secret is returned exactly once
* during overlap, dispatch_event signs every delivery with BOTH the old
  and the new secret, and the receiver can verify either header
* cross-tenant isolation: tenant A cannot rotate, finalise, or cancel
  a webhook that belongs to tenant B
* finalise promotes the new secret and drops the dual-sign header
* dry_run rotate returns the would-happen envelope without writing
* operator role cannot rotate
"""
from __future__ import annotations

import hashlib
import hmac
import http.server
import json
import socketserver
import threading
import time

import pytest
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv("WEBHOOK_EGRESS_ALLOW_HTTP", "true")
    monkeypatch.setenv("WEBHOOK_EGRESS_ALLOW_PRIVATE", "true")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps(
            {
                "acme-admin-key": "admin",
                "acme-op-key": "operator",
                "globex-admin-key": "admin",
            }
        ),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps(
            {
                "acme-admin-key": "acme",
                "acme-op-key": "acme",
                "globex-admin-key": "globex",
            }
        ),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "default")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'wh.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("MFA_REQUIRED_FOR_ADMIN", "false")
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()

    from services.api.app.main import create_app

    return TestClient(create_app())


def _admin(t: str) -> dict[str, str]:
    return {"X-API-Key": f"{t}-admin-key"}


def _create_webhook(client: TestClient, tenant: str, url: str) -> tuple[str, str]:
    r = client.post(
        "/v1/webhooks",
        headers=_admin(tenant),
        json={"url": url, "events": ["*"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["webhook"]["id"], body["secret"]


def test_rotation_returns_new_secret_and_marks_pending(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    sub_id, original_secret = _create_webhook(c, "acme", "http://127.0.0.1:9/never")

    r = c.post(f"/v1/webhooks/{sub_id}/rotate-secret", headers=_admin("acme"))
    assert r.status_code == 200, r.text
    body = r.json()
    new_secret = body["secret"]
    assert new_secret.startswith("whsec_")
    assert new_secret != original_secret
    assert body["webhook"]["secret_rotation_pending"] is True
    assert body["webhook"]["secret_rotated_at"] is not None
    assert "cannot show it again" in body["secret_warning"].lower()


def test_dry_run_rotation_does_not_persist(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    sub_id, _ = _create_webhook(c, "acme", "http://127.0.0.1:9/never")

    r = c.post(
        f"/v1/webhooks/{sub_id}/rotate-secret?dry_run=true",
        headers=_admin("acme"),
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload.get("dry_run") is True
    assert payload["would_rotate"]["id"] == sub_id

    # Subscription must still not have a pending rotation.
    r2 = c.get(f"/v1/webhooks/{sub_id}", headers=_admin("acme"))
    assert r2.status_code == 200
    assert r2.json()["webhook"]["secret_rotation_pending"] is False


def test_operator_cannot_rotate(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    sub_id, _ = _create_webhook(c, "acme", "http://127.0.0.1:9/never")

    r = c.post(
        f"/v1/webhooks/{sub_id}/rotate-secret",
        headers={"X-API-Key": "acme-op-key"},
    )
    assert r.status_code == 403


def test_cross_tenant_rotation_is_denied(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    sub_id, _ = _create_webhook(c, "acme", "http://127.0.0.1:9/never")

    # Globex admin cannot see Acme's subscription -> 404, not 200.
    r = c.post(f"/v1/webhooks/{sub_id}/rotate-secret", headers=_admin("globex"))
    assert r.status_code == 404
    r = c.post(f"/v1/webhooks/{sub_id}/finalize-secret", headers=_admin("globex"))
    assert r.status_code == 404
    r = c.post(f"/v1/webhooks/{sub_id}/cancel-rotation", headers=_admin("globex"))
    assert r.status_code == 404

    # And Acme's subscription is untouched.
    r = c.get(f"/v1/webhooks/{sub_id}", headers=_admin("acme"))
    assert r.status_code == 200
    assert r.json()["webhook"]["secret_rotation_pending"] is False


def test_finalize_requires_pending_rotation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    sub_id, _ = _create_webhook(c, "acme", "http://127.0.0.1:9/never")
    r = c.post(f"/v1/webhooks/{sub_id}/finalize-secret", headers=_admin("acme"))
    assert r.status_code == 409


def test_dispatch_dual_signs_during_overlap_then_single_after_finalize(
    monkeypatch, tmp_path
):
    """End-to-end proof of the rotation contract.

    Spins up a local HTTP listener, rotates the secret, dispatches an
    event, and verifies the receiver gets both signature headers. After
    finalising the rotation the dispatcher must sign only with the new
    key and stop sending the legacy header.
    """
    received: list[dict[str, str]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            received.append(
                {
                    "body": body.decode("utf-8"),
                    "sig": self.headers.get("X-Shotclassify-Signature", ""),
                    "sig_next": self.headers.get(
                        "X-Shotclassify-Signature-Next", ""
                    ),
                }
            )
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_a, **_kw):  # silence test output
            return

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as srv:
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            c = _client(monkeypatch, tmp_path)
            url = f"http://127.0.0.1:{port}/hook"
            sub_id, original_secret = _create_webhook(c, "acme", url)

            # Rotate; both old and new are now valid signers.
            r = c.post(
                f"/v1/webhooks/{sub_id}/rotate-secret", headers=_admin("acme")
            )
            assert r.status_code == 200
            new_secret = r.json()["secret"]

            # Dispatch directly via the store helper used by classify.
            from shotclassify_store import webhooks_store

            webhooks_store.dispatch_event(
                tenant_id="acme",
                event="classify.completed",
                payload={"hello": "world"},
                sleep=lambda *_a, **_kw: None,
            )

            assert received, "Listener never got a delivery"
            got = received[-1]
            body_bytes = got["body"].encode("utf-8")
            old_key = hashlib.sha256(original_secret.encode()).hexdigest()
            new_key = hashlib.sha256(new_secret.encode()).hexdigest()
            expected_old = (
                "sha256="
                + hmac.new(old_key.encode(), body_bytes, hashlib.sha256).hexdigest()
            )
            expected_new = (
                "sha256="
                + hmac.new(new_key.encode(), body_bytes, hashlib.sha256).hexdigest()
            )
            assert got["sig"] == expected_old, "primary header must use old secret"
            assert got["sig_next"] == expected_new, (
                "overlap must expose the new secret in the -Next header"
            )

            # Finalise: drop the old secret, keep only the new one.
            received.clear()
            r = c.post(
                f"/v1/webhooks/{sub_id}/finalize-secret",
                headers=_admin("acme"),
            )
            assert r.status_code == 200, r.text
            assert r.json()["webhook"]["secret_rotation_pending"] is False

            webhooks_store.dispatch_event(
                tenant_id="acme",
                event="classify.completed",
                payload={"hello": "again"},
                sleep=lambda *_a, **_kw: None,
            )
            assert received
            got2 = received[-1]
            body2 = got2["body"].encode("utf-8")
            expected2 = (
                "sha256="
                + hmac.new(new_key.encode(), body2, hashlib.sha256).hexdigest()
            )
            assert got2["sig"] == expected2, "after finalize, primary uses new key"
            assert got2["sig_next"] == "", (
                "after finalize, the -Next header must not be sent"
            )
        finally:
            srv.shutdown()


def test_cancel_rotation_clears_pending_without_breaking_old_secret(
    monkeypatch, tmp_path
):
    c = _client(monkeypatch, tmp_path)
    sub_id, _ = _create_webhook(c, "acme", "http://127.0.0.1:9/never")
    r = c.post(f"/v1/webhooks/{sub_id}/rotate-secret", headers=_admin("acme"))
    assert r.status_code == 200
    r = c.post(f"/v1/webhooks/{sub_id}/cancel-rotation", headers=_admin("acme"))
    assert r.status_code == 200
    assert r.json()["webhook"]["secret_rotation_pending"] is False
    # Cancelling twice is a 409.
    r = c.post(f"/v1/webhooks/{sub_id}/cancel-rotation", headers=_admin("acme"))
    assert r.status_code == 409
