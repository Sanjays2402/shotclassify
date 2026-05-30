"""Audit log middleware + endpoint tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'audit.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def test_audit_log_records_authenticated_mutation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Mutating, authenticated request -> should be recorded.
    r = c.put(
        "/v1/settings/rules",
        json={"yaml": "defaults: {dry_run: true}\nrules: []\n"},
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200

    # Read back via audit endpoint.
    r2 = c.get("/v1/audit", headers={"X-API-Key": "k"})
    assert r2.status_code == 200
    entries = r2.json()
    assert any(
        e["method"] == "PUT" and e["path"] == "/v1/settings/rules" and e["principal"] == "api-key"
        for e in entries
    ), entries

    stats = c.get("/v1/audit/stats", headers={"X-API-Key": "k"}).json()
    assert stats["count"] >= 1


def test_audit_log_skips_reads_and_unauthenticated(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Reads should not be recorded.
    c.get("/v1/history", headers={"X-API-Key": "k"})
    # Unauthenticated mutation should not be recorded (401).
    c.delete("/v1/history/does-not-exist")

    r = c.get("/v1/audit", headers={"X-API-Key": "k"})
    entries = r.json()
    # Only the /v1/audit GET above isn't mutating, so list should be empty.
    assert entries == [], entries


def test_audit_log_records_target_id(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # 404, but it is an authenticated DELETE -> still audited.
    c.delete("/v1/history/abc123", headers={"X-API-Key": "k"})
    entries = c.get(
        "/v1/audit",
        headers={"X-API-Key": "k"},
        params={"path_prefix": "/v1/history"},
    ).json()
    assert any(e["target_id"] == "abc123" and e["status_code"] == 404 for e in entries), entries
