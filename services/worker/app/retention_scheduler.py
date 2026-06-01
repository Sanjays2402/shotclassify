"""Periodic retention enforcement for the worker process.

Per-tenant retention windows are configured by workspace admins via
``PUT /v1/settings/retention``. Without an automated enforcer the policy
is purely declarative, which is unacceptable for any procurement that
mentions GDPR/CCPA/SOC2: the auditor's first question is "show me when
expired data is actually destroyed". This module is that enforcer.

Design:

* A small daemon thread is started by the worker entrypoint when
  ``RETENTION_SCHEDULER_ENABLED`` is true.
* Every ``RETENTION_SCHEDULER_INTERVAL_S`` seconds (floor: 60) it iterates
  every tenant with a positive retention policy and runs
  :func:`purge_expired_for_tenant`. Tenants without a policy are skipped.
* Each non-trivial purge writes one audit row scoped to the tenant so the
  workspace owner sees automatic deletions in the same audit log as
  manual ones.
* All exceptions are caught and logged; one tenant's broken state must
  never stop the scheduler.

The scheduler is intentionally in-process (not RQ) so it has zero new
runtime dependencies and runs even when Redis is briefly unavailable.
"""
from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Callable

from shotclassify_common import get_logger, get_settings
from shotclassify_store import (
    AuditRepository,
    list_tenants_with_retention,
    list_tenants_with_audit_retention,
    purge_expired_audit_for_tenant,
    purge_expired_for_tenant,
)

log = get_logger(__name__)

_MIN_INTERVAL_S = 60
_SYSTEM_PRINCIPAL = "system:retention-scheduler"


def run_once(*, now: datetime | None = None) -> list[dict]:
    """Run a single pass across every tenant with a retention policy.

    Returns a list of per-tenant result dicts so tests and the optional
    manual CLI can assert on what happened.
    """
    audit = AuditRepository()
    results: list[dict] = []
    tenants = list_tenants_with_retention()
    for tenant_id in tenants:
        try:
            res = purge_expired_for_tenant(tenant_id, now=now)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception(
                "retention_purge_failed", tenant_id=tenant_id, error=str(exc)
            )
            results.append(
                {"tenant_id": tenant_id, "error": str(exc), "removed": 0}
            )
            continue
        results.append(res.to_dict())
        # Only audit when something was actually removed; a no-op pass
        # would otherwise spam the audit log every interval.
        if res.removed > 0:
            try:
                audit.record(
                    principal=_SYSTEM_PRINCIPAL,
                    method="JOB",
                    path="/internal/retention/purge",
                    status_code=200,
                    tenant_id=tenant_id,
                    extra={
                        "removed": res.removed,
                        "retention_days": res.retention_days,
                        "cutoff": res.cutoff.isoformat(),
                        "trigger": "scheduler",
                    },
                )
            except Exception:  # pragma: no cover - audit best-effort
                log.exception("retention_audit_failed", tenant_id=tenant_id)
            log.info(
                "retention_purge",
                tenant_id=tenant_id,
                removed=res.removed,
                retention_days=res.retention_days,
            )
    # Audit-log retention runs in the same pass so operators only need to
    # schedule one worker. The two policies are independent: a tenant may
    # set only the audit window, only the classifications window, both,
    # or neither.
    audit_tenants = list_tenants_with_audit_retention()
    for tenant_id in audit_tenants:
        try:
            ares = purge_expired_audit_for_tenant(tenant_id, now=now)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception(
                "audit_retention_purge_failed",
                tenant_id=tenant_id,
                error=str(exc),
            )
            results.append(
                {
                    "tenant_id": tenant_id,
                    "error": str(exc),
                    "removed": 0,
                    "kind": "audit",
                }
            )
            continue
        d = ares.to_dict()
        d["kind"] = "audit"
        results.append(d)
        if ares.removed > 0:
            try:
                # The purge intentionally breaks the per-tenant audit hash
                # chain for the deleted window; this audit entry is the
                # disclosed record of that break so verify_chain reports
                # an expected, attributable gap rather than an undisclosed
                # mutation.
                audit.record(
                    principal=_SYSTEM_PRINCIPAL,
                    method="JOB",
                    path="/internal/audit-retention/purge",
                    status_code=200,
                    tenant_id=tenant_id,
                    extra={
                        "removed": ares.removed,
                        "audit_retention_days": ares.audit_retention_days,
                        "cutoff": ares.cutoff.isoformat(),
                        "trigger": "scheduler",
                    },
                )
            except Exception:  # pragma: no cover - audit best-effort
                log.exception(
                    "audit_retention_audit_failed", tenant_id=tenant_id
                )
            log.info(
                "audit_retention_purge",
                tenant_id=tenant_id,
                removed=ares.removed,
                audit_retention_days=ares.audit_retention_days,
            )
    return results


def _loop(interval_s: int, stop_event: threading.Event, sleeper: Callable[[float], None]) -> None:
    log.info("retention_scheduler_started", interval_s=interval_s)
    # Stagger the first run by a small amount so worker boot logs are not
    # interleaved with a purge on every restart.
    if stop_event.wait(min(15, interval_s)):
        return
    while not stop_event.is_set():
        started = time.monotonic()
        try:
            run_once()
        except Exception:  # pragma: no cover - defensive
            log.exception("retention_scheduler_iteration_failed")
        elapsed = time.monotonic() - started
        remaining = max(1.0, interval_s - elapsed)
        if stop_event.wait(remaining):
            return


def start_in_background() -> tuple[threading.Thread, threading.Event] | None:
    """Spawn the scheduler thread. Returns (thread, stop_event) or None when disabled."""
    s = get_settings()
    if not s.retention_scheduler_enabled:
        log.info("retention_scheduler_disabled")
        return None
    interval = max(_MIN_INTERVAL_S, int(s.retention_scheduler_interval_s))
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_loop,
        args=(interval, stop_event, time.sleep),
        name="retention-scheduler",
        daemon=True,
    )
    thread.start()
    return thread, stop_event
