"""Tests for SecurityHeadersMiddleware and CORS allowlist hardening."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'sec.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    for key, val in env.items():
        monkeypatch.setenv(key, val)

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()

    from services.api.app.main import create_app

    return TestClient(create_app())


def test_baseline_security_headers_present(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "default-src 'self'" in r.headers.get("Content-Security-Policy", "")
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "camera=()" in r.headers.get("Permissions-Policy", "")
    assert r.headers.get("Cross-Origin-Opener-Policy") == "same-origin"


def test_hsts_only_in_production(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, APP_ENV="development")
    r = c.get("/healthz")
    assert "Strict-Transport-Security" not in r.headers


def test_hsts_emitted_in_production(monkeypatch, tmp_path):
    c = _client(
        monkeypatch,
        tmp_path,
        APP_ENV="production",
        CORS_ALLOWED_ORIGINS="https://app.example.com",
    )
    r = c.get("/healthz")
    hsts = r.headers.get("Strict-Transport-Security", "")
    assert "max-age=" in hsts
    assert "includeSubDomains" in hsts


def test_security_headers_present_on_401(monkeypatch, tmp_path):
    """Unauthenticated responses must still carry security headers."""
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/history")
    assert r.status_code == 401
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in r.headers


def test_security_headers_can_be_disabled(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, SECURITY_HEADERS_ENABLED="false")
    r = c.get("/healthz")
    assert "Content-Security-Policy" not in r.headers
    assert "X-Frame-Options" not in r.headers


def test_cors_wildcard_dropped_outside_development(monkeypatch, tmp_path):
    """In staging/production a wildcard must be filtered out, never echoed."""
    c = _client(
        monkeypatch,
        tmp_path,
        APP_ENV="production",
        CORS_ALLOWED_ORIGINS="*,https://app.example.com",
    )
    r = c.get(
        "/healthz",
        headers={"Origin": "https://evil.example.com"},
    )
    assert r.status_code == 200
    assert r.headers.get("Access-Control-Allow-Origin") != "*"
    assert r.headers.get("Access-Control-Allow-Origin") != "https://evil.example.com"


def test_cors_allows_listed_origin(monkeypatch, tmp_path):
    c = _client(
        monkeypatch,
        tmp_path,
        APP_ENV="production",
        CORS_ALLOWED_ORIGINS="https://app.example.com",
    )
    r = c.options(
        "/healthz",
        headers={
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("Access-Control-Allow-Origin") == "https://app.example.com"


def test_cors_wildcard_allowed_in_development(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, APP_ENV="development", CORS_ALLOWED_ORIGINS="*")
    r = c.get("/healthz", headers={"Origin": "https://anything.example.com"})
    # Starlette echoes either ``*`` or the request origin when wildcard is set.
    allow = r.headers.get("Access-Control-Allow-Origin")
    assert allow in {"*", "https://anything.example.com"}
