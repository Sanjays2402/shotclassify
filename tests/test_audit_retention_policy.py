"""Per-tenant audit-log retention policy.

Covers store helpers, RBAC on the routes, validator, and the critical
cross-tenant isolation property: an admin in one workspace cannot
remove audit rows owned by another workspace even by running a manual
purge under their own policy.
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
        json.dumps(
            {
                "acme-admin": "admin",
                "acme-op": "operator",
                "globex-admin": "admin",
            }
        ),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps(
            {
                "acme-admin": "acme",
                "acme-op": "acme",
                "globex-admin": "globex",
            }
        ),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "default")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'auditret.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def _seed_audit(tenant_id: str, principal: str, age_days: int) -> str:
    """Insert an audit row and backdate it by ``age_days`` days."""
    from shotclassify_store import AuditRepository, get_session
    from shotclassify_store.db import AuditLogRow

    audit = AuditRepository()
    entry_id = audit.record(
        principal=principal,
        method="POST",
        path="/v1/test",
        status_code=200,
        tenant_id=tenant_id,
    )
    if age_days > 0:
        backdated = datetime.now(UTC) - timedelta(days=age_days)
        with get_session() as s:
            ar = s.get(AuditLogRow, entry_id)
            ar.created_at = backdated
            s.commit()
    return entry_id


def _count_audit(tenant_id: str) -> int:
    from sqlalchemy import func, select

    from shotclassify_store import get_session
    from shotclassify_store.db import AuditLogRow

    with get_session() as s:
        return int(
            s.execute(
                select(func.count())
                .select_from(AuditLogRow)
                .where(AuditLogRow.tenant_id == tenant_id)
            ).scalar_one()
        )


def test_audit_retention_get_requires_admin(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    forbidden = c.get(
        "/v1/settings/security/audit-retention",
        headers={"X-API-Key": "acme-op"},
    )
    assert forbidden.status_code == 403
    ok = c.get(
        "/v1/settings/security/audit-retention",
        headers={"X-API-Key": "acme-admin"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["tenant_id"] == "acme"
    assert body["enabled"] is False
    assert body["audit_retention_days"] is None
    assert body["max_days"] == 3650


def test_audit_retention_put_validates_input(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    missing_field = c.put(
        "/v1/settings/security/audit-retention",
        headers={"X-API-Key": "acme-admin"},
        json={},
    )
    assert missing_field.status_code == 422
    negative = c.put(
        "/v1/settings/security/audit-retention",
        headers={"X-API-Key": "acme-admin"},
        json={"audit_retention_days": -1},
    )
    assert negative.status_code == 422
    too_big = c.put(
        "/v1/settings/security/audit-retention",
        headers={"X-API-Key": "acme-admin"},
        json={"audit_retention_days": 99999},
    )
    assert too_big.status_code == 422
    ok = c.put(
        "/v1/settings/security/audit-retention",
        headers={"X-API-Key": "acme-admin"},
        json={"audit_retention_days": 90},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["audit_retention_days"] == 90
    assert body["enabled"] is True

    # Disable by sending null.
    cleared = c.put(
        "/v1/settings/security/audit-retention",
        headers={"X-API-Key": "acme-admin"},
        json={"audit_retention_days": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["enabled"] is False
    assert cleared.json()["audit_retention_days"] is None


def test_audit_retention_purge_is_tenant_scoped(monkeypatch, tmp_path):
    """Cross-tenant isolation: acme's purge cannot touch globex's audit rows."""
    c = _client(monkeypatch, tmp_path)

    acme_old = _seed_audit("acme", "acme-admin", age_days=120)
    acme_new = _seed_audit("acme", "acme-admin", age_days=1)
    globex_old = _seed_audit("globex", "globex-admin", age_days=120)

    acme_before = _count_audit("acme")
    globex_before = _count_audit("globex")
    assert acme_before >= 2
    assert globex_before >= 1

    # Acme sets a 90-day policy.
    r = c.put(
        "/v1/settings/security/audit-retention",
        headers={"X-API-Key": "acme-admin"},
        json={"audit_retention_days": 90},
    )
    assert r.status_code == 200

    # Acme admin runs the purge.
    run = c.post(
        "/v1/settings/security/audit-retention/run",
        headers={"X-API-Key": "acme-admin"},
    )
    assert run.status_code == 200
    payload = run.json()
    assert payload["tenant_id"] == "acme"
    # At least the seeded acme_old row was eligible.
    assert payload["removed"] >= 1

    # Old acme row gone, recent acme row preserved.
    from shotclassify_store import get_session
    from shotclassify_store.db import AuditLogRow

    with get_session() as s:
        assert s.get(AuditLogRow, acme_old) is None
        assert s.get(AuditLogRow, acme_new) is not None
        # CRITICAL: the globex row is untouched even though it is older
        # than acme's window. This is the cross-tenant isolation the
        # enterprise procurement review cares about.
        assert s.get(AuditLogRow, globex_old) is not None

    # Globex with no policy: manual run is a no-op.
    run2 = c.post(
        "/v1/settings/security/audit-retention/run",
        headers={"X-API-Key": "globex-admin"},
    )
    assert run2.status_code == 200
    assert run2.json()["removed"] == 0
    with get_session() as s:
        assert s.get(AuditLogRow, globex_old) is not None


def test_audit_retention_respects_legal_hold(monkeypatch, tmp_path):
    """A tenant on a legal hold must not lose audit rows to the purge."""
    c = _client(monkeypatch, tmp_path)
    held_row = _seed_audit("acme", "acme-admin", age_days=400)

    # Configure a tight window then place the workspace on legal hold.
    c.put(
        "/v1/settings/security/audit-retention",
        headers={"X-API-Key": "acme-admin"},
        json={"audit_retention_days": 30},
    )
    from shotclassify_store import legal_holds_store

    legal_holds_store.create_hold(
        tenant_id="acme",
        matter="matter-001",
        reason="Pending litigation: do not purge.",
        created_by="acme-admin",
    )

    run = c.post(
        "/v1/settings/security/audit-retention/run",
        headers={"X-API-Key": "acme-admin"},
    )
    assert run.status_code == 200
    body = run.json()
    assert body["held"] is True
    assert body["removed"] == 0

    from shotclassify_store import get_session
    from shotclassify_store.db import AuditLogRow

    with get_session() as s:
        assert s.get(AuditLogRow, held_row) is not None


def test_audit_retention_put_requires_admin(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.put(
        "/v1/settings/security/audit-retention",
        headers={"X-API-Key": "acme-op"},
        json={"audit_retention_days": 30},
    )
    assert r.status_code == 403
