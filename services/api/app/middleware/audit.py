"""Audit log middleware.

Records authenticated, state-changing requests to the persisted audit_log table
so operators have a tamper-evident trail of who did what when.

Read-only requests (GET, HEAD, OPTIONS) and unauthenticated/public paths are
skipped to keep the table focused on actions worth reviewing.
"""
from __future__ import annotations

import re
import threading
import time

import structlog
from shotclassify_common import get_settings
from shotclassify_store import AuditRepository, audit_sinks_store
from shotclassify_store import webhooks as webhooks_store
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

log = structlog.get_logger(__name__)


# (method, compiled-path-regex) -> security event name. The path patterns
# are anchored against the full request path. Order does not matter; the
# first match wins. Keep this table tight: any entry here means the audit
# middleware will fan an event out to webhook subscribers, which is a
# customer-visible contract.
_SECURITY_EVENT_TABLE: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("PUT", re.compile(r"^/v1/members/[^/]+/role$"), "security.role_changed"),
    ("POST", re.compile(r"^/v1/invitations$"), "security.member_invited"),
    ("DELETE", re.compile(r"^/v1/invitations/[^/]+$"), "security.invitation_revoked"),
    ("DELETE", re.compile(r"^/v1/members/[^/]+$"), "security.member_removed"),
    ("POST", re.compile(r"^/v1/api-keys$"), "security.api_key_created"),
    ("DELETE", re.compile(r"^/v1/api-keys/[^/]+$"), "security.api_key_revoked"),
    ("PATCH", re.compile(r"^/v1/api-keys/[^/]+(/.*)?$"), "security.api_key_updated"),
    ("DELETE", re.compile(r"^/v1/sessions/[^/]+$"), "security.session_revoked"),
    ("POST", re.compile(r"^/v1/sessions/revoke-all$"), "security.sessions_revoked_all"),
    ("POST", re.compile(r"^/v1/sessions/admin/revoke-principal$"), "security.sessions_revoked_all"),
    ("DELETE", re.compile(r"^/v1/mfa$"), "security.mfa_disabled"),
    ("PUT", re.compile(r"^/v1/sso/.*"), "security.sso_config_changed"),
    ("POST", re.compile(r"^/v1/sso/.*"), "security.sso_config_changed"),
    ("PATCH", re.compile(r"^/v1/sso/.*"), "security.sso_config_changed"),
    ("DELETE", re.compile(r"^/v1/sso/.*"), "security.sso_config_changed"),
    ("POST", re.compile(r"^/v1/support-access$"), "security.support_access_granted"),
    ("DELETE", re.compile(r"^/v1/support-access/[^/]+$"), "security.support_access_revoked"),
    ("POST", re.compile(r"^/v1/workspace/teardown$"), "security.workspace_teardown_scheduled"),
    ("DELETE", re.compile(r"^/v1/workspace/teardown$"), "security.workspace_teardown_cancelled"),
    ("POST", re.compile(r"^/v1/workspace/teardown/execute$"), "security.workspace_teardown_executed"),
    ("PUT", re.compile(r"^/v1/security/ip-allowlist$"), "security.ip_allowlist_changed"),
    ("PATCH", re.compile(r"^/v1/security/ip-allowlist$"), "security.ip_allowlist_changed"),
    ("POST", re.compile(r"^/v1/webhooks$"), "security.webhook_subscription_created"),
    ("DELETE", re.compile(r"^/v1/webhooks/[^/]+$"), "security.webhook_subscription_revoked"),
)


def _resolve_security_event(method: str, path: str) -> str | None:
    for m, pat, name in _SECURITY_EVENT_TABLE:
        if m == method and pat.match(path):
            return name
    return None


