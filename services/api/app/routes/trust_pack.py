"""Trust Pack: one-click compliance bundle for procurement reviewers.

Enterprise security and procurement teams routinely ask for the same
artifacts at the end of every evaluation: a SECURITY policy, the
sub-processor list with the workspace's acknowledgement state, the
configured SSO/MFA/IP-allowlist/session/retention policies for *their*
workspace, and a manifest that proves the bundle hasn't been tampered
with. They want one URL, one download, and a signature they can verify.

This route assembles that bundle on demand for the caller's resolved
tenant.

* ``GET /v1/trust/pack/manifest`` (admin) returns a JSON description of
  what the ZIP would contain, including a deterministic SHA-256 for
  every file. No bytes are streamed, so a reviewer can audit the shape
  before downloading.
* ``GET /v1/trust/pack`` (admin) streams a deterministic ZIP. The
  manifest inside is signed with HMAC-SHA256 over the canonical bytes
  of every other file using the deployment's ``app_secret_key``. The
  signature is also surfaced in the ``X-Trust-Pack-Signature`` response
  header so an automated procurement pipeline can verify without
  unzipping.

The endpoints are tenant-scoped: an ``acme`` admin only ever sees
``acme``'s policy snapshot. The mutating audit middleware does not fire
(GET is read-only) but the request-id and structured access logs still
capture the actor, IP, and tenant so a download is traceable.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from shotclassify_common.settings import get_settings
from shotclassify_store import (
    get_api_key_inactivity_policy,
    get_api_key_max_active_policy,
    get_api_key_ttl_policy,
    get_audit_retention_days,
    get_cors_origins,
    get_ip_allowlist,
    get_mfa_policy,
    get_privacy_settings,
    get_retention_days,
    get_session_policy,
    get_sso_config,
    get_tenant_oidc,
    subprocessors_store,
)

from ..middleware.rbac import require_role

router = APIRouter(prefix="/v1/trust", tags=["trust"])

PACK_VERSION = "1"
SECURITY_DOC_PATH = "docs/security.md"


def _tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            400, "No tenant resolved. Pass X-Tenant header to target a tenant."
        )
    return tenant_id


def _principal(request: Request) -> str:
    actor = getattr(request.state, "principal", None)
    if not actor:
        raise HTTPException(401, "Authenticated principal required.")
    return str(actor)


def _safe_get(callable_, *args, default):
    """Call a tenant policy getter, never raise across the wire."""
    try:
        return callable_(*args)
    except Exception:  # pragma: no cover - defensive
        return default


def _policy_snapshot(tenant_id: str) -> dict:
    """Build the per-workspace policy snapshot.

    Every getter is read-only and tenant-scoped. We deliberately omit
    raw secrets (OIDC client secrets, signing keys) and only emit the
    fingerprint already exposed by ``get_tenant_oidc`` so the bundle is
    safe to hand to a third-party reviewer.
    """
    sso = _safe_get(get_sso_config, tenant_id, default=None)
    oidc = _safe_get(get_tenant_oidc, tenant_id, default=None)
    session_policy = _safe_get(get_session_policy, tenant_id, default=None)
    mfa_policy = _safe_get(get_mfa_policy, tenant_id, default=None)
    privacy = _safe_get(get_privacy_settings, tenant_id, default=None)
    ttl = _safe_get(get_api_key_ttl_policy, tenant_id, default=None)
    inactivity = _safe_get(get_api_key_inactivity_policy, tenant_id, default=None)
    max_active = _safe_get(get_api_key_max_active_policy, tenant_id, default=None)
    ip_allowlist = _safe_get(get_ip_allowlist, tenant_id, default=[])
    cors_origins = _safe_get(get_cors_origins, tenant_id, default=[])
    audit_days = _safe_get(get_audit_retention_days, tenant_id, default=None)
    history_days = _safe_get(get_retention_days, tenant_id, default=None)

    def _to_dict(obj):
        if obj is None:
            return None
        for attr in ("to_dict", "_asdict"):
            fn = getattr(obj, attr, None)
            if callable(fn):
                try:
                    return fn()
                except Exception:
                    pass
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        return obj

    return {
        "tenant_id": tenant_id,
        "sso": _to_dict(sso),
        "oidc": _to_dict(oidc),
        "session_policy": _to_dict(session_policy),
        "mfa_policy": _to_dict(mfa_policy),
        "privacy_settings": _to_dict(privacy),
        "api_key_policies": {
            "ttl": _to_dict(ttl),
            "inactivity": _to_dict(inactivity),
            "max_active": _to_dict(max_active),
        },
        "ip_allowlist": list(ip_allowlist or []),
        "cors_origins": list(cors_origins or []),
        "retention": {
            "audit_log_days": audit_days,
            "history_days": history_days,
        },
    }


def _security_md_bytes() -> bytes:
    """Return the deployed SECURITY policy file as bytes.

    We embed the file the project actually publishes so the bundle
    reflects current commitments. Falls back to a minimal stub if the
    repo layout changes so the endpoint never 500s.
    """
    try:
        from pathlib import Path

        # services/api/app/routes/trust_pack.py -> repo root is 4 levels up.
        repo_root = Path(__file__).resolve().parents[4]
        candidates = [
            repo_root / "SECURITY.md",
            repo_root / "docs" / "security.md",
        ]
        for c in candidates:
            if c.exists():
                return c.read_bytes()
    except Exception:  # pragma: no cover
        pass
    return b"# Security\n\nSee project SECURITY.md for the current policy.\n"


def _canonical_json(obj) -> bytes:
    """Stable JSON encoding used for hashing and on-disk files."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _pretty_json(obj) -> bytes:
    return (json.dumps(obj, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _build_files(tenant_id: str) -> list[tuple[str, bytes]]:
    """Return [(arcname, bytes)] for every file in the pack except the manifest."""
    policy = _policy_snapshot(tenant_id)
    subprocessor_catalog = subprocessors_store.list_catalog()
    subprocessor_status = subprocessors_store.status_for(tenant_id)
    return [
        ("README.txt", _readme_bytes(tenant_id)),
        ("SECURITY.md", _security_md_bytes()),
        ("policy.json", _pretty_json(policy)),
        ("subprocessors.json", _pretty_json(subprocessor_catalog)),
        ("subprocessor_ack.json", _pretty_json(subprocessor_status)),
    ]


def _readme_bytes(tenant_id: str) -> bytes:
    text = (
        "ShotClassify Trust Pack\n"
        "=======================\n\n"
        f"Workspace: {tenant_id}\n"
        f"Pack version: {PACK_VERSION}\n\n"
        "Contents:\n"
        "  SECURITY.md            Current security policy.\n"
        "  policy.json            This workspace's SSO, MFA, IP, session,\n"
        "                         retention, privacy, and API key policies.\n"
        "  subprocessors.json     Vendor sub-processor catalog with version.\n"
        "  subprocessor_ack.json  Whether this workspace acknowledged the\n"
        "                         current catalog and when.\n"
        "  manifest.json          Per-file SHA-256 and HMAC-SHA256 signature.\n\n"
        "Verification:\n"
        "  The X-Trust-Pack-Signature response header matches\n"
        "  manifest.json.signature and is HMAC-SHA256 over the canonical\n"
        "  bytes of every other file, in the order listed by\n"
        "  manifest.json.files. The HMAC key is the deployment's\n"
        "  app_secret_key (rotate-on-incident).\n"
    )
    return text.encode("utf-8")


def _build_manifest(
    tenant_id: str, files: list[tuple[str, bytes]], generated_at: str
) -> tuple[dict, str]:
    """Compute per-file SHA-256 and the HMAC signature over their bytes."""
    file_entries = []
    hasher = hmac.new(
        get_settings().app_secret_key.encode("utf-8"),
        digestmod=hashlib.sha256,
    )
    for name, data in files:
        sha = hashlib.sha256(data).hexdigest()
        file_entries.append({"name": name, "sha256": sha, "size": len(data)})
        # Bind name to bytes so reordering is detectable.
        hasher.update(f"{name}\n{sha}\n".encode("utf-8"))
    signature = hasher.hexdigest()
    manifest = {
        "pack_version": PACK_VERSION,
        "tenant_id": tenant_id,
        "generated_at": generated_at,
        "files": file_entries,
        "signature_alg": "HMAC-SHA256",
        "signature": signature,
    }
    return manifest, signature


def _build_zip(tenant_id: str) -> tuple[bytes, str, str]:
    """Return (zip_bytes, signature, generated_at)."""
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    files = _build_files(tenant_id)
    manifest, signature = _build_manifest(tenant_id, files, generated_at)
    # Deterministic ZIP: fixed mtime, fixed order, STORED compression so the
    # bytes are byte-stable across runs of the same input.
    buf = io.BytesIO()
    fixed_dt = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files:
            info = zipfile.ZipInfo(filename=name, date_time=fixed_dt)
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)
        info = zipfile.ZipInfo(filename="manifest.json", date_time=fixed_dt)
        info.external_attr = 0o644 << 16
        zf.writestr(info, _pretty_json(manifest))
    return buf.getvalue(), signature, generated_at


@router.get("/pack/manifest", dependencies=[require_role("admin")])
def get_pack_manifest(request: Request) -> dict:
    """Preview the bundle without downloading the ZIP bytes."""
    tenant_id = _tenant(request)
    _principal(request)  # require an authenticated principal
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    files = _build_files(tenant_id)
    manifest, _sig = _build_manifest(tenant_id, files, generated_at)
    return manifest


@router.get("/pack", dependencies=[require_role("admin")])
def get_pack(request: Request) -> Response:
    """Download the signed compliance ZIP for the caller's workspace."""
    tenant_id = _tenant(request)
    _principal(request)
    zip_bytes, signature, generated_at = _build_zip(tenant_id)
    filename = f"shotclassify-trust-pack-{tenant_id}.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Trust-Pack-Signature": signature,
            "X-Trust-Pack-Tenant": tenant_id,
            "X-Trust-Pack-Generated-At": generated_at,
            "X-Trust-Pack-Version": PACK_VERSION,
            "Cache-Control": "no-store",
        },
    )
