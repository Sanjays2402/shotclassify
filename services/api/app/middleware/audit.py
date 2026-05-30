"""Audit log middleware.

Records authenticated, state-changing requests to the persisted audit_log table
so operators have a tamper-evident trail of who did what when.

Read-only requests (GET, HEAD, OPTIONS) and unauthenticated/public paths are
skipped to keep the table focused on actions worth reviewing.
"""
from __future__ import annotations

import time

import structlog
from shotclassify_store import AuditRepository
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

log = structlog.get_logger(__name__)

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Paths that should never be audited even if they happen to be POSTed
# (e.g. health probes from k8s, OAuth callbacks, static blob fetches).
SKIP_PATH_PREFIXES = (
    "/healthz",
    "/readyz",
    "/auth/",
    "/blob/",
    "/docs",
    "/redoc",
    "/openapi.json",
)


class AuditLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        method = request.method.upper()
        path = request.url.path
        if method not in MUTATING_METHODS:
            return response
        if any(path.startswith(p) for p in SKIP_PATH_PREFIXES):
            return response
        principal = getattr(request.state, "principal", None)
        # Only audit when auth middleware identified a principal. Unauthenticated
        # 401s are already visible in request logs.
        if not principal:
            return response
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        request_id = response.headers.get("x-request-id")
        target_id = None
        # Common pattern: /v1/<resource>/<id>/...
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 3 and parts[0] == "v1":
            target_id = parts[2]
        client_ip = request.client.host if request.client else None
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        try:
            AuditRepository().record(
                principal=str(principal),
                method=method,
                path=path,
                status_code=response.status_code,
                request_id=request_id,
                client_ip=client_ip,
                user_agent=request.headers.get("user-agent"),
                elapsed_ms=elapsed_ms,
                target_id=target_id,
            )
        except Exception as exc:  # pragma: no cover - never break the request path
            log.warning("audit_log_write_failed", error=str(exc), path=path)
        return response
