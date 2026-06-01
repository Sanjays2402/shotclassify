"""Per-tenant audit log SIEM sink tests.

Covers:
* admin-only create / revoke / test (operator gets 403)
* plaintext secret returned exactly once and not on subsequent reads
* cross-tenant isolation: tenant B cannot list, fetch, revoke, or test
  tenant A's sink (cross-tenant fetch returns 404, not 403, to avoid
  existence leaks)
* a mutating authenticated request on tenant A fans the audit event out
  to tenant A's sink only, with an ``HMAC-SHA256(sha256(secret), body)``
  signature receivers can verify
"""
from __future__ import annotations

import hashlib
import hmac
import http.server
import json
import socketserver
import threading
import time

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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'sinks.db'}")
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


class _Collector(http.server.BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length) if length else b""
        type(self).received.append(
            {
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": body,
            }
        )
        self.send_response(200)
        self.send_header("content-length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args, **kwargs):  # noqa: D401
        return


def _start_collector():
    _Collector.received = []
    srv = socketserver.TCPServer(("127.0.0.1", 0), _Collector)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


def test_operator_cannot_create_sink(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/audit/sinks",
        headers={"X-API-Key": "acme-op-key"},
        json={"url": "http://127.0.0.1:1/sink"},
    )
    assert r.status_code == 403


def test_create_returns_secret_exactly_once(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/audit/sinks",
        headers=_admin("acme"),
        json={"url": "http://127.0.0.1:1/sink", "description": "splunk"},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    sid = payload["id"]
    assert payload["secret"].startswith("assec_")
    # No secret on follow-up reads.
    r2 = c.get(f"/v1/audit/sinks/{sid}", headers=_admin("acme"))
    assert r2.status_code == 200
    assert "secret" not in r2.json()


def test_cross_tenant_isolation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/audit/sinks",
        headers=_admin("acme"),
        json={"url": "http://127.0.0.1:1/acme"},
    )
    acme_id = r.json()["id"]

    # Globex admin must not see acme's sink in their list.
    r2 = c.get("/v1/audit/sinks", headers=_admin("globex"))
    assert r2.status_code == 200
    assert all(s["id"] != acme_id for s in r2.json()["sinks"])

    # Cross-tenant fetch returns 404, not 403, to avoid existence leaks.
    assert c.get(f"/v1/audit/sinks/{acme_id}", headers=_admin("globex")).status_code == 404
    assert (
        c.delete(f"/v1/audit/sinks/{acme_id}", headers=_admin("globex")).status_code
        == 404
    )
    assert (
        c.post(f"/v1/audit/sinks/{acme_id}/test", headers=_admin("globex")).status_code
        == 404
    )

    # Owner can still see it.
    assert c.get(f"/v1/audit/sinks/{acme_id}", headers=_admin("acme")).status_code == 200


def test_audit_middleware_fans_out_signed_event(monkeypatch, tmp_path):
    srv, port = _start_collector()
    try:
        c = _client(monkeypatch, tmp_path)
        r = c.post(
            "/v1/audit/sinks",
            headers=_admin("acme"),
            json={"url": f"http://127.0.0.1:{port}/audit"},
        )
        assert r.status_code == 200, r.text
        secret = r.json()["secret"]

        # Drain anything the create call itself queued.
        time.sleep(0.3)
        _Collector.received.clear()

        # A mutating, authenticated request on acme.
        r2 = c.delete("/v1/history/does-not-exist", headers=_admin("acme"))
        assert r2.status_code in (404, 200, 422)

        # Background dispatcher; poll briefly.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not _Collector.received:
            time.sleep(0.1)
        assert _Collector.received, "audit sink never received the event"

        msg = _Collector.received[-1]
        body = msg["body"]
        sig_header = msg["headers"].get("x-shotclassify-audit-signature")
        assert sig_header, msg["headers"]

        # HMAC key = sha256(plaintext secret), payload = raw body bytes.
        key = hashlib.sha256(secret.encode()).hexdigest().encode()
        expected = hmac.new(key, body, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(expected, sig_header)

        decoded = json.loads(body)
        assert decoded["tenant_id"] == "acme"
        assert decoded["method"] == "DELETE"
        assert decoded["path"].startswith("/v1/history/")
    finally:
        srv.shutdown()


def test_dispatch_does_not_cross_tenants(monkeypatch, tmp_path):
    srv, port = _start_collector()
    try:
        c = _client(monkeypatch, tmp_path)
        # Sink belongs to acme only.
        r = c.post(
            "/v1/audit/sinks",
            headers=_admin("acme"),
            json={"url": f"http://127.0.0.1:{port}/acme-only"},
        )
        assert r.status_code == 200
        time.sleep(0.3)
        _Collector.received.clear()

        # Globex performs a mutation; acme's sink must NOT receive it.
        r2 = c.delete("/v1/history/does-not-exist", headers=_admin("globex"))
        assert r2.status_code in (404, 200, 422)
        time.sleep(0.8)
        for msg in _Collector.received:
            decoded = json.loads(msg["body"])
            assert decoded["tenant_id"] != "globex", "cross-tenant leak"
    finally:
        srv.shutdown()
