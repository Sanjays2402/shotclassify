"""Prometheus /metrics endpoint and middleware tests."""
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


def test_metrics_endpoint_public_and_exposes_prom_format(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Generate some traffic so counters increment with known labels.
    c.get("/healthz")
    c.get("/v1/history")  # 401, no key
    c.get("/v1/history", headers={"X-API-Key": "k"})  # 200

    r = c.get("/metrics")
    assert r.status_code == 200
    ct = r.headers["content-type"]
    assert ct.startswith("text/plain") and "version=" in ct

    body = r.text
    # Metric families are declared via HELP/TYPE lines.
    assert "# HELP shotclassify_http_requests_total" in body
    assert "# TYPE shotclassify_http_requests_total counter" in body
    assert "# TYPE shotclassify_http_request_duration_seconds histogram" in body
    assert "shotclassify_http_requests_in_flight" in body

    # Route templates (not raw paths) are used so cardinality stays bounded.
    assert 'route="/healthz"' in body
    assert 'route="/v1/history"' in body
    # The 401 and 200 traffic both registered with the correct status labels.
    assert 'status="401"' in body
    assert 'status="200"' in body


def test_metrics_endpoint_not_recursive(monkeypatch, tmp_path):
    """Scraping /metrics must not record itself in shotclassify_http_requests_total."""
    c = _client(monkeypatch, tmp_path)
    for _ in range(3):
        c.get("/metrics")
    body = c.get("/metrics").text
    assert 'route="/metrics"' not in body
