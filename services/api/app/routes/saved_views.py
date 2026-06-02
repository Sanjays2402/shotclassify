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

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import Response

from shotclassify_store import SavedViewRepository
from shotclassify_store.saved_views import PER_USER_MAX, DuplicateSavedViewName

from ..dryrun import dry_run_query, mark_dry_run
from ..middleware.rbac import require_role, require_scope

router = APIRouter(prefix="/v1/saved-views", tags=["saved-views"])


def _scope(request: Request) -> tuple[str, str | None]:
    principal = getattr(request.state, "principal", None)
    if not principal:
        raise HTTPException(401, "Authenticated principal required.")
    tenant_id = getattr(request.state, "tenant_id", None)
    return principal, tenant_id


_SORT_CHOICES = {
    "updated_desc",
    "updated_asc",
    "created_desc",
    "created_asc",
    "name_asc",
    "name_desc",
}


@router.get("", dependencies=[require_role("viewer"), require_scope("read:classifications")])
def list_views(
    request: Request,
    q: str | None = Query(
        None,
        description=(
            "Optional case-insensitive substring filter on the view name. "
            "Whitespace is trimmed; an empty/whitespace value behaves like "
            "no filter. Helps users with a long sidebar narrow down "
            "without scrolling."
        ),
        max_length=200,
    ),
    sort: str = Query(
        "updated_desc",
        description=(
            "Sort order for the returned items. One of: "
            "``updated_desc`` (default, most recently edited first), "
            "``updated_asc``, ``created_desc``, ``created_asc``, "
            "``name_asc`` (alphabetical, case-insensitive), "
            "``name_desc``. Unknown values return 400 instead of "
            "silently falling back, so the sidebar UI cannot drift out "
            "of sync with what the API actually returned."
        ),
    ),
) -> dict:
    if sort not in _SORT_CHOICES:
        raise HTTPException(
            400,
            f"unknown sort '{sort}'; expected one of {sorted(_SORT_CHOICES)}",
        )
    principal, tenant_id = _scope(request)
    repo = SavedViewRepository()
    items = repo.list(principal=principal, tenant_id=tenant_id)
    needle = (q or "").strip().lower()
    if needle:
        items = [
            r
            for r in items
            if isinstance(r, dict)
            and needle in (r.get("name") or "").lower()
        ]
    if sort != "updated_desc":
        items = _sort_views(items, sort)
    return {"items": items, "count": len(items)}


def _sort_views(items: list[dict], sort: str) -> list[dict]:
    if sort.startswith("name_"):
        key = lambda r: (r.get("name") or "").lower()  # noqa: E731
        return sorted(items, key=key, reverse=sort == "name_desc")
    field = "created_at" if sort.startswith("created_") else "updated_at"
    reverse = sort.endswith("_desc")
    # Missing timestamps sort to the end regardless of direction so they
    # never silently jump to the top when the field is null.
    sentinel = "" if reverse else "\uffff"
    return sorted(items, key=lambda r: (r.get(field) or sentinel), reverse=reverse)


@router.get(
    "/quota",
    dependencies=[require_role("viewer"), require_scope("read:classifications")],
)
def get_quota(request: Request) -> dict:
    """Return how many saved views the caller has used vs. the per-user cap.

    Lets the UI show "47/50 used, 3 remaining" next to the New View button
    and disable the button (with a clear reason) before the user types a
    name only to hit a 422 on submit. Scope matches ``GET /v1/saved-views``:
    only the calling principal's rows in the current tenant are counted.
    """
    principal, tenant_id = _scope(request)
    items = SavedViewRepository().list(principal=principal, tenant_id=tenant_id)
    used = len(items)
    remaining = max(PER_USER_MAX - used, 0)
    return {
        "used": used,
        "limit": PER_USER_MAX,
        "remaining": remaining,
        "at_limit": used >= PER_USER_MAX,
    }


_EXPORT_MAX_IDS = 200