def _fanout_security_event(
    *,
    tenant_id: str,
    event: str,
    payload: dict,
    request_id: str | None,
) -> None:
    """Fire a security webhook in a background thread so the request path
    is never blocked on retries or backoff sleeps."""
    def _run() -> None:
        try:
            webhooks_store.dispatch_event(
                tenant_id=tenant_id,
                event=event,
                payload=payload,
                request_id=request_id,
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "security_webhook_dispatch_failed",
                error=str(exc),
                webhook_event=event,
                tenant_id=tenant_id,
            )

    t = threading.Thread(
        target=_run, name=f"security-webhook:{event}", daemon=True
    )
    t.start()

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Paths that should never be audited even if they happen to be POSTed
# (e.g. health probes from k8s, OAuth callbacks, static blob fetches).
SKIP_PATH_PREFIXES = (
    "/healthz",
    "/readyz",
    "/auth/",
    "/docs",
    "/redoc",
    "/openapi.json",
)


class AuditLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        method = request.method.upper()
        path = request.url.path
        if method not in MUTATING_METHODS:
            return response
        if any(path.startswith(p) for p in SKIP_PATH_PREFIXES):
            return response
        principal = getattr(request.state, "principal", None)
        # Only audit when auth middleware identified a principal. Unauthenticated
        # 401s are already visible in request logs.
        if not principal:
            return response
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        request_id = response.headers.get("x-request-id")
        target_id = None
        # Common pattern: /v1/<resource>/<id>/...
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 3 and parts[0] == "v1":
            target_id = parts[2]
        client_ip = request.client.host if request.client else None
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        extra = getattr(request.state, "audit_extra", None) or None
        if getattr(request.state, "dry_run", False) and (extra is None or "dry_run" not in extra):
            extra = {**(extra or {}), "dry_run": True}
        try:
            AuditRepository().record(
                principal=str(principal),
                method=method,
                path=path,
                status_code=response.status_code,
                request_id=request_id,
                client_ip=client_ip,
                user_agent=request.headers.get("user-agent"),
                elapsed_ms=elapsed_ms,
                target_id=target_id,
                tenant_id=getattr(request.state, "tenant_id", None),
                extra=extra,
            )
        except Exception as exc:  # pragma: no cover - never break the request path
            log.warning("audit_log_write_failed", error=str(exc), path=path)
        # Best-effort fan-out to per-tenant SIEM sinks. Never block, never
        # raise; a slow downstream collector must not affect this request.
        tenant_id = getattr(request.state, "tenant_id", None)
        if tenant_id:
            try:
                s = get_settings()
                audit_sinks_store.dispatch_event(
                    tenant_id,
                    {
                        "type": "shotclassify.audit",
                        "tenant_id": tenant_id,
                        "principal": str(principal),
                        "method": method,
                        "path": path,
                        "status_code": response.status_code,
                        "request_id": request_id,
                        "client_ip": client_ip,
                        "user_agent": request.headers.get("user-agent"),
                        "elapsed_ms": elapsed_ms,
                        "target_id": target_id,
                        "extra": extra or {},
                    },
                    allow_http=s.webhook_egress_allow_http,
                    allow_private=s.webhook_egress_allow_private,
                    extra_blocked_cidrs=s.webhook_egress_extra_blocked_cidrs,
                )
            except Exception as exc:  # pragma: no cover - never break the request path
                log.warning("audit_sink_dispatch_failed", error=str(exc), path=path)
        # Per-tenant security event webhook fan-out. Mirrors the SIEM sink
        # above but targets the customer-facing webhook subscriptions so
        # buyers can wire admin-action alerts into their own SIEM / Slack
        # without standing up a separate ingestion endpoint. Only fired on
        # 2xx responses so a denied or validation-failed request does not
        # generate a misleading delivery.
        if (
            tenant_id
            and 200 <= response.status_code < 300
            and not getattr(request.state, "dry_run", False)
        ):
            event_name = _resolve_security_event(method, path)
            if event_name is not None:
                _fanout_security_event(
                    tenant_id=tenant_id,
                    event=event_name,
                    payload={
                        "event": event_name,
                        "tenant_id": tenant_id,
                        "principal": str(principal),
                        "method": method,
                        "path": path,
                        "status_code": response.status_code,
                        "request_id": request_id,
                        "client_ip": client_ip,
                        "target_id": target_id,
                        "occurred_at_ms": int(time.time() * 1000),
                    },
                    request_id=request_id,
                )
        return response
