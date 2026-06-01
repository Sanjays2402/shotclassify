"""Workspace teardown tests.

Verifies that ``/v1/workspace/teardown``:

* requires admin role + tenant context
* the schedule endpoint rejects a confirm phrase that is not the
  workspace tenant id
* the execute endpoint refuses to run before the cool-off elapses
  (HTTP 425) and runs after the schedule's ``execute_after`` is in
  the past
* execute hard-deletes only the caller's tenant rows; a sibling
  workspace's data survives (cross-tenant isolation)
* dry_run on schedule + execute does not mutate
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps({"viewer-key": "viewer", "admin-b": "admin"}),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP", json.dumps({"admin-b": "tenant-b"})
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'td.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("AUTH_MFA_REQUIRED", "false")
    monkeypatch.setenv("MFA_REQUIRED_FOR_ADMIN", "false")
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def _seed(principal: str, tenant_id: str) -> str:
    from shotclassify_common import (
        Category,
        Classification,
        Confidence,
        ExtractedFields,
        OCRResult,
        ProcessResult,
        RouteAction,
        RouteDecision,
    )
    from shotclassify_common.utils import new_id
    from shotclassify_store import Repository

    rid = new_id()
    result = ProcessResult(
        id=rid,
        filename="x.png",
        created_at=datetime.now(UTC),
        classification=Classification(
            primary=Category.other,
            confidences=[Confidence(category=Category.other, score=0.9)],
        ),
        ocr=OCRResult(text="hello", language="en"),
        extracted=ExtractedFields(),
        route=RouteDecision(action=RouteAction.none),
        elapsed_ms=1,
        image_url=None,
    )
    Repository().save_result(
        result, image_path=None, principal=principal, tenant_id=tenant_id
    )
    return rid


def _admin_a():
    return {"x-api-key": "admin-key", "x-tenant": "tenant-a"}


def _admin_b():
    return {"x-api-key": "admin-b"}


def test_get_requires_admin(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get(
        "/v1/workspace/teardown",
        headers={"x-api-key": "viewer-key", "x-tenant": "tenant-a"},
    )
    assert r.status_code == 403, r.text


def test_get_returns_empty_default(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/workspace/teardown", headers=_admin_a())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scheduled"] is False
    assert body["status"] == "none"
    assert body["ready_to_execute"] is False


def test_schedule_requires_matching_confirm_phrase(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    bad = c.post(
        "/v1/workspace/teardown",
        headers=_admin_a(),
        json={"confirm": "wrong-tenant", "cooloff_hours": 24},
    )
    assert bad.status_code == 400
    assert "confirmation phrase" in bad.json()["detail"].lower()
    state = c.get("/v1/workspace/teardown", headers=_admin_a()).json()
    assert state["scheduled"] is False


def test_schedule_then_cancel(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/workspace/teardown",
        headers=_admin_a(),
        json={"confirm": "tenant-a", "cooloff_hours": 1, "reason": "decom"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scheduled"] is True
    assert body["reason"] == "decom"
    assert body["status"] == "scheduled"

    cancel = c.request(
        "DELETE", "/v1/workspace/teardown", headers=_admin_a()
    )
    assert cancel.status_code == 200, cancel.text
    after = c.get("/v1/workspace/teardown", headers=_admin_a()).json()
    assert after["scheduled"] is False


def test_execute_rejected_before_cooloff_elapses(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    sched = c.post(
        "/v1/workspace/teardown",
        headers=_admin_a(),
        json={"confirm": "tenant-a", "cooloff_hours": 24},
    )
    assert sched.status_code == 200
    r = c.post(
        "/v1/workspace/teardown/execute?confirm=tenant-a", headers=_admin_a()
    )
    assert r.status_code == 425, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "cooloff_not_elapsed"


def test_execute_no_schedule_returns_409(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/workspace/teardown/execute?confirm=tenant-a", headers=_admin_a()
    )
    assert r.status_code == 409


def test_execute_cross_tenant_isolation_and_full_purge(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed("alice", "tenant-a")
    _seed("alice2", "tenant-a")
    _seed("bob", "tenant-b")

    from shotclassify_store import Repository

    assert len(Repository().list_by_tenant("tenant-a")) == 2
    assert len(Repository().list_by_tenant("tenant-b")) == 1

    sched = c.post(
        "/v1/workspace/teardown",
        headers=_admin_a(),
        json={"confirm": "tenant-a", "cooloff_hours": 1},
    )
    assert sched.status_code == 200, sched.text

    # Back-date so the cool-off has elapsed.
    from shotclassify_store import get_session
    from shotclassify_store.db import TenantSettingsRow
    from sqlalchemy import select

    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(
                TenantSettingsRow.tenant_id == "tenant-a"
            )
        ).scalar_one()
        row.teardown_execute_after = datetime.now(UTC) - timedelta(minutes=1)
        s.commit()

    # Dry-run must not mutate.
    dry = c.post(
        "/v1/workspace/teardown/execute?confirm=tenant-a&dry_run=true",
        headers=_admin_a(),
    )
    assert dry.status_code == 200, dry.text
    assert dry.json().get("dry_run") is True
    assert len(Repository().list_by_tenant("tenant-a")) == 2

    r = c.post(
        "/v1/workspace/teardown/execute?confirm=tenant-a", headers=_admin_a()
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["executed"] is True
    assert body["deleted"]["classifications"] == 2

    # tenant-a wiped, tenant-b untouched.
    assert Repository().list_by_tenant("tenant-a") == []
    assert len(Repository().list_by_tenant("tenant-b")) == 1


def test_execute_confirm_phrase_required(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.post(
        "/v1/workspace/teardown",
        headers=_admin_a(),
        json={"confirm": "tenant-a", "cooloff_hours": 1},
    ).raise_for_status()
    from shotclassify_store import get_session
    from shotclassify_store.db import TenantSettingsRow
    from sqlalchemy import select

    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(
                TenantSettingsRow.tenant_id == "tenant-a"
            )
        ).scalar_one()
        row.teardown_execute_after = datetime.now(UTC) - timedelta(minutes=1)
        s.commit()
    r = c.post(
        "/v1/workspace/teardown/execute?confirm=NOPE", headers=_admin_a()
    )
    assert r.status_code == 400
