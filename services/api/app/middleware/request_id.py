"""Request ID, OTEL trace correlation, and structured access logging."""
from __future__ import annotations

import time
import uuid

from shotclassify_common.logging import get_logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from structlog.contextvars import bind_contextvars, clear_contextvars

_log = get_logger("http.access")


def _current_trace_ids() -> tuple[str | None, str | None]:
    """Return (trace_id, span_id) as hex strings if an OTEL span is recording.

    Returns (None, None) when OpenTelemetry is unavailable or no span is active.
    Safe to call when OTEL is disabled.
    """
    try:
        from opentelemetry import trace as _trace
    except Exception:
        return None, None
    span = _trace.get_current_span()
    ctx = span.get_span_context() if span is not None else None
    if ctx is None or not getattr(ctx, "is_valid", False):
        return None, None
    return f"{ctx.trace_id:032x}", f"{ctx.span_id:016x}"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assign request_id, bind log context (with OTEL trace ids), emit access log.

    Behaviour:
    - Honours inbound ``x-request-id`` or generates a hex uuid.
    - Binds ``request_id``, ``path``, ``method`` into structlog contextvars so
      all downstream logs carry them.
    - When an OTEL span is recording, also binds ``trace_id`` and ``span_id``
      so logs and traces can be correlated in the observability backend.
    - Emits one ``http.access`` log line per request with status, latency_ms,
      and principal subject when present.
    - Echoes ``x-request-id`` and, when available, ``x-trace-id`` response
      headers so clients can quote them in bug reports.
    """

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        ctx: dict[str, str] = {
            "request_id": rid,
            "path": request.url.path,
            "method": request.method,
        }
        trace_id, span_id = _current_trace_ids()
        if trace_id:
            ctx["trace_id"] = trace_id
        if span_id:
            ctx["span_id"] = span_id
        bind_contextvars(**ctx)

        start = time.perf_counter()
        status = 500
        response = None
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
            principal = getattr(request.state, "principal", None)
            sub = getattr(principal, "subject", None) if principal else None
            client = request.client.host if request.client else None
            _log.info(
                "http.access",
                status=status,
                latency_ms=latency_ms,
                principal=sub,
                client=client,
            )
            if response is not None:
                response.headers["x-request-id"] = rid
                if trace_id:
                    response.headers["x-trace-id"] = trace_id
            clear_contextvars()
