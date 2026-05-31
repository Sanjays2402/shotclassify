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


# --- SSO configuration ----------------------------------------------------


from dataclasses import dataclass


# Roles allowed for SSO domain auto-join. ``admin`` is intentionally
# excluded: anyone who controls DNS for an allowed domain could otherwise
# self-promote to admin on first sign-in. Admins must still be invited or
# promoted explicitly.
AUTO_JOIN_ROLES: tuple[str, ...] = ("operator", "viewer")


@dataclass(frozen=True)
class SsoConfig:
    tenant_id: str
    enforced: bool
    domain: str | None
    provider: str | None
    auto_join_role: str | None = None

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "enforced": self.enforced,
            "domain": self.domain,
            "provider": self.provider,
            "auto_join_role": self.auto_join_role,
        }


def get_sso_config(tenant_id: str) -> SsoConfig:
    if not tenant_id:
        return SsoConfig(tenant_id="", enforced=False, domain=None, provider=None)
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            return SsoConfig(tenant_id=tenant_id, enforced=False, domain=None, provider=None)
        return SsoConfig(
            tenant_id=tenant_id,
            enforced=bool(getattr(row, "sso_enforced", False)),
            domain=getattr(row, "sso_domain", None),
            provider=getattr(row, "sso_provider", None),
            auto_join_role=getattr(row, "sso_auto_join_role", None),
        )


def set_sso_config(
    tenant_id: str,
    *,
    enforced: bool,
    domain: str | None,
    provider: str | None,
    updated_by: str | None,
    auto_join_role: str | None = None,
) -> SsoConfig:
    """Update the per-tenant SSO settings.

    ``enforced=True`` means the auth middleware refuses any non-SSO session
    for this tenant. ``domain`` (e.g. ``acme.com``) is used by
    ``/auth/sso/login?email=...`` to route a user to the correct tenant
    without exposing tenant ids in URLs.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    norm_domain: str | None = None
    if domain:
        d = domain.strip().lower().lstrip("@")
        if not d or " " in d or "." not in d or len(d) > 128:
            raise ValueError(f"invalid SSO domain: {domain!r}")
        norm_domain = d
    norm_provider: str | None = None
    if provider:
        p = provider.strip()[:64]
        if p:
            norm_provider = p
    norm_auto_join: str | None = None
    if auto_join_role:
        ajr = auto_join_role.strip().lower()
        if ajr:
            if ajr not in AUTO_JOIN_ROLES:
                raise ValueError(
                    f"invalid auto_join_role {auto_join_role!r}: must be one of {AUTO_JOIN_ROLES}"
                )
            if not norm_domain:
                # Auto-join needs a domain to match against; refuse the
                # half-configured state instead of silently doing nothing.
                raise ValueError("auto_join_role requires a domain to be set")
            norm_auto_join = ajr
    init_db()
    with get_session() as s:
        # Domain uniqueness across tenants: refuse to overwrite another
        # tenant's claim on the same domain. Otherwise an admin of tenant B
        # could hijack tenant A's email routing.
        if norm_domain:
            clash = s.execute(
                select(TenantSettingsRow).where(
                    TenantSettingsRow.sso_domain == norm_domain,
                    TenantSettingsRow.tenant_id != tenant_id,
                )
            ).scalar_one_or_none()
            if clash is not None:
                raise ValueError(
                    f"SSO domain {norm_domain!r} is already configured for another tenant"
                )
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                ip_allowlist=[],
                sso_enforced=enforced,
                sso_domain=norm_domain,
                sso_provider=norm_provider,
                sso_auto_join_role=norm_auto_join,
                updated_at=datetime.now(UTC),
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.sso_enforced = enforced
            row.sso_domain = norm_domain
            row.sso_provider = norm_provider
            row.sso_auto_join_role = norm_auto_join
            row.updated_at = datetime.now(UTC)
            row.updated_by = updated_by
        s.commit()
    return SsoConfig(
        tenant_id=tenant_id,
        enforced=enforced,
        domain=norm_domain,
        provider=norm_provider,
        auto_join_role=norm_auto_join,
    )


def tenant_for_sso_domain(domain: str) -> str | None:
    """Return the tenant_id whose SSO config claims ``domain``, if any."""
    if not domain:
        return None
    d = domain.strip().lower().lstrip("@")
    if not d:
        return None
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.sso_domain == d)
        ).scalar_one_or_none()
        return row.tenant_id if row else None


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


# --- Privacy: PII redaction modes and data residency hint -----------------


# Supported redaction modes. Keep this tuple in lockstep with the regex
# table in ``shotclassify_common.redact``: any value persisted that is not
# in this allow-list is silently dropped so a future code rollback cannot
# accidentally re-enable a removed mode.
PII_REDACT_MODES: tuple[str, ...] = (
    "email",
    "phone",
    "ssn",
    "credit_card",
    "ip",
    "iban",
)


@dataclass(frozen=True)
class PrivacySettings:
    tenant_id: str
    redact_modes: list[str]
    data_residency: str | None

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "redact_modes": list(self.redact_modes),
            "data_residency": self.data_residency,
            "available_modes": list(PII_REDACT_MODES),
        }


def _normalize_modes(raw) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("redact_modes must be a list of strings")
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"redact_modes entry must be a string: {item!r}")
        s = item.strip().lower()
        if not s:
            continue
        if s not in PII_REDACT_MODES:
            raise ValueError(
                f"unsupported redact mode {s!r}: must be one of {PII_REDACT_MODES}"
            )
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _normalize_residency(raw) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("data_residency must be a string or null")
    s = raw.strip().lower()
    if not s:
        return None
    if len(s) > 32 or any(c.isspace() for c in s):
        raise ValueError("data_residency must be <=32 chars with no whitespace")
    # Allow letters, digits, dash, underscore. Defensive: anything else
    # could leak into headers and break HTTP parsers downstream.
    for c in s:
        if not (c.isalnum() or c in "-_"):
            raise ValueError(f"invalid character in data_residency: {c!r}")
    return s


def get_privacy_settings(tenant_id: str) -> PrivacySettings:
    """Return the privacy settings for ``tenant_id`` (defaults when unset)."""
    if not tenant_id:
        return PrivacySettings(tenant_id="", redact_modes=[], data_residency=None)
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            return PrivacySettings(tenant_id=tenant_id, redact_modes=[], data_residency=None)
        modes_raw = getattr(row, "pii_redact_modes", None) or []
        # Filter against current allow-list defensively so a stale value
        # from before this revision can never re-enable a removed mode.
        modes = [m for m in modes_raw if m in PII_REDACT_MODES]
        return PrivacySettings(
            tenant_id=tenant_id,
            redact_modes=modes,
            data_residency=getattr(row, "data_residency", None),
        )


def set_privacy_settings(
    tenant_id: str,
    *,
    redact_modes,
    data_residency,
    updated_by: str | None,
) -> PrivacySettings:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    modes = _normalize_modes(redact_modes)
    residency = _normalize_residency(data_residency)
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                ip_allowlist=[],
                pii_redact_modes=modes,
                data_residency=residency,
                updated_at=datetime.now(UTC),
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.pii_redact_modes = modes
            row.data_residency = residency
            row.updated_at = datetime.now(UTC)
            row.updated_by = updated_by
        s.commit()
    return PrivacySettings(
        tenant_id=tenant_id, redact_modes=modes, data_residency=residency
    )
