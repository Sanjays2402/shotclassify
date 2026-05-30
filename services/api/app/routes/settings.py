"""Settings + routing rules read/write."""
from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import APIRouter, Body, HTTPException

from shotclassify_common import get_settings

from ..middleware.rbac import require_role

router = APIRouter(prefix="/v1/settings", tags=["settings"])


@router.get("/rules", dependencies=[require_role("operator")])
def get_rules():
    p = Path(get_settings().route_rules_path)
    if not p.exists():
        return {"path": str(p), "yaml": "", "parsed": None}
    raw = p.read_text()
    try:
        parsed = yaml.safe_load(raw)
    except Exception as e:
        raise HTTPException(500, f"YAML parse error: {e}")
    return {"path": str(p), "yaml": raw, "parsed": parsed}


@router.put("/rules", dependencies=[require_role("admin")])
def put_rules(payload: dict = Body(...)):
    raw = payload.get("yaml", "")
    try:
        yaml.safe_load(raw)
    except Exception as e:
        raise HTTPException(422, f"Invalid YAML: {e}")
    p = Path(get_settings().route_rules_path)
    p.write_text(raw)
    return {"ok": True, "path": str(p)}


@router.get("/env", dependencies=[require_role("operator")])
def safe_env():
    s = get_settings()
    return {
        "app_env": s.app_env,
        "llm_base_url": s.llm_base_url,
        "llm_model": s.llm_model,
        "storage_backend": s.storage_backend,
        "queue": s.queue_name,
        "route_dry_run": s.route_dry_run,
        "auth_enabled": s.auth_enabled,
        "otel_enabled": s.otel_enabled,
    }
