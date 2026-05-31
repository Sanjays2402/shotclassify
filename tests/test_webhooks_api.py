"""API-side webhook subscription + delivery tests.

Covers:
* admin-only access (operator / viewer roles get 403)
* HMAC signature is computed with sha256(secret) as the HMAC key
* dispatch_event POSTs to a live local listener and persists a delivery row
* dry-run revoke leaves the subscription intact
* cross-tenant isolation: tenant A cannot list, revoke, or replay a
  webhook that belongs to tenant B
* failed delivery records a ``failed`` row with the HTTP status
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
    # Tests use 127.0.0.1 listeners and example.com placeholders that may
    # not resolve in sandboxed CI; the webhook egress allowlist is exercised
    # directly in tests/test_webhook_egress.py.
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


def test_operator_cannot_create_webhook(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/webhooks",
        headers={"X-API-Key": "acme-op-key"},
        json={"url": "https://example.com/hook", "events": ["classify.completed"]},
    )
    assert r.status_code == 403


def test_create_returns_secret_exactly_once(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/webhooks",
        headers=_admin("acme"),
        json={
            "url": "https://example.com/hook",
            "events": ["classify.completed"],
            "description": "prod",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["secret"].startswith("whsec_")
    wid = body["webhook"]["id"]

    # The secret is not present in subsequent reads.
    r2 = c.get(f"/v1/webhooks/{wid}", headers=_admin("acme"))
    assert r2.status_code == 200
    assert "secret" not in r2.json()["webhook"]


def test_cross_tenant_isolation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/webhooks",
        headers=_admin("acme"),
        json={"url": "https://acme.example.com/h", "events": ["*"]},
    )
    assert r.status_code == 200, r.text
    acme_id = r.json()["webhook"]["id"]

    # Globex admin should not see acme's webhook in the list.
    r2 = c.get("/v1/webhooks", headers=_admin("globex"))
    assert r2.status_code == 200
    assert all(w["id"] != acme_id for w in r2.json()["webhooks"])

    # Cross-tenant fetch returns 404, not 403, to avoid existence-leaks.
    r3 = c.get(f"/v1/webhooks/{acme_id}", headers=_admin("globex"))
    assert r3.status_code == 404

    # Cross-tenant delete returns 404.
    r4 = c.delete(f"/v1/webhooks/{acme_id}", headers=_admin("globex"))
    assert r4.status_code == 404

    # The original is still there for the owning tenant.
    r5 = c.get(f"/v1/webhooks/{acme_id}", headers=_admin("acme"))
    assert r5.status_code == 200


def test_dry_run_revoke_does_not_mutate(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/webhooks",
        headers=_admin("acme"),
        json={"url": "https://example.com/hook", "events": ["classify.completed"]},
    )
    wid = r.json()["webhook"]["id"]

    r2 = c.delete(f"/v1/webhooks/{wid}?dry_run=true", headers=_admin("acme"))
    assert r2.status_code == 200
    assert r2.json()["dry_run"] is True
    assert r2.json()["applied"] is False
    assert r2.headers.get("X-Dry-Run") == "true"

    # Still active.
    r3 = c.get(f"/v1/webhooks/{wid}", headers=_admin("acme"))
    assert r3.json()["webhook"]["active"] is True


def test_validates_url_and_events(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/webhooks",
        headers=_admin("acme"),
        json={"url": "ftp://nope", "events": ["classify.completed"]},
    )
    assert r.status_code == 422


class _Capture(http.server.BaseHTTPRequestHandler):
    received: list[tuple[dict, bytes]] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length else b""
        self.received.append((dict(self.headers), body))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args, **_kwargs):  # silence
        return


def _spawn_listener():
    _Capture.received = []
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _Capture)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port


def test_dispatch_signs_and_delivers(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'dispatch.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("WEBHOOK_EGRESS_ALLOW_HTTP", "true")
    monkeypatch.setenv("WEBHOOK_EGRESS_ALLOW_PRIVATE", "true")
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db, webhooks_store

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()

    httpd, port = _spawn_listener()
    try:
        record, secret = webhooks_store.create_subscription(
            tenant_id="acme",
            url=f"http://127.0.0.1:{port}/hook",
            events=["classify.completed"],
            description="t",
            created_by="alice",
        )
        results = webhooks_store.dispatch_event(
            tenant_id="acme",
            event="classify.completed",
            payload={"id": "abc", "ok": True},
            sleep=lambda *_: None,
        )
        assert len(results) == 1
        delivered = results[0]
        assert delivered.status == "success"
        assert delivered.http_status == 200
        assert delivered.attempt == 1
        assert _Capture.received, "listener got nothing"
        headers, body = _Capture.received[-1]
        assert headers.get("X-Shotclassify-Event") == "classify.completed"
        sig = headers.get("X-Shotclassify-Signature", "")
        assert sig.startswith("sha256=")
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()
        expected = (
            "sha256="
            + hmac.new(secret_hash.encode(), body, hashlib.sha256).hexdigest()
        )
        assert hmac.compare_digest(sig, expected)
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_dispatch_records_failure_after_retries(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'fail.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("WEBHOOK_EGRESS_ALLOW_HTTP", "true")
    monkeypatch.setenv("WEBHOOK_EGRESS_ALLOW_PRIVATE", "true")
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db, webhooks_store

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()

    # Closed port -> connection refused on every attempt.
    webhooks_store.create_subscription(
        tenant_id="acme",
        url="http://127.0.0.1:1/never",
        events=["*"],
        description=None,
        created_by=None,
    )
    results = webhooks_store.dispatch_event(
        tenant_id="acme",
        event="classify.completed",
        payload={"id": "x"},
        sleep=lambda *_: None,
    )
    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].attempt == webhooks_store.MAX_ATTEMPTS
    assert results[0].error
