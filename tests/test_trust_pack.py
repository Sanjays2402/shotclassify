"""Trust Pack: signed compliance bundle for procurement reviewers.

Covers:
* Admin can GET the manifest preview and the signed ZIP.
* Non-admin members are denied (RBAC enforcement).
* The HMAC signature in the response header matches the manifest inside
  the ZIP and is reproducible across calls for the same input.
* Cross-tenant isolation: a sibling admin's pack is a different bundle
  with a different signature.
* The ZIP contains the expected files and the manifest's per-file
  SHA-256 entries match the bytes actually written.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile

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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'pack.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("MFA_STEP_UP_ENABLED", "false")
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key-32bytes-padding!!!")
    rules = tmp_path / "rules.yaml"
    rules.write_text("defaults: {dry_run: true}\nrules: []\n")
    monkeypatch.setenv("ROUTE_RULES_PATH", str(rules))

    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def _expected_files() -> set[str]:
    return {
        "README.txt",
        "SECURITY.md",
        "policy.json",
        "subprocessors.json",
        "subprocessor_ack.json",
        "manifest.json",
    }


def test_member_cannot_download_pack(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/trust/pack", headers={"X-API-Key": "acme-op"})
    assert r.status_code == 403, r.text


def test_admin_downloads_signed_pack(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/trust/pack", headers={"X-API-Key": "acme-admin"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    sig = r.headers.get("x-trust-pack-signature")
    assert sig and len(sig) == 64  # sha256 hex
    assert r.headers["x-trust-pack-tenant"] == "acme"
    assert r.headers["x-trust-pack-version"] == "1"
    cd = r.headers["content-disposition"]
    assert "shotclassify-trust-pack-acme.zip" in cd

    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = set(zf.namelist())
        assert names == _expected_files(), names
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["tenant_id"] == "acme"
        assert manifest["signature"] == sig
        assert manifest["signature_alg"] == "HMAC-SHA256"
        # Every listed file's SHA-256 matches the on-disk bytes.
        by_name = {f["name"]: f for f in manifest["files"]}
        for name in _expected_files() - {"manifest.json"}:
            data = zf.read(name)
            assert by_name[name]["sha256"] == hashlib.sha256(data).hexdigest()
            assert by_name[name]["size"] == len(data)


def test_manifest_preview_matches_zip(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    preview = c.get(
        "/v1/trust/pack/manifest", headers={"X-API-Key": "acme-admin"}
    )
    assert preview.status_code == 200, preview.text
    pj = preview.json()
    pack = c.get("/v1/trust/pack", headers={"X-API-Key": "acme-admin"})
    with zipfile.ZipFile(io.BytesIO(pack.content)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    # generated_at and signature may differ across calls only if file bytes
    # differ; in this test environment the policy snapshot is static, so the
    # signature must be identical.
    preview_files = {(f["name"], f["sha256"]) for f in pj["files"]}
    zip_files = {(f["name"], f["sha256"]) for f in manifest["files"]}
    assert preview_files == zip_files
    assert pj["signature"] == manifest["signature"]


def test_cross_tenant_packs_differ(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    acme = c.get("/v1/trust/pack", headers={"X-API-Key": "acme-admin"})
    globex = c.get("/v1/trust/pack", headers={"X-API-Key": "globex-admin"})
    assert acme.status_code == 200
    assert globex.status_code == 200
    assert acme.headers["x-trust-pack-tenant"] == "acme"
    assert globex.headers["x-trust-pack-tenant"] == "globex"
    # Different tenant -> different policy snapshot -> different signature.
    assert (
        acme.headers["x-trust-pack-signature"]
        != globex.headers["x-trust-pack-signature"]
    )
    with zipfile.ZipFile(io.BytesIO(acme.content)) as zf:
        acme_policy = json.loads(zf.read("policy.json"))
    with zipfile.ZipFile(io.BytesIO(globex.content)) as zf:
        globex_policy = json.loads(zf.read("policy.json"))
    assert acme_policy["tenant_id"] == "acme"
    assert globex_policy["tenant_id"] == "globex"


def test_unauthenticated_denied(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/v1/trust/pack")
    assert r.status_code in (401, 403), r.text
    r2 = c.get("/v1/trust/pack/manifest")
    assert r2.status_code in (401, 403), r2.text
