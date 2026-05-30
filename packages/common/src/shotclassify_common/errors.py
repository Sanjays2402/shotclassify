"""Sentry error tracking wiring.

Initialization is a no-op unless ``SENTRY_DSN`` is set in the environment.
The Sentry SDK is imported lazily so the project keeps working in
environments where the package is unavailable (development, CI without the
extra installed).
"""
from __future__ import annotations

import logging
from typing import Any

from .settings import get_settings

_log = logging.getLogger(__name__)

_initialized: bool = False
_sentry_module: Any | None = None


def _scrub_event(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    """Strip auth headers, cookies, and API keys from Sentry payloads.

    Returning ``None`` from a ``before_send`` hook drops the event. We never
    drop here, but we mutate the event to remove secrets that the FastAPI
    integration would otherwise capture from request scope.
    """
    request = event.get("request") or {}
    headers = request.get("headers")
    if isinstance(headers, dict):
        for key in list(headers):
            lk = key.lower()
            if lk in {"authorization", "cookie", "x-api-key", "x-auth-token"}:
                headers[key] = "[Filtered]"
    if "cookies" in request:
        request["cookies"] = {}
    # Drop env QUERY_STRING values that might leak api keys
    env = request.get("env")
    if isinstance(env, dict) and "QUERY_STRING" in env:
        env["QUERY_STRING"] = "[Filtered]"
    extra = event.get("extra") or {}
    for k in list(extra):
        if "key" in k.lower() or "secret" in k.lower() or "token" in k.lower():
            extra[k] = "[Filtered]"
    return event


def init_sentry(service_name: str | None = None) -> bool:
    """Initialize Sentry once per process.

    Returns ``True`` when the SDK was initialized, ``False`` otherwise
    (DSN missing, SDK not installed, or already initialized).
    """
    global _initialized, _sentry_module
    if _initialized:
        return False
    s = get_settings()
    dsn = (s.sentry_dsn or "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except Exception as exc:  # pragma: no cover - exercised in environments without sdk
        _log.warning("sentry_sdk unavailable, skipping init: %s", exc)
        return False

    logging_integration = LoggingIntegration(
        level=logging.INFO,
        event_level=logging.ERROR,
    )

    sentry_sdk.init(
        dsn=dsn,
        environment=s.app_env,
        release=s.sentry_release or None,
        server_name=service_name or s.otel_service_name,
        traces_sample_rate=float(s.sentry_traces_sample_rate),
        profiles_sample_rate=float(s.sentry_profiles_sample_rate),
        sample_rate=float(s.sentry_sample_rate),
        send_default_pii=False,
        attach_stacktrace=True,
        max_breadcrumbs=64,
        before_send=_scrub_event,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
            logging_integration,
        ],
    )
    _sentry_module = sentry_sdk
    _initialized = True
    _log.info("sentry initialized", extra={"environment": s.app_env})
    return True


def is_initialized() -> bool:
    return _initialized


def capture_exception(exc: BaseException) -> str | None:
    """Forward an exception to Sentry if initialized; return event id or None."""
    if not _initialized or _sentry_module is None:
        return None
    try:
        return _sentry_module.capture_exception(exc)
    except Exception:  # pragma: no cover - never raise from telemetry
        return None


def _reset_for_tests() -> None:
    """Drop init state. Intended for the test suite only."""
    global _initialized, _sentry_module
    _initialized = False
    _sentry_module = None
