"""Request ID middleware."""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from structlog.contextvars import bind_contextvars, clear_contextvars


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        bind_contextvars(request_id=rid, path=request.url.path, method=request.method)
        try:
            response = await call_next(request)
        finally:
            clear_contextvars()
        response.headers["x-request-id"] = rid
        return response
