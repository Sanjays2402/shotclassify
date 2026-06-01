"""Per-tenant browser-origin allowlist enforcement.

Each tenant can configure the set of browser origins (``scheme://host[:port]``)
that are allowed to call the API from a web page. When the allowlist is
non-empty, every request that arrives with an ``Origin`` header is
rejected with HTTP 403 ``origin_not_allowed`` unless the origin is in the
list. Server-to-server callers (curl, SDKs, CI) never send ``Origin``, so
they are unaffected.

This complements two existing controls:

* The deployment-level CORS allowlist in ``main.py`` (covers the whole
  fleet, not per-tenant).
* ``IPAllowlistMiddleware`` (covers IPs, but cannot distinguish two web
  apps sharing one egress IP).

Together they answer the procurement question "which web origins can talk
to our workspace?" with a per-workspace, self-serve answer instead of a
deploy ticket.

Order: this middleware reads ``request.state.tenant_id``, so it must run
AFTER ``TenantResolutionMiddleware`` on the inbound path. With
Starlette's outer-to-inner ``add_middleware`` semantics that means it is
added BEFORE the tenant middleware in ``main.py`` (so it ends up more
inner and executes after tenant resolution).
"""
from __future__ import annotations

import structlog
from prometheus_client import Counter
from shotclassify_store import get_cors_origins, origin_matches_allowlist
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

log = structlog.get_logger(__name__)


ORIGIN_ALLOWLIST_REJECTIONS = Counter(
    "shotclassify_origin_allowlist_rejections_total",
    "Browser requests rejected by a tenant origin allowlist.",
    ["tenant"],
)


# Paths that must remain reachable from any origin so probes, the SSO
# callback (which can be navigated to from the IdP) and the allowlist
# management UI itself never lock the operator out.
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
)


class OriginAllowlistMiddleware(BaseHTTPMiddleware):
    """Reject browser requests whose Origin is not in the tenant allowlist."""

    def __init__(self, app, exempt_prefixes: tuple[str, ...] | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.exempt = exempt_prefixes or DEFAULT_EXEMPT_PREFIXES

    def _is_exempt(self, path: str) -> bool:
        if path == "/":
            return True
        for p in self.exempt:
            if p == "/":
                continue
            if path == p or path.startswith(p):
                return True
        return False

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        # No Origin header = server-to-server caller. Browsers always set
        # Origin on cross-origin XHR/fetch and on POST/PUT/DELETE on same
        # origin too, so anything without one is not subject to this
        # control.
        if not origin:
            return await call_next(request)
        path = request.url.path
        if self._is_exempt(path):
            return await call_next(request)
        # Preflight is handled by the global CORS middleware which runs
        # outermost. If it accepted the OPTIONS we still want to enforce
        # tenant policy on the real request, but the OPTIONS itself does
        # not yet have a resolved tenant, so pass through.
        if request.method == "OPTIONS":
            return await call_next(request)
        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            # Unauthenticated request that another layer will 401 -> let
            # it through so the caller learns "not authenticated" rather
            # than getting a misleading 403 origin error.
            return await call_next(request)
        try:
            allowlist = get_cors_origins(tenant_id)
        except Exception as exc:  # pragma: no cover - never break the request path
            log.warning("origin_allowlist_lookup_failed", error=str(exc), tenant=tenant_id)
            return await call_next(request)
        if not allowlist:
            return await call_next(request)
        if origin_matches_allowlist(origin, allowlist):
            return await call_next(request)
        ORIGIN_ALLOWLIST_REJECTIONS.labels(tenant=tenant_id).inc()
        log.info(
            "origin_allowlist_blocked",
            tenant=tenant_id,
            origin=origin,
            path=path,
        )
        return JSONResponse(
            status_code=403,
            content={
                "error": "origin_not_allowed",
                "detail": (
                    "Browser origin is not in the workspace allowlist. Ask a "
                    "workspace admin to add it under Settings > Security."
                ),
                "tenant": tenant_id,
            },
        )
