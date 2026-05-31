"""Tamper-evident audit log: hash chain verification."""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'audit-chain.db'}")
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


def _trigger_audited_mutations(c: TestClient, n: int) -> None:
    # Hit a small, authenticated mutating endpoint to generate audit rows.
    # /v1/history/{id} PATCH 404s without a real row, but middleware still
    # records the audited request because auth identified a principal.
    for i in range(n):
        c.patch(
            f"/v1/history/does-not-exist-{i}",
            json={"label": f"x-{i}"},
            headers={"x-api-key": "k"},
        )


def test_audit_chain_verifies_after_recorded_mutations(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _trigger_audited_mutations(c, 3)
    r = c.get("/v1/audit/verify", headers={"x-api-key": "k"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body
    assert body["checked"] >= 3
    assert body["broken_at"] is None
    assert body["tip_hash"] and len(body["tip_hash"]) == 64


def test_audit_chain_detects_row_mutation(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _trigger_audited_mutations(c, 3)

    # Tamper with the audit log directly to simulate an attacker (or a buggy
    # admin) editing history. The verifier MUST flag this even though the
    # row's own entry_hash still exists in the DB.
    from shotclassify_store import get_session
    from shotclassify_store import AuditLogRow

    with get_session() as s:
        row = (
            s.query(AuditLogRow)
            .order_by(AuditLogRow.created_at.asc(), AuditLogRow.id.asc())
            .offset(1)
            .first()
        )
        assert row is not None
        broken_id = row.id
        row.path = "/v1/history/TAMPERED"
        s.commit()

    r = c.get("/v1/audit/verify", headers={"x-api-key": "k"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False, body
    assert body["broken_at"] == broken_id
    assert "mismatch" in (body["reason"] or "")
