"""Per-IP and per-API-key rate limiting middleware.

Uses an in-process token bucket keyed on either the API key (when present
on the request) or the client IP. Limits are configured via settings:

  RATE_LIMIT_ENABLED         bool, default True
  RATE_LIMIT_PER_IP_RPM      int requests/min per client IP, default 120
  RATE_LIMIT_PER_KEY_RPM     int requests/min per API key, default 600
  RATE_LIMIT_BURST           int extra burst allowance, default 20
  RATE_LIMIT_EXEMPT_PATHS    comma list of path prefixes, default
                             "/healthz,/readyz,/metrics,/blob"

When the bucket is empty the middleware returns HTTP 429 with a
Retry-After header and emits ``shotclassify_rate_limit_rejections_total``
on the Prometheus registry so operators can alert on throttling.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from prometheus_client import Counter
from shotclassify_common import get_settings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

RATE_LIMIT_REJECTIONS = Counter(
    "shotclassify_rate_limit_rejections_total",
    "HTTP requests rejected by the rate limiter.",
    ["scope"],
)


@dataclass
class _Bucket:
    tokens: float
    updated: float


class TokenBucketLimiter:
    """Thread-safe token-bucket limiter shared across worker threads.

    Refill rate is ``capacity / window`` tokens per second. ``capacity``
    equals ``rpm + burst`` so a client can briefly spike above the
    sustained rate without being throttled.
    """

    def __init__(self, rpm: int, burst: int, window_s: float = 60.0) -> None:
        self.capacity = float(max(1, rpm + burst))
        self.refill_per_s = float(max(1, rpm)) / window_s
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> tuple[bool, float]:
        """Return (allowed, retry_after_seconds)."""
        t = now if now is not None else time.monotonic()
        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                b = _Bucket(tokens=self.capacity, updated=t)
                self._buckets[key] = b
            elapsed = max(0.0, t - b.updated)
            b.tokens = min(self.capacity, b.tokens + elapsed * self.refill_per_s)
            b.updated = t
            if b.tokens >= 1.0:
                b.tokens -= 1.0
                return True, 0.0
            needed = 1.0 - b.tokens
            retry = needed / self.refill_per_s
            return False, retry

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply per-IP and per-API-key token-bucket limits."""

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        s = get_settings()
        self.enabled = s.rate_limit_enabled
        self.exempt = tuple(
            p.strip() for p in s.rate_limit_exempt_paths.split(",") if p.strip()
        )
        self.ip_limiter = TokenBucketLimiter(s.rate_limit_per_ip_rpm, s.rate_limit_burst)
        self.key_limiter = TokenBucketLimiter(s.rate_limit_per_key_rpm, s.rate_limit_burst)

    def _is_exempt(self, path: str) -> bool:
        for p in self.exempt:
            if path == p:
                return True
            if p.endswith("/") and path.startswith(p):
                return True
            if path.startswith(p + "/"):
                return True
        return False

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)
        path = request.url.path
        if self._is_exempt(path):
            return await call_next(request)

        api_key = request.headers.get("x-api-key")
        if api_key:
            allowed, retry = self.key_limiter.allow(f"key:{api_key}")
            scope = "api_key"
        else:
            allowed, retry = self.ip_limiter.allow(f"ip:{_client_ip(request)}")
            scope = "ip"

        if not allowed:
            RATE_LIMIT_REJECTIONS.labels(scope=scope).inc()
            retry_s = max(1, int(retry + 0.999))
            return JSONResponse(
                {"error": "rate_limited", "detail": f"Too many requests ({scope})."},
                status_code=429,
                headers={"Retry-After": str(retry_s), "X-RateLimit-Scope": scope},
            )
        return await call_next(request)
