"""Per-tenant emergency write lockdown (\"freeze\").

When a workspace owner engages a freeze on their tenant, this middleware
rejects every state-changing HTTP request scoped to that tenant with
HTTP 423 ``tenant_frozen`` before the route handler runs. Read-only
methods (GET / HEAD / OPTIONS) are always allowed so investigators,
auditors, and exporters keep working during an incident.

A narrow allowlist of mutation paths must keep working while the
tenant is frozen:

* ``/v1/settings/security/freeze`` so the owner can lift the freeze.
* MFA enrolment + step-up so the owner can satisfy the gate on the
  freeze route if their session is fresh but the MFA challenge expired.
* ``/auth/logout`` and ``/v1/sessions/...`` revocation so any
  authenticated principal can sign out of a workspace they no longer
  trust.

Order requirement: this middleware reads ``request.state.tenant_id``,
so it must run AFTER ``TenantResolutionMiddleware`` on the inbound
path. With Starlette's last-added-is-outermost semantics, that means
adding it BEFORE ``TenantResolutionMiddleware`` in ``main.py`` so it
ends up more inner.
"""
from __future__ import annotations

import structlog
from prometheus_client import Counter
from shotclassify_store import get_freeze_state
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

log = structlog.get_logger(__name__)


FREEZE_REJECTIONS = Counter(
    "shotclassify_tenant_freeze_rejections_total",
    "HTTP write requests rejected because the tenant is in freeze mode.",
    ["tenant"],
)


MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


# Paths that must remain mutable while a freeze is engaged so the owner
# can lift the lockdown and members can sign out. Order matters: these
# are matched as prefixes.
DEFAULT_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/healthz",
    "/readyz",
    "/metrics",
    "/v1/settings/security/freeze",
    "/v1/mfa/",
    "/auth/logout",
    "/v1/sessions",
)


class FreezeMiddleware(BaseHTTPMiddleware):
    """Reject mutating requests when the caller's tenant is frozen."""

    def __init__(
        self,
        app,  # type: ignore[no-untyped-def]
        exempt_prefixes: tuple[str, ...] | None = None,
    ) -> None:
        super().__init__(app)
        self.exempt = exempt_prefixes or DEFAULT_EXEMPT_PREFIXES

    def _is_exempt(self, path: str) -> bool:
        for p in self.exempt:
            if path == p or path.startswith(p):
                return True
        return False

    async def dispatch(self, request: Request, call_next):
        if request.method.upper() not in MUTATING_METHODS:
            return await call_next(request)
        if self._is_exempt(request.url.path):
            return await call_next(request)
        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            # No resolved tenant means we have no policy to apply.
            return await call_next(request)
        state = get_freeze_state(tenant_id)
        if not state.frozen:
            return await call_next(request)
        FREEZE_REJECTIONS.labels(tenant=tenant_id).inc()
        principal = getattr(request.state, "principal", None)
        log.warning(
            "freeze.reject",
            tenant=tenant_id,
            principal=principal,
            method=request.method,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=423,
            content={
                "error": "tenant_frozen",
                "detail": (
                    "This workspace is in emergency freeze mode. "
                    "Writes are blocked until an owner lifts the freeze."
                ),
                "tenant_id": tenant_id,
                "reason": state.reason,
                "engaged_at": (
                    state.engaged_at.isoformat() if state.engaged_at else None
                ),
                "engaged_by": state.engaged_by,
            },
        )
