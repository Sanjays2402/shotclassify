"""Per-user saved views for the history page.

These endpoints let an authenticated principal (session login or API key)
save a named combination of history filters and re-apply it later. The
filter payload is whitelist-coerced inside the repository, so the route
itself stays thin.

Auth model matches the rest of the API: ``viewer`` can list/read its own
views, ``editor`` can create/update/delete. Rows are always scoped by
``(principal, tenant_id)``; there is no cross-user read path.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from shotclassify_store import SavedViewRepository
from shotclassify_store.saved_views import DuplicateSavedViewName

from ..dryrun import dry_run_query, mark_dry_run
from ..middleware.rbac import require_role, require_scope

router = APIRouter(prefix="/v1/saved-views", tags=["saved-views"])


def _scope(request: Request) -> tuple[str, str | None]:
    principal = getattr(request.state, "principal", None)
    if not principal:
        raise HTTPException(401, "Authenticated principal required.")
    tenant_id = getattr(request.state, "tenant_id", None)
    return principal, tenant_id


@router.get("", dependencies=[require_role("viewer"), require_scope("read:classifications")])
def list_views(request: Request) -> dict:
    principal, tenant_id = _scope(request)
    repo = SavedViewRepository()
    items = repo.list(principal=principal, tenant_id=tenant_id)
    return {"items": items, "count": len(items)}


@router.post("", dependencies=[require_role("operator"), require_scope("write:classifications")])
def create_view(request: Request, payload: dict = Body(...)) -> dict:
    principal, tenant_id = _scope(request)
    name = payload.get("name")
    filters = payload.get("filters") or {}
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(422, "name is required")
    if not isinstance(filters, dict):
        raise HTTPException(422, "filters must be an object")
    try:
        return SavedViewRepository().create(
            principal=principal,
            name=name,
            filters=filters,
            tenant_id=tenant_id,
        )
    except DuplicateSavedViewName as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/{view_id}/duplicate", dependencies=[require_role("operator"), require_scope("write:classifications")])
def duplicate_view(
    request: Request, view_id: str, payload: dict | None = Body(default=None)
) -> dict:
    """Clone a saved view for the same principal.

    Optional body: ``{"name": "...", "filters": {...}}``. When ``name`` is
    omitted the new view is called ``"{source} (copy)"`` (auto-suffixed if
    that name is taken). When ``filters`` is omitted the source filters are
    copied verbatim.
    """
    principal, tenant_id = _scope(request)
    payload = payload or {}
    name = payload.get("name")
    filters = payload.get("filters")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise HTTPException(422, "name must be a non-empty string")
    if filters is not None and not isinstance(filters, dict):
        raise HTTPException(422, "filters must be an object")
    try:
        row = SavedViewRepository().duplicate(
            view_id,
            principal=principal,
            name=name,
            filters=filters,
            tenant_id=tenant_id,
        )
    except DuplicateSavedViewName as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    if row is None:
        raise HTTPException(404, "saved view not found")
    return row


@router.get("/{view_id}", dependencies=[require_role("viewer"), require_scope("read:classifications")])
def get_view(request: Request, view_id: str) -> dict:
    principal, tenant_id = _scope(request)
    row = SavedViewRepository().get(
        view_id, principal=principal, tenant_id=tenant_id
    )
    if row is None:
        raise HTTPException(404, "saved view not found")
    return row


@router.patch("/{view_id}", dependencies=[require_role("operator"), require_scope("write:classifications")])
def update_view(
    request: Request, view_id: str, payload: dict = Body(...)
) -> dict:
    principal, tenant_id = _scope(request)
    name = payload.get("name")
    filters = payload.get("filters")
    if name is None and filters is None:
        raise HTTPException(422, "name or filters required")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise HTTPException(422, "name must be a non-empty string")
    if filters is not None and not isinstance(filters, dict):
        raise HTTPException(422, "filters must be an object")
    try:
        row = SavedViewRepository().update(
            view_id,
            principal=principal,
            name=name,
            filters=filters,
            tenant_id=tenant_id,
        )
    except DuplicateSavedViewName as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    if row is None:
        raise HTTPException(404, "saved view not found")
    return row


@router.delete("/{view_id}", dependencies=[require_role("operator"), require_scope("write:classifications")])
def delete_view(request: Request, view_id: str, dry_run: bool = dry_run_query()) -> dict | object:
    principal, tenant_id = _scope(request)
    repo = SavedViewRepository()
    if dry_run:
        existing = repo.get(view_id, principal=principal, tenant_id=tenant_id) if hasattr(repo, "get") else None
        present = existing is not None
        if not present:
            # Fallback: enumerate to check existence without mutating.
            try:
                rows = repo.list(principal=principal, tenant_id=tenant_id)
                present = any((r.get("id") if isinstance(r, dict) else getattr(r, "id", None)) == view_id for r in rows)
            except Exception:
                present = False
        request.state.audit_target_id = view_id
        return mark_dry_run(request, would_delete={"id": view_id} if present else None)
    ok = repo.delete(
        view_id, principal=principal, tenant_id=tenant_id
    )
    if not ok:
        raise HTTPException(404, "saved view not found")
    return {"ok": True, "id": view_id}
