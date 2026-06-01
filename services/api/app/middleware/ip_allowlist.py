"""Per-tenant IP allowlist enforcement.

Each tenant can configure a list of CIDR ranges that are allowed to reach
the API and the dashboard. Requests from a source IP outside the list are
rejected with HTTP 403 before the route handler runs. When the list is
empty (the default for every tenant until an admin opts in) the middleware
is a no-op, so existing deployments keep working unchanged.

This is one of the controls enterprise procurement teams ask about by
name (SOC 2 CC6.6 "logical access boundaries") so it is wired in at the
middleware layer rather than per route, which also guarantees we cannot
forget it on a future endpoint.

Order matters: this middleware must run AFTER ``TenantResolutionMiddleware``
on the inbound path so ``request.state.tenant_id`` is populated. With
Starlette's outer-to-inner add order, that means it is added BEFORE the
tenant middleware in ``main.py``.
"""
from __future__ import annotations

import structlog
from prometheus_client import Counter
from shotclassify_common import get_settings
from shotclassify_store import get_ip_allowlist, ip_matches_allowlist
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

log = structlog.get_logger(__name__)


IP_ALLOWLIST_REJECTIONS = Counter(
    "shotclassify_ip_allowlist_rejections_total",
    "HTTP requests rejected by a tenant IP allowlist.",
    ["tenant"],
)


# Paths that must remain reachable from anywhere so probes, OAuth callbacks
# and the allowlist management UI itself never lock the operator out.
DEFAULT_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/healthz",
    "/readyz",
    "/metrics",
    "/auth/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/.well-known/",
    "/security.txt",
    "/v1/trust/",
    "/",
)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


class IPAllowlistMiddleware(BaseHTTPMiddleware):
    """Reject requests whose source IP is not in the tenant's allowlist."""

    def __init__(self, app, exempt_prefixes: tuple[str, ...] | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.exempt = exempt_prefixes or DEFAULT_EXEMPT_PREFIXES

    def _is_exempt(self, path: str) -> bool:
        # Exact root match; otherwise prefix with trailing-slash semantics.
        if path == "/":
            return True
        for p in self.exempt:
            if p == "/":
                continue
            if path == p or path.startswith(p):
                return True
        return False

    async def dispatch(self, request: Request, call_next):
        s = get_settings()
        if not s.ip_allowlist_enabled:
            return await call_next(request)
        path = request.url.path
        if self._is_exempt(path):
            return await call_next(request)
        tenant_id = getattr(request.state, "tenant_id", None)
        # No tenant resolved yet (e.g. unauthenticated request that another
        # layer will 401) -> let it through; auth will reject it.
        if not tenant_id:
            return await call_next(request)
        try:
            allowlist = get_ip_allowlist(tenant_id)
        except Exception as exc:  # pragma: no cover - never break the request path
            log.warning("ip_allowlist_lookup_failed", error=str(exc), tenant=tenant_id)
            return await call_next(request)
        if not allowlist:
            return await call_next(request)
        ip = _client_ip(request)
        if ip and ip_matches_allowlist(ip, allowlist):
            return await call_next(request)
        IP_ALLOWLIST_REJECTIONS.labels(tenant=tenant_id).inc()
        log.info(
            "ip_allowlist_blocked",
            tenant=tenant_id,
            client_ip=ip or "unknown",
            path=path,
        )
        return JSONResponse(
            status_code=403,
            content={
                "error": "ip_not_allowed",
                "detail": (
                    "Source IP is not in the tenant allowlist. Ask a workspace "
                    "admin to add it under Settings > Security."
                ),
                "tenant": tenant_id,
            },
        )
