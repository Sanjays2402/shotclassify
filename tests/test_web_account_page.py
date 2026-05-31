"""Smoke test for the web /account feature wiring.

These checks guard the customer-facing Account/GDPR page from silent
regressions: the page file exists, the nav links to it, and the Next
proxy routes that talk to /v1/me/data are in place.
"""
from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def test_account_page_exists_and_uses_me_endpoint():
    page = WEB / "app" / "account" / "page.tsx"
    assert page.exists(), "Account page is missing."
    body = page.read_text(encoding="utf-8")
    assert "/api/me" in body, "Account page must fetch /api/me."
    assert "/api/me/export" in body, "Account page must offer JSON export."
    assert "confirm=erase" in body, "Account page must require erase confirm."
    assert "/auth/login" in body, "Account page must surface sign in."
    assert "/auth/logout" in body, "Account page must surface sign out."


def test_account_proxy_routes_exist():
    me = WEB / "app" / "api" / "me" / "route.ts"
    export = WEB / "app" / "api" / "me" / "export" / "route.ts"
    assert me.exists(), "/api/me proxy route is missing."
    assert export.exists(), "/api/me/export proxy route is missing."
    me_src = me.read_text(encoding="utf-8")
    assert "/v1/me/data" in me_src, "Proxy must call the GDPR endpoint."
    assert "DELETE" in me_src, "Proxy must support deletion."
    assert "sc_session" in me_src, (
        "Proxy should prefer the browser session cookie when present."
    )


def test_account_in_nav():
    layout = (WEB / "app" / "layout.tsx").read_text(encoding="utf-8")
    assert 'href="/account"' in layout, "Nav must link to /account."
