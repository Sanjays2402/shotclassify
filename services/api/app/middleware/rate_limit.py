"""Per-IP, per-API-key, and per-workspace rate limiting middleware.

Uses an in-process token bucket keyed on (in order of preference) the
resolved workspace id, the API key id, or the client IP. Limits are
configured via settings:

  RATE_LIMIT_ENABLED          bool, default True
  RATE_LIMIT_PER_IP_RPM       int requests/min per client IP, default 120
  RATE_LIMIT_PER_KEY_RPM      int requests/min per API key, default 600
  RATE_LIMIT_PER_WORKSPACE_RPM int requests/min per workspace, default 2400
  RATE_LIMIT_BURST            int extra burst allowance, default 20
  RATE_LIMIT_EXEMPT_PATHS     comma list of path prefixes, default
                              "/healthz,/readyz,/metrics,/.well-known,/security.txt"

Individual API keys may override the per-key ceiling via the
``api_keys.rpm_override`` column so workspace admins can grant elevated
quotas to trusted integrations without lifting the global default.

Every response carries the standard ``X-RateLimit-Limit``,
``X-RateLimit-Remaining``, ``X-RateLimit-Reset``, and ``X-RateLimit-Scope``
headers so clients can back off proactively. Rejected requests additionally
carry ``Retry-After`` and emit ``shotclassify_rate_limit_rejections_total``
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
from starlette.responses import JSONResponse, Response

RATE_LIMIT_REJECTIONS = Counter(
    "shotclassify_rate_limit_rejections_total",
    "HTTP requests rejected by the rate limiter.",
    ["scope"],
)


@dataclass
class _Bucket:
    tokens: float
    updated: float
    capacity: float
    refill_per_s: float


class TokenBucketLimiter:
    """Thread-safe token-bucket limiter shared across worker threads.

    Refill rate is ``capacity / window`` tokens per second. ``capacity``
    equals ``rpm + burst`` so a client can briefly spike above the
    sustained rate without being throttled. Per-key custom limits can be
    passed at allow() time and override the limiter default for that key.
    """

    def __init__(self, rpm: int, burst: int, window_s: float = 60.0) -> None:
        self.default_rpm = int(max(1, rpm))
        self.burst = int(max(0, burst))
        self.window_s = float(window_s)
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _capacity_for(self, rpm: int | None) -> tuple[float, float]:
        effective_rpm = int(rpm) if rpm else self.default_rpm
        effective_rpm = max(1, effective_rpm)
        capacity = float(effective_rpm + self.burst)
        refill = float(effective_rpm) / self.window_s
        return capacity, refill

    def allow(
        self,
        key: str,
        now: float | None = None,
        rpm_override: int | None = None,
    ) -> tuple[bool, float, int, int]:
        """Return ``(allowed, retry_after_seconds, remaining, limit_rpm)``."""
        t = now if now is not None else time.monotonic()
        capacity, refill = self._capacity_for(rpm_override)
        with self._lock:
            b = self._buckets.get(key)
            if b is None or b.capacity != capacity or b.refill_per_s != refill:
                # Recreate the bucket when the effective limit changed so an
                # admin lifting the cap takes effect on the next request.
                b = _Bucket(
                    tokens=capacity, updated=t, capacity=capacity, refill_per_s=refill
                )
                self._buckets[key] = b
            elapsed = max(0.0, t - b.updated)
            b.tokens = min(b.capacity, b.tokens + elapsed * b.refill_per_s)
            b.updated = t
            limit_rpm = int(round(b.refill_per_s * self.window_s))
            if b.tokens >= 1.0:
                b.tokens -= 1.0
                remaining = int(b.tokens)
                return True, 0.0, remaining, limit_rpm
            needed = 1.0 - b.tokens
            retry = needed / b.refill_per_s
            return False, retry, 0, limit_rpm

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _api_key_record_for(request: Request):
    """Best-effort lookup of the DB-backed API key for the presented token.

    Used so the rate limiter can honor a per-key ``rpm_override`` and key
    the bucket on the stable key id (not the raw token) so rotating the
    plaintext token does not reset the bucket. Returns ``None`` whenever
    the lookup fails for any reason; the middleware then falls back to
    keying on the raw header.
    """
    token = request.headers.get("x-api-key")
    if not token:
        return None
    try:
        from shotclassify_store import api_keys_store

        return api_keys_store.get_active_by_token(token)
    except Exception:
        return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply per-IP, per-API-key, and per-workspace token-bucket limits."""

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        s = get_settings()
        self.enabled = s.rate_limit_enabled
        self.exempt = tuple(
            p.strip() for p in s.rate_limit_exempt_paths.split(",") if p.strip()
        )
        burst = s.rate_limit_burst
        self.ip_limiter = TokenBucketLimiter(s.rate_limit_per_ip_rpm, burst)
        self.key_limiter = TokenBucketLimiter(s.rate_limit_per_key_rpm, burst)
        self.workspace_limiter = TokenBucketLimiter(
            getattr(s, "rate_limit_per_workspace_rpm", s.rate_limit_per_key_rpm * 4),
            burst,
        )

    def _is_exempt(self, path: str) -> bool:
        for p in self.exempt:
            if path == p:
                return True
            if p.endswith("/") and path.startswith(p):
                return True
            if path.startswith(p + "/"):
                return True
        return False

    @staticmethod
    def _attach_headers(
        response: Response, *, scope: str, limit: int, remaining: int, retry: float
    ) -> None:
        response.headers["X-RateLimit-Scope"] = scope
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
        # ``Reset`` is seconds until at least one token is available, per the
        # de-facto convention used by GitHub/Stripe-style APIs.
        reset_s = max(1, int(retry + 0.999)) if retry > 0 else 1
        response.headers["X-RateLimit-Reset"] = str(reset_s)

    async def dispatch(self, request: Request, call_next):
        if not self.enabled or self._is_exempt(request.url.path):
            return await call_next(request)

        # Resolve the most specific bucket we can. Workspace > API key > IP.
        key_record = _api_key_record_for(request)
        workspace_id = (
            request.headers.get("x-tenant")
            or (key_record.tenant_id if key_record else None)
        )

        if workspace_id and workspace_id != "*":
            allowed, retry, remaining, limit = self.workspace_limiter.allow(
                f"ws:{workspace_id}"
            )
            scope = "workspace"
        elif key_record is not None:
            allowed, retry, remaining, limit = self.key_limiter.allow(
                f"key:{key_record.id}", rpm_override=key_record.rpm_override
            )
            scope = "api_key"
        elif request.headers.get("x-api-key"):
            # Token presented but DB lookup failed (e.g. env-var key path).
            # Key on the raw token so the bucket is still per-credential.
            allowed, retry, remaining, limit = self.key_limiter.allow(
                f"raw:{request.headers['x-api-key']}"
            )
            scope = "api_key"
        else:
            allowed, retry, remaining, limit = self.ip_limiter.allow(
                f"ip:{_client_ip(request)}"
            )
            scope = "ip"

        if not allowed:
            RATE_LIMIT_REJECTIONS.labels(scope=scope).inc()
            retry_s = max(1, int(retry + 0.999))
            resp = JSONResponse(
                {"error": "rate_limited", "detail": f"Too many requests ({scope})."},
                status_code=429,
                headers={"Retry-After": str(retry_s)},
            )
            self._attach_headers(
                resp, scope=scope, limit=limit, remaining=0, retry=retry
            )
            return resp

        response = await call_next(request)
        # Headers on every successful response so clients can back off
        # proactively without waiting for a 429.
        self._attach_headers(
            response, scope=scope, limit=limit, remaining=remaining, retry=0.0
        )
        return response
