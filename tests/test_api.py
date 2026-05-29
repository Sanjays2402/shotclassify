"""FastAPI route smoke tests using TestClient."""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'api.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def test_healthz_public(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/healthz").status_code == 200


def test_history_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/v1/history").status_code == 401
    assert c.get("/v1/history", headers={"X-API-Key": "k"}).status_code == 200


def test_settings_rules_roundtrip(monkeypatch, tmp_path):
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/settings/rules", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    new_yaml = "defaults: {dry_run: false}\nrules: []\n"
    r2 = c.put(
        "/v1/settings/rules",
        json={"yaml": new_yaml},
        headers={"X-API-Key": "k"},
    )
    assert r2.status_code == 200
    assert "dry_run: false" in rules.read_text()
