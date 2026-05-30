"""Liveness and readiness endpoints.

``/healthz`` is a cheap liveness probe: it returns 200 as long as the
process can serve HTTP. It does not touch the database or any external
dependency, so kubelet does not restart pods when a backing service has
a transient outage.

``/readyz`` is a deep readiness probe. It actively checks each hard
dependency (database, object storage directory, Redis when configured)
and returns HTTP 503 when any check fails. Kubernetes uses this to pull
the pod out of the Service endpoints while the dependency recovers,
which is what readiness probes are for. The previous implementation
returned 200 unconditionally and so was effectively a no-op as a probe.

The response body always reports per-check status (ok/error/skipped) so
operators can see at a glance which dependency is degraded without
hitting logs.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Response
from shotclassify_common import get_settings
from shotclassify_store import db, init_db
from sqlalchemy import text

router = APIRouter(tags=["health"])

# How long any single readiness check may block before we consider it
# failed. Probes must be fast or the kubelet times out and flaps.
_READY_TIMEOUT_S = 2.0


@router.get("/")
def root() -> dict[str, str]:
    return {"service": "shotclassify", "version": "0.1.0"}


@router.get("/healthz")
def healthz() -> dict[str, str]:
    # Liveness: process is up and the event loop is responsive.
    return {"status": "ok"}


def _check_db() -> tuple[str, str | None]:
    """Round-trip a trivial query against the configured database."""
    try:
        init_db()
        engine = db.get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok", None
    except Exception as exc:  # pragma: no cover - exercised via monkeypatch
        return "error", f"{type(exc).__name__}: {exc}"


def _check_storage(path: str) -> tuple[str, str | None]:
    """Storage dir must exist and be writable; workers depend on it."""
    try:
        if not os.path.isdir(path):
            return "error", f"missing: {path}"
        if not os.access(path, os.W_OK):
            return "error", f"not writable: {path}"
        return "ok", None
    except Exception as exc:  # pragma: no cover
        return "error", f"{type(exc).__name__}: {exc}"


def _check_redis(url: str) -> tuple[str, str | None]:
    """Ping Redis with a short timeout. Skipped if the client is absent."""
    try:
        from redis import Redis  # type: ignore
    except Exception:
        return "skipped", "redis client not installed"
    try:
        client = Redis.from_url(
            url,
            socket_connect_timeout=_READY_TIMEOUT_S,
            socket_timeout=_READY_TIMEOUT_S,
        )
        if not client.ping():
            return "error", "ping returned false"
        return "ok", None
    except Exception as exc:
        return "error", f"{type(exc).__name__}: {exc}"


@router.get("/readyz")
def readyz(response: Response) -> dict[str, Any]:
    s = get_settings()
    checks: dict[str, dict[str, Any]] = {}

    db_status, db_detail = _check_db()
    checks["db"] = {"status": db_status}
    if db_detail:
        checks["db"]["detail"] = db_detail

    storage_status, storage_detail = _check_storage(s.storage_local_dir)
    checks["storage"] = {"status": storage_status}
    if storage_detail:
        checks["storage"]["detail"] = storage_detail

    # Redis is only required when a non-default URL is configured or the
    # worker queue is in use. We still probe the default so operators get
    # signal, but a connection failure to localhost in development should
    # not fail the probe.
    redis_status, redis_detail = _check_redis(s.redis_url)
    checks["redis"] = {"status": redis_status}
    if redis_detail:
        checks["redis"]["detail"] = redis_detail
    redis_required = s.app_env not in ("development", "test")

    hard_failed = any(
        c["status"] == "error"
        for name, c in checks.items()
        if name != "redis" or redis_required
    )
    overall = "degraded" if hard_failed else "ready"
    if hard_failed:
        response.status_code = 503

    return {"status": overall, "checks": checks}
