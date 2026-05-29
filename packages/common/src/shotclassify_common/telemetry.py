"""OpenTelemetry helpers. No-op when OTEL_ENABLED=false."""
from __future__ import annotations

from typing import Any

from .settings import get_settings


def setup_telemetry(service_name: str | None = None) -> Any:
    s = get_settings()
    if not s.otel_enabled:
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception:
        return None
    resource = Resource.create({"service.name": service_name or s.otel_service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=s.otel_exporter_otlp_endpoint, insecure=True))
    )
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name or s.otel_service_name)


def instrument_fastapi(app: Any) -> None:
    s = get_settings()
    if not s.otel_enabled:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception:
        return
