"""Readiness probe tests.

The readiness probe must:
  * return 200 when DB and storage are healthy
  * return 503 with per-check detail when DB is broken
  * return 503 in non-development environments when Redis is unreachable
  * keep liveness (``/healthz``) green regardless of dependency state
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path, *, env="development", redis_url=None):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'rdy.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_ENV", env)
    if redis_url is not None:
        monkeypatch.setenv("REDIS_URL", redis_url)
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    from services.api.app.main import create_app

    return TestClient(create_app())


def test_healthz_is_pure_liveness(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz_ok_when_deps_healthy(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/readyz")
    body = r.json()
    assert r.status_code == 200, body
    assert body["status"] == "ready"
    assert body["checks"]["db"]["status"] == "ok"
    assert body["checks"]["storage"]["status"] == "ok"
    # Redis check runs but is not required in development.
    assert "redis" in body["checks"]


def test_readyz_fails_when_storage_missing(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Remove the storage directory after startup created it.
    import shutil
    shutil.rmtree(tmp_path / "storage")
    r = c.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["storage"]["status"] == "error"
    assert "missing" in body["checks"]["storage"]["detail"]


def test_readyz_fails_when_db_broken(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    from services.api.app.routes import health as health_module

    monkeypatch.setattr(
        health_module,
        "_check_db",
        lambda: ("error", "OperationalError: connection refused"),
    )
    r = c.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["checks"]["db"]["status"] == "error"
    assert "connection refused" in body["checks"]["db"]["detail"]


def test_readyz_redis_required_outside_development(monkeypatch, tmp_path):
    # Build app under dev (so production validation does not block startup)
    # then flip the env on the cached settings so the probe treats Redis as
    # a hard dependency. This mirrors what happens in staging/production.
    c = _client(
        monkeypatch,
        tmp_path,
        env="development",
        redis_url="redis://127.0.0.1:1/0",
    )
    from shotclassify_common.settings import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "app_env", "production")
    r = c.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["checks"]["redis"]["status"] == "error"


def test_readyz_redis_optional_in_development(monkeypatch, tmp_path):
    c = _client(
        monkeypatch,
        tmp_path,
        env="development",
        redis_url="redis://127.0.0.1:1/0",
    )
    r = c.get("/readyz")
    # Redis is down but env is dev, so it must not fail the probe.
    assert r.status_code == 200
    assert r.json()["status"] == "ready"
