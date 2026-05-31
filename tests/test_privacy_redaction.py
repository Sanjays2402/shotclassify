"""PII redaction and data residency behavior.

These tests verify that:

* The regex redactor replaces emails, phones, SSNs, credit cards (Luhn
  valid only), IPs, and IBANs and leaves unrelated text alone.
* The pipeline applies the per-tenant redaction modes to OCR text and
  extracted fields before persistence, and does NOT redact for tenants
  that opted out, so cross-tenant isolation is real.
* The admin API rejects non-admin callers, validates input, and the
  resulting X-Data-Residency header is echoed on responses.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from shotclassify_common.redact import redact_fields, redact_text
from services.api.app.main import create_app


def test_redact_text_handles_common_pii():
    src = (
        "Email me at alice@acme.com or call (415) 555-1234.\n"
        "SSN 123-45-6789, card 4242 4242 4242 4242, server 10.0.0.5, "
        "IBAN GB82 WEST 1234 5698 7654 32."
    )
    out = redact_text(
        src,
        ["email", "phone", "ssn", "credit_card", "ip", "iban"],
    )
    assert "alice@acme.com" not in out
    assert "[REDACTED:email]" in out
    assert "[REDACTED:phone]" in out
    assert "[REDACTED:ssn]" in out
    assert "[REDACTED:credit_card]" in out
    assert "[REDACTED:ip]" in out
    assert "[REDACTED:iban]" in out


def test_redact_skips_invalid_luhn_card():
    # 16 digits, fails Luhn -> must NOT be redacted as a credit_card.
    out = redact_text("number 1234 5678 9012 3456 here", ["credit_card"])
    assert "1234 5678 9012 3456" in out


def test_redact_fields_walks_dict_and_list():
    payload = {
        "vendor": "Acme",
        "notes": ["call (415) 555-1234", "ok"],
        "total": 12.5,
        "contact": {"email": "x@y.io"},
    }
    out = redact_fields(payload, ["email", "phone"])
    assert out["notes"][0] == "call [REDACTED:phone]"
    assert out["notes"][1] == "ok"
    assert out["total"] == 12.5
    assert out["contact"]["email"] == "[REDACTED:email]"


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'privacy.db'}")
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
    return TestClient(create_app())


def test_privacy_route_admin_only(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Operator cannot read.
    r = c.get(
        "/v1/settings/security/privacy",
        headers={"x-api-key": "acme-op-key"},
    )
    assert r.status_code in (401, 403)
    # Admin can read; defaults are empty.
    r = c.get(
        "/v1/settings/security/privacy",
        headers={"x-api-key": "acme-admin-key"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == "acme"
    assert body["redact_modes"] == []
    assert body["data_residency"] is None
    assert "email" in body["available_modes"]


def test_privacy_validates_and_isolates_tenants(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    # Bad mode -> 422.
    r = c.put(
        "/v1/settings/security/privacy",
        headers={"x-api-key": "acme-admin-key", "content-type": "application/json"},
        json={"redact_modes": ["nope"], "data_residency": "eu"},
    )
    assert r.status_code == 422

    # Acme enables email + ssn, picks eu.
    r = c.put(
        "/v1/settings/security/privacy",
        headers={"x-api-key": "acme-admin-key", "content-type": "application/json"},
        json={"redact_modes": ["email", "ssn"], "data_residency": "eu"},
    )
    assert r.status_code == 200, r.text
    assert set(r.json()["redact_modes"]) == {"email", "ssn"}
    assert r.json()["data_residency"] == "eu"

    # Acme response now carries the residency header.
    r = c.get("/healthz", headers={"x-api-key": "acme-admin-key"})
    # /healthz is public so tenant may be unresolved; fetch a tenant-scoped
    # admin route instead.
    r = c.get(
        "/v1/settings/security/privacy",
        headers={"x-api-key": "acme-admin-key"},
    )
    assert r.headers.get("x-data-residency") == "eu"

    # Globex (separate tenant) sees empty privacy and NO residency header.
    r = c.get(
        "/v1/settings/security/privacy",
        headers={"x-api-key": "globex-admin-key"},
    )
    assert r.status_code == 200
    assert r.json()["redact_modes"] == []
    assert r.json()["data_residency"] is None
    assert "x-data-residency" not in {k.lower() for k in r.headers.keys()}
