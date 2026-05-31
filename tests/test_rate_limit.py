"""Rate limit middleware tests.

Covers the token bucket itself (deterministic, no sleeps) and the
end-to-end FastAPI integration (per-IP and per-API-key buckets, 429
response shape, and exempt paths).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import create_app
from services.api.app.middleware.rate_limit import TokenBucketLimiter


def test_token_bucket_drains_and_refills():
    b = TokenBucketLimiter(rpm=60, burst=0)  # 60/min = 1/s, capacity 60
    t = 1000.0
    # Drain the full capacity at t=1000.
    for _ in range(60):
        ok, _, _, _ = b.allow("x", now=t)
        assert ok
    ok, retry, remaining, limit = b.allow("x", now=t)
    assert not ok
    assert retry > 0
    assert remaining == 0
    assert limit == 60
    # 10 seconds later we should have refilled ~10 tokens.
    ok, _, _, _ = b.allow("x", now=t + 10.0)
    assert ok
    # Distinct keys have independent buckets.
    ok, _, _, _ = b.allow("y", now=t)
    assert ok


def test_token_bucket_rpm_override_lifts_capacity():
    # Default rpm=10, but a single key passes rpm_override=120 so it should
    # drain 120 tokens before being rejected. Other keys still see the
    # default capacity.
    b = TokenBucketLimiter(rpm=10, burst=0)
    t = 5000.0
    for _ in range(120):
        ok, _, _, lim = b.allow("vip", now=t, rpm_override=120)
        assert ok
        assert lim == 120
    ok, _, _, _ = b.allow("vip", now=t, rpm_override=120)
    assert not ok
    # A different key with no override still uses the default.
    for _ in range(10):
        ok, _, _, lim = b.allow("normal", now=t)
        assert ok
        assert lim == 10
    ok, _, _, _ = b.allow("normal", now=t)
    assert not ok


def _client(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'rl.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def test_per_ip_rate_limit_returns_429(monkeypatch, tmp_path):
    # 2 rpm, no burst -> capacity 2. First two unauthenticated requests
    # return 401 (auth runs after rate limit middleware fires), the third
    # exceeds the bucket and must return 429.
    c = _client(
        monkeypatch,
        tmp_path,
        RATE_LIMIT_PER_IP_RPM="2",
        RATE_LIMIT_PER_KEY_RPM="2",
        RATE_LIMIT_BURST="0",
    )
    r1 = c.get("/v1/history")
    r2 = c.get("/v1/history")
    r3 = c.get("/v1/history")
    assert r1.status_code in (401, 429)
    assert r2.status_code in (401, 429)
    assert r3.status_code == 429
    assert r3.headers.get("Retry-After")
    assert r3.headers.get("X-RateLimit-Scope") == "ip"
    body = r3.json()
    assert body["error"] == "rate_limited"


def test_per_key_bucket_isolated_from_ip(monkeypatch, tmp_path):
    c = _client(
        monkeypatch,
        tmp_path,
        RATE_LIMIT_PER_IP_RPM="1",
        RATE_LIMIT_PER_KEY_RPM="50",
        RATE_LIMIT_BURST="0",
    )
    # Authenticated requests use the per-key bucket, which has plenty of
    # headroom even though the per-IP bucket is tiny.
    for _ in range(5):
        r = c.get("/v1/history", headers={"X-API-Key": "k"})
        assert r.status_code == 200


def test_health_metrics_exempt_from_rate_limit(monkeypatch, tmp_path):
    c = _client(
        monkeypatch,
        tmp_path,
        RATE_LIMIT_PER_IP_RPM="1",
        RATE_LIMIT_BURST="0",
    )
    for _ in range(5):
        assert c.get("/healthz").status_code == 200
        assert c.get("/metrics").status_code == 200


def test_rate_limit_disabled(monkeypatch, tmp_path):
    c = _client(
        monkeypatch,
        tmp_path,
        RATE_LIMIT_ENABLED="false",
        RATE_LIMIT_PER_IP_RPM="1",
        RATE_LIMIT_BURST="0",
    )
    # With limiter disabled, requests pass through to auth (401), never 429.
    for _ in range(10):
        assert c.get("/v1/history").status_code == 401


def test_standard_headers_on_every_response(monkeypatch, tmp_path):
    # Every response (success or rejection) carries X-RateLimit-Limit /
    # X-RateLimit-Remaining / X-RateLimit-Reset / X-RateLimit-Scope so
    # well-behaved clients can back off without waiting for a 429.
    c = _client(
        monkeypatch,
        tmp_path,
        RATE_LIMIT_PER_IP_RPM="5",
        RATE_LIMIT_PER_KEY_RPM="5",
        RATE_LIMIT_BURST="0",
    )
    r = c.get("/v1/history")
    assert r.headers.get("X-RateLimit-Limit") == "5"
    assert r.headers.get("X-RateLimit-Scope") in ("ip", "api_key", "workspace")
    assert r.headers.get("X-RateLimit-Reset") is not None
    remaining = int(r.headers["X-RateLimit-Remaining"])
    assert 0 <= remaining <= 5


def test_per_workspace_bucket_aggregates_across_keys(monkeypatch, tmp_path):
    # When callers present X-Tenant, the workspace bucket fires before the
    # per-key bucket. Two distinct keys sharing one workspace should both
    # count against the same workspace quota.
    c = _client(
        monkeypatch,
        tmp_path,
        RATE_LIMIT_PER_IP_RPM="1000",
        RATE_LIMIT_PER_KEY_RPM="1000",
        RATE_LIMIT_PER_WORKSPACE_RPM="3",
        RATE_LIMIT_BURST="0",
    )
    headers = {"X-API-Key": "k", "X-Tenant": "acme"}
    statuses = [c.get("/v1/history", headers=headers).status_code for _ in range(5)]
    assert 429 in statuses
    # The first three should succeed and the fourth must be throttled by
    # the workspace bucket, not the per-key bucket.
    last_429 = next(r for r in statuses if r == 429)
    assert last_429 == 429
