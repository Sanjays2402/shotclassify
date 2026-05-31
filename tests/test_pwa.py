"""PWA (Progressive Web App) wiring smoke tests.

These checks guard the install + offline shell story exposed at /manifest.webmanifest,
/sw.js, and the web app's offline route, all served from web/public + web/app.
"""

from __future__ import annotations

import json
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def test_manifest_present_and_valid() -> None:
    path = WEB / "public" / "manifest.webmanifest"
    assert path.exists(), "PWA manifest missing"
    data = json.loads(path.read_text())
    # Required fields for installability.
    for key in ("name", "short_name", "start_url", "display", "icons"):
        assert key in data, f"manifest missing {key!r}"
    assert data["display"] in {"standalone", "fullscreen", "minimal-ui"}
    sizes = {icon.get("sizes") for icon in data["icons"]}
    assert "192x192" in sizes and "512x512" in sizes, "need both 192 and 512 icons"
    assert any(
        icon.get("purpose", "") == "maskable" for icon in data["icons"]
    ), "need a maskable icon"


def test_service_worker_has_offline_fallback() -> None:
    sw = (WEB / "public" / "sw.js").read_text()
    assert "/offline" in sw, "service worker must reference the /offline shell"
    assert "fetch" in sw and "install" in sw and "activate" in sw
    # Do not intercept API traffic.
    assert "/api/" in sw and "/v1/" in sw, "service worker must skip /api/ and /v1/"


def test_offline_route_exists() -> None:
    page = WEB / "app" / "offline" / "page.tsx"
    assert page.exists(), "offline page missing"
    body = page.read_text()
    assert "offline" in body.lower()


def test_icons_present() -> None:
    icons = WEB / "public" / "icons"
    assert (icons / "icon-192.png").exists()
    assert (icons / "icon-512.png").exists()
    assert (icons / "maskable-512.png").exists()


def test_layout_links_manifest_and_installer() -> None:
    layout = (WEB / "app" / "layout.tsx").read_text()
    assert "manifest.webmanifest" in layout
    assert "PwaInstaller" in layout
    assert "themeColor" in layout
