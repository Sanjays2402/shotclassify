"""End-to-end smoke test for the web webhooks store and dispatch.

Spins a tiny local HTTP listener, registers a webhook pointing at it, and
verifies the signed POST arrives with a valid HMAC signature. Also exercises
the file fallback assertions used when tsx/ts-node are not installed.
"""
from __future__ import annotations

import hmac
import hashlib
import http.server
import json
import os
import shutil
import socket
import socketserver
import subprocess
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (WEB / "node_modules").exists(),
    reason="node + web/node_modules required",
)


class _Handler(http.server.BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length)
        self.__class__.received.append(
            {
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": body.decode("utf-8", "replace"),
            }
        )
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *_args):  # silence
        return


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_webhook_files_exist() -> None:
    # File contract checks. Always run, regardless of tsx availability.
    assert (WEB / "lib" / "webhooks.ts").exists()
    assert (WEB / "app" / "api" / "webhooks" / "route.ts").exists()
    assert (WEB / "app" / "api" / "webhooks" / "[id]" / "route.ts").exists()
    assert (WEB / "app" / "webhooks" / "page.tsx").exists()
    classify = (WEB / "app" / "api" / "classify" / "route.ts").read_text()
    assert "dispatchEvent" in classify
    v1 = (WEB / "app" / "v1" / "classify" / "route.ts").read_text()
    assert "dispatchEvent" in v1


def test_webhook_dispatch_signs_and_delivers(tmp_path: Path) -> None:
    has_tsx = (WEB / "node_modules" / "tsx").exists()
    if not has_tsx:
        pytest.skip("tsx not installed; file-contract test covers structure")

    port = _free_port()
    _Handler.received = []
    httpd = socketserver.TCPServer(("127.0.0.1", port), _Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        url = f"http://127.0.0.1:{port}/hook"
        script = r"""
import Module from 'node:module';
const orig = Module.prototype.require;
Module.prototype.require = function(id) {
  if (id === 'server-only') return {};
  return orig.apply(this, arguments);
};
const wh = await import('./lib/webhooks.ts');
const ks = await import('./lib/keystore-core.ts');
const h = await wh.createWebhook({ url: process.env.HOOK_URL, description: 'test' });
const d = await wh.testFire(h);
// dispatchEvent gained a workspace_id arg in a later tick; pass the same
// default workspace createWebhook backfills so the fan-out finds the hook.
await wh.dispatchEvent(ks.DEFAULT_WORKSPACE_ID, 'classify.completed', { hello: 'world' });
// Give the fire-and-forget a moment to flush.
await new Promise(r => setTimeout(r, 400));
const list = await wh.listDeliveries(h.id, 10);
console.log(JSON.stringify({
  secret: h.secret,
  test_status: d.status,
  test_http: d.http_status,
  delivery_count: list.length,
}));
"""
        env = {
            "SHOTCLASSIFY_STORE_DIR": str(tmp_path),
            "HOOK_URL": url,
            # The SSRF guard added in a later tick rejects loopback URLs by
            # default. This test deliberately points the webhook at a local
            # listener, so flip the documented dev escape hatch.
            "SHOTCLASSIFY_WEBHOOK_ALLOW_LOOPBACK": "1",
        }
        proc = subprocess.run(
            ["node", "--import", "tsx", "--input-type=module", "-e", script],
            cwd=WEB,
            env={**os.environ, **env},
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            raise AssertionError(
                f"node exited {proc.returncode}\nstdout:{proc.stdout}\nstderr:{proc.stderr}"
            )
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        assert result["test_status"] == "success"
        assert result["test_http"] == 200
        assert result["delivery_count"] >= 1
        # At least 2 received: test ping + classify.completed dispatch.
        assert len(_Handler.received) >= 2
        # Verify HMAC signature on the first delivery.
        first = _Handler.received[0]
        sig_header = first["headers"].get("x-shotclassify-signature", "")
        assert sig_header.startswith("sha256=")
        expected = "sha256=" + hmac.new(
            result["secret"].encode(), first["body"].encode(), hashlib.sha256
        ).hexdigest()
        assert hmac.compare_digest(sig_header, expected)
        assert first["headers"].get("x-shotclassify-event") in {
            "ping",
            "classify.completed",
        }
    finally:
        httpd.shutdown()
        httpd.server_close()