@router.get(
    "/export",
    dependencies=[require_role("viewer"), require_scope("read:classifications")],
)
def export_views(
    request: Request,
    ids: str | None = Query(
        None,
        description=(
            "Optional comma-separated list of view ids to include. When "
            "omitted, every saved view owned by the caller in the current "
            "tenant is exported. Unknown ids are silently dropped so a "
            "partial selection still produces a usable backup; the "
            "response's ``count`` reflects what actually shipped. Capped "
            f"at {_EXPORT_MAX_IDS} ids per call."
        ),
    ),
    q: str | None = Query(
        None,
        description=(
            "Optional case-insensitive substring filter on the view "
            "name, matching ``GET /v1/saved-views``. Lets users export "
            "\"all my receipts views\" without first calling list to "
            "collect ids. Mutually exclusive with ``ids``: combining "
            "them returns 422 so the caller does not have to guess "
            "whether the filters AND or OR."
        ),
        max_length=200,
    ),
) -> Response:
    """Download the caller's saved views as a JSON file.

    Lets a user back up or migrate their personal filter sidebar without
    going through workspace-wide admin exports. Scope is the same as
    ``GET /v1/saved-views``: only rows owned by the calling principal in
    the current tenant are returned, with all repository-side coercion
    already applied. Pass ``?ids=a,b,c`` to export just a subset, which
    is the common case when migrating a hand-picked few views between
    workspaces instead of the whole sidebar.
    """
    principal, tenant_id = _scope(request)
    needle = (q or "").strip().lower()
    if ids is not None and needle:
        raise HTTPException(
            422,
            "ids and q are mutually exclusive; pick one",
        )
    wanted: set[str] | None = None
    if ids is not None:
        wanted = {tok.strip() for tok in ids.split(",") if tok.strip()}
        if len(wanted) > _EXPORT_MAX_IDS:
            raise HTTPException(
                422,
                f"too many ids ({len(wanted)}); max {_EXPORT_MAX_IDS} per export",
            )
    items = SavedViewRepository().list(principal=principal, tenant_id=tenant_id)
    if wanted is not None:
        items = [
            r
            for r in items
            if isinstance(r, dict) and r.get("id") in wanted
        ]
    elif needle:
        items = [
            r
            for r in items
            if isinstance(r, dict)
            and needle in (r.get("name") or "").lower()
        ]
    now = datetime.now(UTC)
    body = {
        "schema": "shotclassify.saved_views.v1",
        "exported_at": now.isoformat(),
        "principal": principal,
        "tenant_id": tenant_id,
        "count": len(items),
        "items": items,
    }
    filename = f"saved-views-{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    return Response(
        content=json.dumps(body, indent=2, sort_keys=True),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


_VALID_CONFLICT_MODES = ("skip", "rename", "error")
_IMPORT_MAX_ITEMS = 200


_BULK_DELETE_MAX = 200


@router.post(
    "/bulk-delete",
    dependencies=[require_role("operator"), require_scope("write:classifications")],
)
def bulk_delete_views(
    request: Request,
    payload: dict = Body(...),
    dry_run: bool = dry_run_query(),
) -> dict | object:
    """Delete several of the caller's saved views in one call.

    Body: ``{"ids": ["a", "b", ...]}``. Only rows owned by the calling
    principal in the current tenant are touched; unknown or foreign ids
    land in ``not_found`` instead of erroring out the whole batch, so the
    sidebar's "clear selected" action does not have to retry one id at a
    time after a stale tab. Pass ``?dry_run=true`` to preview the split
    without writing.
    """
    ids_raw = payload.get("ids")
    if not isinstance(ids_raw, list) or not ids_raw:
        raise HTTPException(422, "ids must be a non-empty list")
    if len(ids_raw) > _BULK_DELETE_MAX:
        raise HTTPException(
            422,
            f"too many ids ({len(ids_raw)}); max {_BULK_DELETE_MAX} per call",
        )
    seen: set[str] = set()
    ids: list[str] = []
    for tok in ids_raw:
        if not isinstance(tok, str) or not tok.strip():
            raise HTTPException(422, "ids must be non-empty strings")
        clean = tok.strip()
        if clean in seen:
            continue
        seen.add(clean)
        ids.append(clean)

    principal, tenant_id = _scope(request)
    repo = SavedViewRepository()

    existing_rows = repo.list(principal=principal, tenant_id=tenant_id)
    owned: set[str] = {
        r.get("id")
        for r in existing_rows
        if isinstance(r, dict) and r.get("id")
    }
    deletable = [i for i in ids if i in owned]
    not_found = [i for i in ids if i not in owned]

    if dry_run:
        return mark_dry_run(
            request,
            would_delete={
                "ids": deletable,
                "count": len(deletable),
                "not_found": not_found,
            },
        )

    deleted: list[str] = []
    for view_id in deletable:
        if repo.delete(view_id, principal=principal, tenant_id=tenant_id):
            deleted.append(view_id)
        else:
            not_found.append(view_id)
    return {
        "deleted": deleted,
        "count": len(deleted),
        "not_found": not_found,
        "requested": len(ids),
    }


