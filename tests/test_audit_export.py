"""Audit export endpoint: streaming JSONL/CSV with manifest, tenant scoping."""
from __future__ import annotations

import csv
import io
import json

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "admin-key")
    monkeypatch.setenv(
        "AUTH_API_KEYS",
        json.dumps({
            "acme-admin-key": "admin",
            "globex-admin-key": "admin",
        }),
    )
    monkeypatch.setenv(
        "AUTH_TENANT_MAP",
        json.dumps({
            "acme-admin-key": "acme",
            "globex-admin-key": "globex",
        }),
    )
    monkeypatch.setenv("AUTH_DEFAULT_TENANT", "default")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'audit_export.db'}")
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


def _seed_mutations(client, key):
    # PUT writes one audit row; do it twice with distinct YAML so we have
    # two rows per tenant to export.
    for body in ("rules: []\ndefaults: {dry_run: true}\n", "rules: []\ndefaults: {dry_run: false}\n"):
        r = client.put(
            "/v1/settings/rules",
            json={"yaml": body},
            headers={"X-API-Key": key},
        )
        assert r.status_code == 200, r.text


def _read_stream(response) -> bytes:
    # TestClient consumes streaming responses synchronously into .content.
    return response.content


def test_audit_export_jsonl_includes_manifest_and_is_tenant_scoped(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_mutations(c, "acme-admin-key")
    _seed_mutations(c, "globex-admin-key")

    r = c.post(
        "/v1/audit/export",
        json={"format": "jsonl"},
        headers={"X-API-Key": "acme-admin-key"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/x-ndjson")
    assert "shotclassify-audit-acme-" in r.headers["content-disposition"]
    assert "x-audit-manifest" in r.headers

    lines = [ln for ln in _read_stream(r).decode("utf-8").splitlines() if ln]
    assert lines, "expected at least the manifest line"
    manifest_line = json.loads(lines[-1])
    assert "_manifest" in manifest_line, manifest_line
    manifest = manifest_line["_manifest"]
    assert manifest["tenant_id"] == "acme"
    assert manifest["format"] == "jsonl"
    assert manifest["chain"]["ok"] is True
    assert manifest["rows"] == len(lines) - 1
    assert manifest["rows"] >= 2, manifest

    # Cross-tenant isolation: every data row's tenant_id must be acme (or NULL
    # legacy rows, which the iter intentionally folds in). Globex must NEVER
    # appear in acme's export.
    data_rows = [json.loads(ln) for ln in lines[:-1]]
    tenants = {row.get("tenant_id") for row in data_rows}
    assert "globex" not in tenants, tenants
    assert tenants.issubset({"acme", None}), tenants

    # And every globex-driven mutation must still land in globex's export.
    r2 = c.post(
        "/v1/audit/export",
        json={"format": "jsonl"},
        headers={"X-API-Key": "globex-admin-key"},
    )
    assert r2.status_code == 200, r2.text
    globex_lines = [ln for ln in _read_stream(r2).decode("utf-8").splitlines() if ln]
    globex_rows = [json.loads(ln) for ln in globex_lines[:-1]]
    globex_tenants = {row.get("tenant_id") for row in globex_rows}
    assert "acme" not in globex_tenants, globex_tenants
    assert any(t == "globex" for t in globex_tenants), globex_tenants


def test_audit_export_csv_streams_and_has_manifest_trailer(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_mutations(c, "acme-admin-key")

    r = c.post(
        "/v1/audit/export",
        json={"format": "csv", "path_prefix": "/v1/settings"},
        headers={"X-API-Key": "acme-admin-key"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    body = _read_stream(r).decode("utf-8")
    # Manifest comment trailer
    trailer = body.strip().splitlines()[-1]
    assert trailer.startswith("# "), trailer
    manifest = json.loads(trailer[2:])
    assert manifest["tenant_id"] == "acme"
    assert manifest["format"] == "csv"
    assert manifest["filters"]["path_prefix"] == "/v1/settings"

    # CSV body (sans trailer) parses and contains audited PUTs.
    csv_text = "\n".join(
        ln for ln in body.splitlines() if not ln.startswith("#")
    )
    reader = list(csv.DictReader(io.StringIO(csv_text)))
    assert reader, "expected at least one CSV row"
    assert all(row["path"].startswith("/v1/settings") for row in reader), reader
    # tenant scoping in CSV too
    assert all(row["tenant_id"] in ("acme", "") for row in reader), reader


def test_audit_export_requires_admin(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_API_KEYS", json.dumps({"viewer-key": "viewer"}))
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/audit/export",
        json={"format": "jsonl"},
        headers={"X-API-Key": "viewer-key"},
    )
    assert r.status_code in (401, 403), r.text


def test_audit_export_rejects_inverted_window(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post(
        "/v1/audit/export",
        json={
            "format": "jsonl",
            "since": "2030-01-02T00:00:00Z",
            "until": "2030-01-01T00:00:00Z",
        },
        headers={"X-API-Key": "acme-admin-key"},
    )
    assert r.status_code == 422, r.text
