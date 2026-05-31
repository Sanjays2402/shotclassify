"""Worker-side retention scheduler tests.

The scheduler is responsible for *actually enforcing* per-tenant
retention windows configured via ``/v1/settings/security/retention``.
Without enforcement the policy is purely declarative and any GDPR
auditor will reject the product. These tests prove:

* a single scheduler pass purges expired rows for every tenant that has
  a policy, and only those tenants;
* tenants without a policy are completely untouched;
* the scheduler is strictly tenant-scoped (no cross-tenant leakage even
  when both tenants run in the same process);
* successful purges write an audit row scoped to the owning tenant with
  the ``scheduler`` trigger so admins see automatic deletions in the
  same audit log as manual ones;
* zero-removal passes are silent in the audit log (no spam).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tests.test_retention_policy import _client, _seed_old


def _set_policy(c, key, days):
    # Step-up MFA is enforced on PUT, but in tests AUTH_API_KEY admin
    # short-circuits MFA. We POST via the settings route.
    r = c.put(
        "/v1/settings/security/retention",
        headers={"X-API-Key": key},
        json={"retention_days": days},
    )
    assert r.status_code in (200, 204), r.text


def test_scheduler_purges_only_tenants_with_policy_and_audits(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)

    # Acme has a 7-day policy; Globex has no policy at all.
    _set_policy(c, "acme-admin", 7)

    expired_acme = _seed_old("acme", "alice@acme", age_days=30, filename="old-acme.png")
    fresh_acme = _seed_old("acme", "alice@acme", age_days=1, filename="new-acme.png")
    untouched_globex = _seed_old(
        "globex", "bob@globex", age_days=365, filename="ancient-globex.png"
    )

    from services.worker.app.retention_scheduler import run_once
    from shotclassify_store import AuditRepository, Repository

    results = run_once(now=datetime.now(UTC))

    # Only acme has a policy, so only acme should appear in results.
    tenants_seen = {r["tenant_id"] for r in results}
    assert tenants_seen == {"acme"}, results
    acme_result = next(r for r in results if r["tenant_id"] == "acme")
    assert acme_result["removed"] == 1
    assert acme_result["retention_days"] == 7

    repo = Repository()
    acme_rows = {r.id for r in repo.list_by_tenant("acme")}
    globex_rows = {r.id for r in repo.list_by_tenant("globex")}

    # Expired acme row is gone, fresh acme row stayed, and globex was
    # never touched even though its only row is a year old.
    assert expired_acme not in acme_rows
    assert fresh_acme in acme_rows
    assert untouched_globex in globex_rows

    # Audit row exists for acme, scoped to acme, with the scheduler trigger.
    acme_audit = AuditRepository().list_for_tenant("acme")
    purge_entries = [
        e for e in acme_audit if e.get("path") == "/internal/retention/purge"
    ]
    assert len(purge_entries) == 1
    entry = purge_entries[0]
    assert entry["tenant_id"] == "acme"
    assert entry["principal"] == "system:retention-scheduler"
    assert entry["extra"]["trigger"] == "scheduler"
    assert entry["extra"]["removed"] == 1

    # And no purge audit row leaked into globex.
    globex_audit = AuditRepository().list_for_tenant("globex")
    assert not [
        e for e in globex_audit if e.get("path") == "/internal/retention/purge"
    ]


def test_scheduler_noop_pass_does_not_spam_audit_log(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _set_policy(c, "acme-admin", 30)
    # Row is well inside the retention window, so the purge removes nothing.
    _seed_old("acme", "alice@acme", age_days=2, filename="recent.png")

    from services.worker.app.retention_scheduler import run_once
    from shotclassify_store import AuditRepository

    results = run_once(now=datetime.now(UTC))
    assert results == [
        r for r in results if r["tenant_id"] == "acme"
    ]
    assert results[0]["removed"] == 0

    audit = AuditRepository().list_for_tenant("acme")
    purge_entries = [
        e for e in audit if e.get("path") == "/internal/retention/purge"
    ]
    assert purge_entries == []
