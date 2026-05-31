"""Legal-acceptance enforcement gate.

When a workspace owner toggles ``enforce=true`` on the legal agreements
page, every mutating ``/v1`` request from that workspace is rejected
with ``HTTP 451 Unavailable For Legal Reasons`` until the current
versions of all required agreements have been accepted.

The middleware depends on ``request.state.tenant_id`` (set by
``TenantResolutionMiddleware``) and ``request.state.principal`` (set by
``APIKeyAndSessionAuth``), so it must run AFTER both on the inbound
path. It deliberately exempts:

* read-only methods (``GET``, ``HEAD``, ``OPTIONS``);
* auth, health, blob, well-known, and the trust/legal routes themselves
  (otherwise an over-eager flip would lock out the route used to accept
  agreements);
* unauthenticated requests (handled by the auth layer's 401);
* requests that did not resolve to a tenant (e.g. probes).

The response body carries the list of missing agreement ids so the UI
can deep-link the operator straight to the acceptance page.
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from shotclassify_store import legal_agreements_store
from starlette.middleware.base import BaseHTTPMiddleware

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Routes that must remain reachable even when the gate is armed.
EXEMPT_PREFIXES = (
    "/healthz",
    "/readyz",
    "/auth/",
    "/v1/trust/legal",  # accept + enforcement endpoints themselves
    "/v1/trust/subprocessors",  # sub-processor acks are policy-adjacent
    "/.well-known/",
    "/docs",
    "/redoc",
    "/openapi.json",
)


class LegalAcceptanceGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        method = request.method.upper()
        if method not in MUTATING_METHODS:
            return await call_next(request)
        path = request.url.path
        if any(path.startswith(p) for p in EXEMPT_PREFIXES):
            return await call_next(request)
        principal = getattr(request.state, "principal", None)
        if not principal:
            # Auth layer will handle the 401; do not double-respond.
            return await call_next(request)
        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            return await call_next(request)
        try:
            missing = legal_agreements_store.gate_blocks(tenant_id)
        except Exception:
            # Fail open on infra errors so legal enforcement never causes
            # an outage; the audit middleware still records the attempt.
            return await call_next(request)
        if not missing:
            return await call_next(request)
        return JSONResponse(
            status_code=451,
            content={
                "detail": (
                    "This workspace has enabled legal-acceptance "
                    "enforcement and one or more required agreements have "
                    "not been accepted at their current version."
                ),
                "tenant_id": tenant_id,
                "missing_required": missing,
                "remediation": (
                    "An admin must visit /admin/legal and accept the "
                    "listed agreements, or disable enforcement."
                ),
            },
            headers={"X-Legal-Gate": "missing:" + ",".join(missing)},
        )
