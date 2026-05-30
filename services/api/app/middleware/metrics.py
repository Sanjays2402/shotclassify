"""Prometheus metrics middleware and /metrics endpoint.

Exposes per-route request counts, in-flight gauge, and latency histogram
labelled by method, route template (low cardinality), and status code.
"""
from __future__ import annotations

import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

# Use the default registry so multiple imports share the same collectors.
# This is created at import time so tests can rebuild the app and still
# see consistent series names.
REQUESTS_TOTAL = Counter(
    "shotclassify_http_requests_total",
    "Total HTTP requests processed by the API.",
    ["method", "route", "status"],
)

REQUEST_LATENCY = Histogram(
    "shotclassify_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

IN_FLIGHT = Gauge(
    "shotclassify_http_requests_in_flight",
    "Number of HTTP requests currently being processed.",
    ["method"],
)

EXCEPTIONS_TOTAL = Counter(
    "shotclassify_http_exceptions_total",
    "Unhandled exceptions raised while serving HTTP requests.",
    ["method", "route", "exception"],
)


def _route_template(request: Request) -> str:
    """Resolve the path template (e.g. /v1/items/{id}) for low-cardinality labels.

    Falls back to a sentinel for unknown paths so we never blow up the metric
    cardinality with arbitrary client-supplied URLs.
    """
    app = request.app
    router = getattr(app, "router", None)
    if router is None:
        return "__unknown__"
    for route in router.routes:
        try:
            match, _ = route.matches(request.scope)
        except Exception:  # noqa: S112 - skip non-matchable routes silently
            continue
        if match == Match.FULL:
            return getattr(route, "path", "__unknown__")
    return "__unknown__"


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip the metrics scrape itself so we do not self-amplify cardinality.
        if request.url.path == "/metrics":
            return await call_next(request)
        method = request.method
        IN_FLIGHT.labels(method=method).inc()
        start = time.perf_counter()
        route = "__unknown__"
        status = "500"
        try:
            response = await call_next(request)
            status = str(response.status_code)
            route = _route_template(request)
            return response
        except Exception as exc:
            route = _route_template(request)
            EXCEPTIONS_TOTAL.labels(
                method=method, route=route, exception=type(exc).__name__
            ).inc()
            raise
        finally:
            elapsed = time.perf_counter() - start
            REQUEST_LATENCY.labels(method=method, route=route).observe(elapsed)
            REQUESTS_TOTAL.labels(method=method, route=route, status=status).inc()
            IN_FLIGHT.labels(method=method).dec()


def metrics_response() -> Response:
    """Render Prometheus exposition format.

    Supports multiprocess mode when the PROMETHEUS_MULTIPROC_DIR env var is
    set (gunicorn/uvicorn workers), otherwise serves from the default registry.
    """
    import os

    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        data = generate_latest(registry)
    else:
        data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
