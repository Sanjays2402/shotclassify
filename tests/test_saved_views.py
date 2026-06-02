"""Per-user saved views CRUD: /v1/saved-views."""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'sv.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


HEADERS = {"x-api-key": "k"}


def test_saved_views_round_trip(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    # Empty list on first visit.
    r = c.get("/v1/saved-views", headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json() == {"items": [], "count": 0}

    # Create.
    payload = {
        "name": "  Low conf, last week ",
        "filters": {
            "category": "receipt",
            "min_conf": 0.4,
            "since": "2025-01-01",
            "sort": "conf_asc",
            "garbage": "should_drop",
            "limit": 9999,
        },
    }
    r = c.post("/v1/saved-views", json=payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["name"] == "Low conf, last week"
    f = created["filters"]
    assert "garbage" not in f
    assert f["category"] == "receipt"
    assert f["min_conf"] == 0.4
    assert f["sort"] == "conf_asc"
    assert f["limit"] == 500  # clamped to max
    view_id = created["id"]

    # Listed.
    r = c.get("/v1/saved-views", headers=HEADERS)
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == view_id

    # Bad sort dropped, valid name rewritten.
    r = c.patch(
        f"/v1/saved-views/{view_id}",
        json={"name": "Renamed", "filters": {"sort": "nope", "q": "tip"}},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["name"] == "Renamed"
    assert "sort" not in updated["filters"]
    assert updated["filters"]["q"] == "tip"

    # Delete.
    r = c.delete(f"/v1/saved-views/{view_id}", headers=HEADERS)
    assert r.status_code == 200
    r = c.get(f"/v1/saved-views/{view_id}", headers=HEADERS)
    assert r.status_code == 404


def test_saved_view_requires_name(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/saved-views",
        json={"name": "  ", "filters": {}},
        headers=HEADERS,
    )
    assert r.status_code == 422


def test_saved_view_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/saved-views")
    assert r.status_code in (401, 403)


def test_saved_view_persists_extended_filters(monkeypatch, tmp_path):
    """max_conf, pinned, and multi-tag filters round-trip on save.

    These keys were added to the history list/export route but were not in
    the saved-views whitelist, so a view created from a UI that exposed them
    would silently drop those filters on replay.
    """
    c = _client(monkeypatch, tmp_path)
    payload = {
        "name": "Pinned high-conf Q1",
        "filters": {
            "min_conf": 0.6,
            "max_conf": 0.95,
            "pinned": True,
            "tags": ["Finance", "finance", "  Q1 ", "", "x" * 64],
        },
    }
    r = c.post("/v1/saved-views", json=payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    f = r.json()["filters"]
    assert f["min_conf"] == 0.6
    assert f["max_conf"] == 0.95
    assert f["pinned"] is True
    # Dedup on lowercase, trim, drop empties and oversized tags.
    assert f["tags"] == ["finance", "q1"]


def test_saved_view_drops_inverted_conf_range(monkeypatch, tmp_path):
    """An inverted min/max range never reaches the row."""
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/saved-views",
        json={
            "name": "bad range",
            "filters": {"min_conf": 0.9, "max_conf": 0.1, "pinned": False},
        },
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    f = r.json()["filters"]
    assert f["min_conf"] == 0.9
    assert "max_conf" not in f
    # ``pinned=False`` is a real filter, not a synonym for "unset".
    assert f["pinned"] is False


def test_saved_view_rejects_duplicate_name(monkeypatch, tmp_path):
    """Re-saving under the same name returns 409 instead of cloning the row.

    Without this guard, re-clicking "Save view" on the same filters spawns
    identical-looking entries in the sidebar that the user then has to clean
    up by hand. Match is case-insensitive and whitespace-normalised so
    ``"Q1 review"`` and ``"q1   review"`` collide.
    """
    c = _client(monkeypatch, tmp_path)
    base = {"name": "Q1 review", "filters": {"min_conf": 0.7}}
    r = c.post("/v1/saved-views", json=base, headers=HEADERS)
    assert r.status_code == 200, r.text
    first_id = r.json()["id"]

    r = c.post(
        "/v1/saved-views",
        json={"name": "q1   review", "filters": {"min_conf": 0.7}},
        headers=HEADERS,
    )
    assert r.status_code == 409, r.text
    assert "already exists" in r.json()["detail"]

    # Still exactly one row for this principal.
    r = c.get("/v1/saved-views", headers=HEADERS)
    assert r.json()["count"] == 1

    # Renaming a different view onto an existing name also collides.
    r = c.post(
        "/v1/saved-views",
        json={"name": "other", "filters": {}},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    other_id = r.json()["id"]
    r = c.patch(
        f"/v1/saved-views/{other_id}",
        json={"name": "Q1 REVIEW"},
        headers=HEADERS,
    )
    assert r.status_code == 409, r.text

    # Renaming the original to its own name (case/whitespace variant) is a noop, not a conflict.
    r = c.patch(
        f"/v1/saved-views/{first_id}",
        json={"name": "Q1   Review"},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Q1 Review"


def test_saved_view_duplicate_copies_filters_and_auto_names(monkeypatch, tmp_path):
    """POST /v1/saved-views/{id}/duplicate clones the row for the same user.

    Default name is ``"{source} (copy)"`` with auto ``(copy 2)``,
    ``(copy 3)`` suffixes on collision so a user can hit "Duplicate"
    repeatedly without getting a 409 on the very first try.
    """
    c = _client(monkeypatch, tmp_path)
    base = {
        "name": "Pinned receipts",
        "filters": {
            "category": "receipt",
            "min_conf": 0.5,
            "pinned": True,
            "tags": ["finance"],
        },
    }
    r = c.post("/v1/saved-views", json=base, headers=HEADERS)
    assert r.status_code == 200, r.text
    src_id = r.json()["id"]

    # First duplicate: default name + copied filters.
    r = c.post(f"/v1/saved-views/{src_id}/duplicate", headers=HEADERS)
    assert r.status_code == 200, r.text
    dup1 = r.json()
    assert dup1["id"] != src_id
    assert dup1["name"] == "Pinned receipts (copy)"
    assert dup1["filters"] == {
        "category": "receipt",
        "min_conf": 0.5,
        "pinned": True,
        "tags": ["finance"],
    }

    # Second duplicate auto-suffixes.
    r = c.post(f"/v1/saved-views/{src_id}/duplicate", headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Pinned receipts (copy 2)"

    # Explicit name override and filter override.
    r = c.post(
        f"/v1/saved-views/{src_id}/duplicate",
        json={"name": "Receipts, Q2", "filters": {"category": "receipt", "min_conf": 0.8}},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Receipts, Q2"
    assert body["filters"] == {"category": "receipt", "min_conf": 0.8}

    # Explicit name that collides still 409s.
    r = c.post(
        f"/v1/saved-views/{src_id}/duplicate",
        json={"name": "Pinned receipts"},
        headers=HEADERS,
    )
    assert r.status_code == 409, r.text

    # Unknown id is 404.
    r = c.post("/v1/saved-views/does-not-exist/duplicate", headers=HEADERS)
    assert r.status_code == 404

    # Bad payload shape rejected.
    r = c.post(
        f"/v1/saved-views/{src_id}/duplicate",
        json={"filters": "not-an-object"},
        headers=HEADERS,
    )
    assert r.status_code == 422

    # Sidebar now has source + 3 copies = 4 rows.
    r = c.get("/v1/saved-views", headers=HEADERS)
    assert r.json()["count"] == 4


def test_saved_views_export_returns_json_attachment(monkeypatch, tmp_path):
    import json

    c = _client(monkeypatch, tmp_path)

    # Empty export still succeeds and reports a count of zero.
    r = c.get("/v1/saved-views/export", headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    cd = r.headers.get("content-disposition", "")
    assert cd.startswith('attachment; filename="saved-views-')
    assert cd.endswith('.json"')
    body = json.loads(r.content)
    assert body["schema"] == "shotclassify.saved_views.v1"
    assert body["count"] == 0
    assert body["items"] == []
    assert "exported_at" in body

    # Seed two views and re-export.
    c.post(
        "/v1/saved-views",
        json={"name": "Receipts", "filters": {"category": "receipt"}},
        headers=HEADERS,
    )
    c.post(
        "/v1/saved-views",
        json={"name": "High conf", "filters": {"min_conf": 0.9}},
        headers=HEADERS,
    )

    r = c.get("/v1/saved-views/export", headers=HEADERS)
    assert r.status_code == 200
    body = json.loads(r.content)
    assert body["count"] == 2
    names = sorted(v["name"] for v in body["items"])
    assert names == ["High conf", "Receipts"]
    # Each row keeps the same shape the list endpoint returns.
    for row in body["items"]:
        assert set(row).issuperset(
            {"id", "name", "filters", "created_at", "updated_at"}
        )


def test_saved_views_export_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/saved-views/export")
    assert r.status_code in (401, 403)


def test_saved_views_import_round_trip_from_export(monkeypatch, tmp_path):
    """Export from one workspace, import into another, get the same set back."""
    import json

    c = _client(monkeypatch, tmp_path)
    c.post(
        "/v1/saved-views",
        json={"name": "Receipts", "filters": {"category": "receipt"}},
        headers=HEADERS,
    )
    c.post(
        "/v1/saved-views",
        json={"name": "High conf", "filters": {"min_conf": 0.9}},
        headers=HEADERS,
    )
    dump = json.loads(c.get("/v1/saved-views/export", headers=HEADERS).content)

    # Fresh tenant DB so we can re-import without collisions.
    c2 = _client(monkeypatch, tmp_path / "second")
    r = c2.post("/v1/saved-views/import", json=dump, headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 2
    assert body["skipped"] == []
    assert body["errors"] == []
    imported_names = sorted(v["name"] for v in body["imported"])
    assert imported_names == ["High conf", "Receipts"]
    # Ids are re-issued, not copied.
    src_ids = {v["id"] for v in dump["items"]}
    new_ids = {v["id"] for v in body["imported"]}
    assert src_ids.isdisjoint(new_ids)
    # Listing reflects the import.
    listed = c2.get("/v1/saved-views", headers=HEADERS).json()
    assert listed["count"] == 2


def test_saved_views_import_accepts_bare_list(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/saved-views/import",
        json=[
            {"name": "A", "filters": {"category": "receipt"}},
            {"name": "B", "filters": {"min_conf": 0.5}},
        ],
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 2


def test_saved_views_import_conflict_skip(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.post(
        "/v1/saved-views",
        json={"name": "Receipts", "filters": {"category": "receipt"}},
        headers=HEADERS,
    )
    r = c.post(
        "/v1/saved-views/import",
        json={"items": [
            {"name": "receipts", "filters": {"category": "invoice"}},
            {"name": "Fresh", "filters": {"min_conf": 0.4}},
        ]},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["imported"][0]["name"] == "Fresh"
    assert body["skipped"] == [{"name": "receipts", "reason": "duplicate"}]
    # Existing row untouched.
    listed = c.get("/v1/saved-views", headers=HEADERS).json()
    receipts = next(v for v in listed["items"] if v["name"] == "Receipts")
    assert receipts["filters"]["category"] == "receipt"


def test_saved_views_import_conflict_rename(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.post(
        "/v1/saved-views",
        json={"name": "Receipts", "filters": {"category": "receipt"}},
        headers=HEADERS,
    )
    r = c.post(
        "/v1/saved-views/import?on_conflict=rename",
        json=[
            {"name": "Receipts", "filters": {"category": "invoice"}},
            {"name": "Receipts", "filters": {"category": "id_card"}},
        ],
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    names = {v["name"] for v in r.json()["imported"]}
    assert names == {"Receipts (imported)", "Receipts (imported 2)"}


def test_saved_views_import_conflict_error(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.post(
        "/v1/saved-views",
        json={"name": "Receipts", "filters": {"category": "receipt"}},
        headers=HEADERS,
    )
    r = c.post(
        "/v1/saved-views/import?on_conflict=error",
        json=[{"name": "Receipts", "filters": {}}],
        headers=HEADERS,
    )
    assert r.status_code == 409


def test_saved_views_import_dry_run_no_mutation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/saved-views/import?dry_run=true",
        json=[
            {"name": "A", "filters": {"category": "receipt"}},
            {"name": "B", "filters": {"min_conf": 0.5}},
        ],
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("dry_run") is True
    assert r.headers.get("X-Dry-Run") == "true"
    preview = body["would_import"]
    assert preview["count"] == 2
    # No rows actually written.
    listed = c.get("/v1/saved-views", headers=HEADERS).json()
    assert listed["count"] == 0


def test_saved_views_import_rejects_bad_inputs(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    # Bad on_conflict.
    r = c.post(
        "/v1/saved-views/import?on_conflict=overwrite",
        json=[],
        headers=HEADERS,
    )
    assert r.status_code == 422

    # Missing items.
    r = c.post(
        "/v1/saved-views/import",
        json={"schema": "shotclassify.saved_views.v1"},
        headers=HEADERS,
    )
    assert r.status_code == 422

    # Per-item shape errors collected, valid ones still imported.
    r = c.post(
        "/v1/saved-views/import",
        json=[
            {"name": "  ", "filters": {}},
            {"name": "Good", "filters": {"category": "receipt"}},
            "not-an-object",
            {"name": "Bad filters", "filters": "nope"},
        ],
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["imported"][0]["name"] == "Good"
    err_indexes = sorted(e["index"] for e in body["errors"])
    assert err_indexes == [0, 2, 3]


def test_saved_views_import_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post("/v1/saved-views/import", json=[])
    assert r.status_code in (401, 403)
