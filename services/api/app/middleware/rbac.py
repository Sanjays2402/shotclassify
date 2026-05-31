"""Role-based access control.

Three roles, ordered by privilege:

* ``admin``    - full access including settings writes, audit reads, and
                 destructive data-lifecycle operations on any principal
* ``operator`` - read and write classifications, read settings, read own
                 audit/data
* ``viewer``   - read-only access to classifications and history

Role assignment lives in settings:

* ``AUTH_API_KEY`` (the legacy single key) maps to ``admin``
* ``AUTH_API_KEYS`` is a JSON object ``{key: role}`` for provisioning
  additional keys with non-admin roles
* ``AUTH_ROLE_MAP`` is a JSON object ``{login: role}`` for OAuth users
* Anyone not matched falls through to ``AUTH_DEFAULT_ROLE``

The auth middleware sets ``request.state.role`` on every authenticated
request. Route handlers call :func:`require_role` (as a FastAPI dependency)
to enforce a minimum role.
"""
from __future__ import annotations

import json
from typing import Literal

from fastapi import Depends, HTTPException, Request
from shotclassify_common import get_settings

Role = Literal["admin", "operator", "viewer"]

# Higher number wins.
ROLE_RANK: dict[str, int] = {"viewer": 1, "operator": 2, "admin": 3}


def _safe_json_map(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, str) and v in ROLE_RANK:
            out[k] = v
    return out


def role_for_api_key(api_key: str) -> str | None:
    """Resolve the role for a presented API key, or ``None`` if unknown."""
    s = get_settings()
    if not api_key:
        return None
    if s.auth_api_key and api_key == s.auth_api_key:
        return "admin"
    extra = _safe_json_map(s.auth_api_keys)
    return extra.get(api_key)


def role_for_login(login: str) -> str:
    """Resolve the role for an authenticated OAuth login."""
    s = get_settings()
    mapping = _safe_json_map(s.auth_role_map)
    if login in mapping:
        return mapping[login]
    # The single-allowlist login is treated as admin so the existing
    # solo-operator deployment keeps full access after upgrading.
    if s.auth_allowed_github_login and login == s.auth_allowed_github_login:
        return "admin"
    return s.auth_default_role


def require_scope(scope: str):
    """FastAPI dependency factory: 403 unless caller's key includes ``scope``.

    Session callers (humans) and legacy env-var keys do not carry an explicit
    scope list, so we fall back to the coarse role check (``admin`` satisfies
    any scope; ``operator`` satisfies write/read; ``viewer`` satisfies read).
    DB-backed API keys are checked against their literal scope list, with the
    ``admin`` scope acting as a superset shorthand.
    """

    def _checker(request: Request) -> str:
        scopes = getattr(request.state, "auth_scopes", None) or []
        if scopes:
            if "admin" in scopes or scope in scopes:
                return scope
            raise HTTPException(
                status_code=403,
                detail=f"API key is missing required scope '{scope}'.",
            )
        role = getattr(request.state, "role", None) or "anonymous"
        rank = ROLE_RANK.get(role, 0)
        needed = 3 if scope == "admin" else (2 if scope.startswith("write:") else 1)
        if rank < needed:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{role}' lacks required scope '{scope}'.",
            )
        return scope

    return Depends(_checker)


def require_role(minimum: Role):
    """FastAPI dependency factory: 403 unless caller has >= ``minimum`` role."""
    required = ROLE_RANK[minimum]

    def _checker(request: Request) -> str:
        role = getattr(request.state, "role", None)
        if not role or ROLE_RANK.get(role, 0) < required:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Role '{role or 'anonymous'}' lacks required role '{minimum}'."
                ),
            )
        return role

    return Depends(_checker)
