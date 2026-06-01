"""Security event webhook fan-out.

Verifies that sensitive admin actions land on webhook subscribers whose
event filter matches, without leaking across tenants. Owners can wire
admin alerts into their own SIEM/Slack/PagerDuty without standing up a
separate ingestion endpoint.
"""
from __future__ import annotations

import http.server
import json
import socketserver
import threading
import time

import pytest
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("WEBHOOK_EGRESS_ALLOW_HTTP", "true")
    monkeypatch.setenv("WEBHOOK_EGRESS_ALLOW_PRIVATE", "true")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps(
            {
                "acme-admin-key": "admin",
                "globex-admin-key": "admin",
            }
        ),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps(
            {
                "acme-admin-key": "acme",
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


class _Collector(http.server.BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}
        _Collector.received.append(
            {
                "event": self.headers.get("X-Shotclassify-Event"),
                "subscription": self.headers.get("X-Shotclassify-Subscription"),
                "payload": payload,
            }
        )
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a, **k):  # quiet test output
        return


@pytest.fixture
def collector():
    _Collector.received = []
    srv = socketserver.TCPServer(("127.0.0.1", 0), _Collector)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield f"http://127.0.0.1:{port}/hook", _Collector
    finally:
        srv.shutdown()
        srv.server_close()


def _wait(collector_cls, n: int, timeout: float = 3.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(collector_cls.received) >= n:
            return
        time.sleep(0.05)


def test_security_events_listed_in_allowed_events(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/webhooks", headers={"X-API-Key": "acme-admin-key"})
    assert r.status_code == 200, r.text
    allowed = r.json()["allowed_events"]
    # Security events are advertised to subscribers; classify events remain.
    assert "classify.completed" in allowed
    assert "security.api_key_created" in allowed
    assert "security.role_changed" in allowed
    assert "security.support_access_granted" in allowed
    assert "*" in allowed


def test_api_key_creation_fires_security_webhook(monkeypatch, tmp_path, collector):
    url, cls = collector
    c = _client(monkeypatch, tmp_path)
    # Subscribe acme to the api_key_created event.
    sub = c.post(
        "/v1/webhooks",
        headers={"X-API-Key": "acme-admin-key"},
        json={"url": url, "events": ["security.api_key_created"]},
    )
    assert sub.status_code == 200, sub.text
    sub_id = sub.json()["webhook"]["id"]

    # Create an API key as an admin action.
    r = c.post(
        "/v1/api-keys",
        headers={"X-API-Key": "acme-admin-key"},
        json={"label": "ci-key", "scopes": ["read:classifications"], "owner_email": "ops@acme.test"},
    )
    assert r.status_code == 201, r.text

    _wait(cls, 1)
    assert len(cls.received) >= 1, cls.received
    delivered = cls.received[0]
    assert delivered["event"] == "security.api_key_created"
    assert delivered["subscription"] == sub_id
    assert delivered["payload"]["tenant_id"] == "acme"
    assert delivered["payload"]["method"] == "POST"
    assert delivered["payload"]["path"] == "/v1/api-keys"
    assert delivered["payload"]["status_code"] == 201


def test_security_event_does_not_leak_across_tenants(monkeypatch, tmp_path, collector):
    url, cls = collector
    c = _client(monkeypatch, tmp_path)
    # globex subscribes to *all* security events.
    sub = c.post(
        "/v1/webhooks",
        headers={"X-API-Key": "globex-admin-key"},
        json={"url": url, "events": ["*"]},
    )
    assert sub.status_code == 200, sub.text

    # acme performs an admin action.
    r = c.post(
        "/v1/api-keys",
        headers={"X-API-Key": "acme-admin-key"},
        json={"label": "acme-ci", "scopes": ["read:classifications"], "owner_email": "ops@acme.test"},
    )
    assert r.status_code == 201, r.text

    # globex's subscriber must not receive acme's event.
    time.sleep(0.5)
    assert all(
        d["payload"].get("tenant_id") != "acme" for d in cls.received
    ), cls.received


def test_failed_admin_action_does_not_fire_event(monkeypatch, tmp_path, collector):
    url, cls = collector
    c = _client(monkeypatch, tmp_path)
    sub = c.post(
        "/v1/webhooks",
        headers={"X-API-Key": "acme-admin-key"},
        json={"url": url, "events": ["*"]},
    )
    assert sub.status_code == 200

    # Invalid payload -> 422; no security event should fan out.
    r = c.post(
        "/v1/api-keys",
        headers={"X-API-Key": "acme-admin-key"},
        json={},
    )
    assert r.status_code >= 400
    time.sleep(0.5)
    # Only the subscription-created event (which we also emit) may show up.
    # Filter that out; no api_key_created should be present.
    api_key_events = [
        d for d in cls.received if d["event"] == "security.api_key_created"
    ]
    assert api_key_events == [], cls.received