@router.post(
    "/import",
    dependencies=[require_role("operator"), require_scope("write:classifications")],
)
def import_views(
    request: Request,
    payload: dict | list = Body(...),
    on_conflict: str = Query(
        "skip",
        description=(
            "How to handle a saved view whose name already exists for this "
            "principal+tenant: 'skip' (default) leaves the existing row "
            "alone, 'rename' imports under an auto-suffixed name like "
            "'Name (imported)', 'error' aborts the whole import with 409 "
            "on the first collision."
        ),
    ),
    dry_run: bool = dry_run_query(),
) -> dict | object:
    """Restore saved views from a prior ``GET /v1/saved-views/export`` dump.

    Accepts either the wrapped export envelope (``{"schema": ..., "items": [...]}``)
    or a bare list of view objects. Only ``name`` and ``filters`` are taken
    from each item; everything else (ids, timestamps, principal) is
    re-issued by the server so the import always belongs to the calling
    principal in the current tenant. Repository-side coercion still runs,
    so unknown filter keys and out-of-range values get cleaned the same
    way as a manual create.

    Use ``?dry_run=true`` to preview which rows would be imported,
    skipped, or renamed without writing anything.
    """
    if on_conflict not in _VALID_CONFLICT_MODES:
        raise HTTPException(
            422,
            f"on_conflict must be one of {_VALID_CONFLICT_MODES}",
        )
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("items")
        if items is None:
            raise HTTPException(422, "payload missing 'items' array")
    else:
        raise HTTPException(422, "payload must be an object or list")
    if not isinstance(items, list):
        raise HTTPException(422, "'items' must be a list")
    if len(items) > _IMPORT_MAX_ITEMS:
        raise HTTPException(
            422,
            f"too many items ({len(items)}); max {_IMPORT_MAX_ITEMS} per import",
        )

    principal, tenant_id = _scope(request)
    repo = SavedViewRepository()

    # Snapshot existing names (case-insensitive) so we can detect
    # collisions without round-tripping the DB per item.
    existing_rows = repo.list(principal=principal, tenant_id=tenant_id)
    taken: set[str] = {
        (r.get("name") or "").strip().lower()
        for r in existing_rows
        if isinstance(r, dict)
    }

    def _suffix(base: str) -> str:
        candidate = f"{base} (imported)"
        if candidate.lower() not in taken:
            return candidate
        n = 2
        while f"{base} (imported {n})".lower() in taken:
            n += 1
        return f"{base} (imported {n})"

    imported: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            errors.append({"index": idx, "error": "item must be an object"})
            continue
        name = raw.get("name")
        filters = raw.get("filters") or {}
        if not isinstance(name, str) or not name.strip():
            errors.append({"index": idx, "error": "name is required"})
            continue
        if not isinstance(filters, dict):
            errors.append({"index": idx, "error": "filters must be an object"})
            continue
        clean_name = name.strip()
        target_name = clean_name
        if clean_name.lower() in taken:
            if on_conflict == "skip":
                skipped.append({"name": clean_name, "reason": "duplicate"})
                continue
            if on_conflict == "error":
                raise HTTPException(
                    409,
                    f"saved view name already exists: {clean_name!r}",
                )
            # rename
            target_name = _suffix(clean_name)
        if dry_run:
            imported.append({"name": target_name, "source_name": clean_name})
            taken.add(target_name.lower())
            continue
        try:
            row = repo.create(
                principal=principal,
                name=target_name,
                filters=filters,
                tenant_id=tenant_id,
            )
        except DuplicateSavedViewName:
            # Race against a concurrent create. Treat as skip rather than
            # blowing up the whole import.
            skipped.append({"name": target_name, "reason": "duplicate"})
            continue
        except ValueError as e:
            # Per-user limit reached or filter coercion rejected the row.
            # Stop here so the caller sees a clear partial-success state
            # instead of silently dropping the tail of their backup.
            errors.append({"index": idx, "name": clean_name, "error": str(e)})
            break
        imported.append(row)
        taken.add(target_name.lower())

    result = {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "count": len(imported),
        "on_conflict": on_conflict,
    }
    if dry_run:
        return mark_dry_run(request, would_import=result)
    return result


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


@router.get(
    "/by-name/{name:path}",
    dependencies=[require_role("viewer"), require_scope("read:classifications")],
)
def get_view_by_name(request: Request, name: str) -> dict:
    """Look up one of the caller's saved views by name.

    Lets the UI and CLI deep-link to a view (``/history?view=Receipts``)
    or reference one from a script without first calling ``GET
    /v1/saved-views`` and scanning for the id. Match is case-insensitive
    and ignores surrounding whitespace, matching how the create endpoint
    stores names. Scope is the same as ``GET /v1/saved-views``: only the
    calling principal's rows in the current tenant are visible.
    """
    needle = (name or "").strip().lower()
    if not needle:
        raise HTTPException(422, "name is required")
    principal, tenant_id = _scope(request)
    items = SavedViewRepository().list(principal=principal, tenant_id=tenant_id)
    for row in items:
        if not isinstance(row, dict):
            continue
        if (row.get("name") or "").strip().lower() == needle:
            return row
    raise HTTPException(404, "saved view not found")


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
