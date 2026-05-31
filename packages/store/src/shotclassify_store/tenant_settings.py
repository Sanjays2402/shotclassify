"""Per-tenant security settings (currently the IP allowlist).

The IP allowlist is enforced by ``IPAllowlistMiddleware`` before any route
handler runs. Empty list or missing row means the feature is disabled for
that tenant and traffic flows unchanged, so existing deployments keep
working until an admin opts in.
"""
from __future__ import annotations

import ipaddress
from datetime import UTC, datetime

from sqlalchemy import select

from .db import TenantSettingsRow, get_session, init_db


def _normalize_cidrs(raw: list[str] | None) -> list[str]:
    """Validate and canonicalize a list of CIDR strings.

    Single IPs are accepted and widened to a /32 or /128. Invalid entries
    raise ``ValueError`` so the API layer can return a 422 with a clear
    message instead of silently dropping a malformed rule.
    """
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"ip allowlist entry must be a string: {item!r}")
        s = item.strip()
        if not s:
            continue
        try:
            net = ipaddress.ip_network(s, strict=False)
        except ValueError as exc:
            raise ValueError(f"invalid CIDR or IP: {s!r} ({exc})") from exc
        canonical = str(net)
        if canonical not in seen:
            seen.add(canonical)
            out.append(canonical)
    return out


def get_ip_allowlist(tenant_id: str) -> list[str]:
    """Return the configured CIDR list for ``tenant_id``. Empty when unset."""
    if not tenant_id:
        return []
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None or not row.ip_allowlist:
            return []
        return list(row.ip_allowlist)


def set_ip_allowlist(
    tenant_id: str, cidrs: list[str], updated_by: str | None
) -> list[str]:
    """Persist a normalized CIDR list for ``tenant_id`` and return it."""
    if not tenant_id:
        raise ValueError("tenant_id is required")
    normalized = _normalize_cidrs(cidrs)
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                ip_allowlist=normalized,
                updated_at=datetime.now(UTC),
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.ip_allowlist = normalized
            row.updated_at = datetime.now(UTC)
            row.updated_by = updated_by
        s.commit()
    return normalized


def ip_matches_allowlist(ip: str, cidrs: list[str]) -> bool:
    """Return True if ``ip`` is contained by any CIDR in ``cidrs``.

    Unparseable inputs are treated as a miss so we fail closed.
    """
    if not cidrs:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for c in cidrs:
        try:
            if addr in ipaddress.ip_network(c, strict=False):
                return True
        except ValueError:
            continue
    return False
