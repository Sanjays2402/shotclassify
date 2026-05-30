"""Security response headers middleware.

Applies a baseline set of HTTP security headers (CSP, X-Frame-Options,
X-Content-Type-Options, Referrer-Policy, Permissions-Policy, HSTS) to every
response so the API and its served frontend assets get sane defaults out of
the box. Header values are driven by ``Settings`` so operators can override
them without code changes. HSTS is intentionally restricted to production to
avoid pinning dev/staging browsers onto HTTPS-only behavior.
"""
from __future__ import annotations

from shotclassify_common import get_settings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        s = get_settings()
        if not s.security_headers_enabled:
            return response

        headers = response.headers
        headers.setdefault("Content-Security-Policy", s.security_csp)
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", s.security_referrer_policy)
        headers.setdefault("Permissions-Policy", s.security_permissions_policy)
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")

        if s.app_env == "production" and s.security_hsts_max_age > 0:
            headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={s.security_hsts_max_age}; includeSubDomains",
            )
        return response
