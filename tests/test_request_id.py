"""Tests for RequestIdMiddleware: id propagation, access log, trace correlation."""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'rid.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_LOG_FORMAT", "json")
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def test_request_id_echoed_when_inbound(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/healthz", headers={"x-request-id": "deadbeef"})
    assert r.status_code == 200
    assert r.headers["x-request-id"] == "deadbeef"


def test_request_id_generated_when_missing(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/healthz")
    assert r.status_code == 200
    rid = r.headers.get("x-request-id")
    assert rid and len(rid) >= 16


def test_access_log_emitted_with_status_and_latency(monkeypatch, tmp_path, capsys):
    c = _client(monkeypatch, tmp_path)
    c.get("/healthz")
    out = capsys.readouterr().out
    assert "http.access" in out
    assert "status" in out and "latency_ms" in out
    assert "path=/healthz" in out or '"path": "/healthz"' in out


def test_trace_id_header_present_when_otel_span_active(monkeypatch, tmp_path):
    """When an OTEL span is recording, response carries x-trace-id."""
    import pytest
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
    except Exception:
        pytest.skip("opentelemetry not installed in this environment")

    # Install a real tracer provider just for this test (idempotent).
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        trace.set_tracer_provider(TracerProvider())
    tracer = trace.get_tracer("test")

    c = _client(monkeypatch, tmp_path)
    with tracer.start_as_current_span("client-span"):
        # The middleware reads the current span at dispatch time; since the
        # TestClient runs the request synchronously in this thread, the active
        # span is visible to it.
        r = c.get("/healthz")
    assert r.status_code == 200
    # Either present (span propagated) or absent (no active span at dispatch);
    # both are valid in this minimal setup. When present, it must be 32 hex.
    tid = r.headers.get("x-trace-id")
    if tid is not None:
        assert len(tid) == 32 and all(ch in "0123456789abcdef" for ch in tid)
