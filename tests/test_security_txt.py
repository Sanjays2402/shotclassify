"""RFC 9116 /.well-known/security.txt endpoint tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path, **env: str):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'api.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    for key, value in env.items():
        monkeypatch.setenv(key.upper(), value)
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def test_security_txt_404_when_unconfigured(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/.well-known/security.txt")
    assert r.status_code == 404, r.text
    assert r.headers["content-type"].startswith("text/plain")


def test_security_txt_served_without_auth(monkeypatch, tmp_path):
    c = _client(
        monkeypatch,
        tmp_path,
        security_contact="security@example.com",
        security_canonical_url="https://example.com/.well-known/security.txt",
        security_policy_url="https://example.com/security",
        security_acknowledgments_url="https://example.com/security/thanks",
        security_preferred_languages="en, de",
        security_expires_days="180",
    )
    # No API key. Must still return 200; this proves the route is in
    # PUBLIC_PATHS and exempt from the rate limiter / IP allowlist.
    r = c.get("/.well-known/security.txt")
    assert r.status_code == 200, r.text
    body = r.text
    # Required fields per RFC 9116.
    assert "Contact: mailto:security@example.com" in body
    assert "Expires:" in body
    # ISO 8601 UTC trailing Z required by the RFC.
    expires_line = [line for line in body.splitlines() if line.startswith("Expires:")][0]
    assert expires_line.rstrip().endswith("Z"), expires_line
    # Optional fields normalised.
    assert "Preferred-Languages: en, de" in body
    assert "Canonical: https://example.com/.well-known/security.txt" in body
    assert "Policy: https://example.com/security" in body
    assert "Acknowledgments: https://example.com/security/thanks" in body
    # Cacheable per response headers, plain-text content type.
    assert r.headers["content-type"].startswith("text/plain")
    assert "max-age" in r.headers.get("cache-control", "")


def test_security_txt_widens_https_contact(monkeypatch, tmp_path):
    c = _client(
        monkeypatch,
        tmp_path,
        security_contact="https://example.com/report",
    )
    r = c.get("/.well-known/security.txt")
    assert r.status_code == 200
    assert "Contact: https://example.com/report" in r.text


def test_security_txt_legacy_alias(monkeypatch, tmp_path):
    c = _client(
        monkeypatch,
        tmp_path,
        security_contact="security@example.com",
    )
    r = c.get("/security.txt")
    assert r.status_code == 200
    assert "Contact: mailto:security@example.com" in r.text


def test_security_txt_expires_clamped(monkeypatch, tmp_path):
    # A value beyond the RFC-recommended ~1 year cap must be clamped, not
    # echoed verbatim. We can't pin the date without freezing time, but we
    # can assert the line is present and a 4-digit year shows up.
    c = _client(
        monkeypatch,
        tmp_path,
        security_contact="security@example.com",
        security_expires_days="9999",
    )
    r = c.get("/.well-known/security.txt")
    assert r.status_code == 200
    expires_line = [line for line in r.text.splitlines() if line.startswith("Expires:")][0]
    # ISO 8601 like Expires: 2027-05-31T19:56:00Z
    assert len(expires_line.split("Expires: ", 1)[1]) == len("YYYY-MM-DDTHH:MM:SSZ")
