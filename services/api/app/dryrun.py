"""Sandbox / dry-run helper.

Enterprise procurement reviewers ask: "can my admins preview what a
destructive call would do before it actually runs?". Every mutating
endpoint that destroys data accepts ``?dry_run=true`` and routes through
:func:`mark_dry_run` so:

* the response body carries ``dry_run: true`` and a ``would_*`` preview
  of what would change,
* the audit log middleware writes the row with ``extra.dry_run=true`` so
  operators can distinguish previews from real mutations in the SIEM,
* the HTTP response carries ``X-Dry-Run: true`` so proxies, CI checks
  and client SDKs can assert on it without parsing JSON.

Endpoints that mutate state MUST short-circuit when ``dry_run`` is true
and MUST NOT call the underlying delete/revoke method.
"""
from __future__ import annotations

from typing import Any

from fastapi import Query, Request
from fastapi.responses import JSONResponse


DRY_RUN_HEADER = "X-Dry-Run"


def dry_run_query() -> Any:
    """FastAPI ``Query`` dependency for the canonical ``dry_run`` flag.

    Accepts the common spellings ``true``/``1``/``yes`` (FastAPI handles
    the bool coercion) and defaults to ``False`` so existing callers
    behave exactly as before.
    """
    return Query(
        False,
        alias="dry_run",
        description=(
            "When true, preview the effect of this destructive call without "
            "actually mutating state. The response includes a `would_*` "
            "summary and the X-Dry-Run header is set."
        ),
    )


def mark_dry_run(request: Request, **preview: Any) -> JSONResponse:
    """Record a dry-run on the request and return the standardized payload.

    ``preview`` keyword arguments are merged into the response body. By
    convention, callers pass ``would_delete``, ``would_revoke``, etc.
    """
    request.state.dry_run = True
    request.state.audit_extra = {
        **(getattr(request.state, "audit_extra", None) or {}),
        "dry_run": True,
    }
    body: dict[str, Any] = {"dry_run": True, "applied": False}
    body.update(preview)
    return JSONResponse(body, headers={DRY_RUN_HEADER: "true"})
