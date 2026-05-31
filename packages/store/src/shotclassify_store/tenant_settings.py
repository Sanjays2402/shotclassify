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


# --- Session policy: per-tenant cookie session TTL ------------------------


# Bounds on the configurable per-tenant session TTL. The lower bound keeps
# admins from locking themselves out with a 0-minute policy (any browser
# round trip would already be expired). The upper bound prevents a tenant
# from quietly opting out of session rotation entirely; 365 days is the
# longest a SOC2 auditor will tolerate without a written exception.
SESSION_TTL_MIN_MINUTES = 5
SESSION_TTL_MAX_MINUTES = 60 * 24 * 365

# Bounds on the configurable per-tenant session *idle* timeout. The lower
# bound matches the absolute-TTL floor so an admin cannot lock the entire
# tenant out with a 0-minute setting. The upper bound is 30 days; anything
# longer is meaningless because the absolute TTL caps at 365 days.
SESSION_IDLE_MIN_MINUTES = 5
SESSION_IDLE_MAX_MINUTES = 60 * 24 * 30


@dataclass(frozen=True)
class SessionPolicy:
    tenant_id: str
    session_ttl_minutes: int | None  # None = use global default
    session_idle_minutes: int | None = None  # None = no idle timeout

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "session_ttl_minutes": self.session_ttl_minutes,
            "session_idle_minutes": self.session_idle_minutes,
            "min_minutes": SESSION_TTL_MIN_MINUTES,
            "max_minutes": SESSION_TTL_MAX_MINUTES,
            "idle_min_minutes": SESSION_IDLE_MIN_MINUTES,
            "idle_max_minutes": SESSION_IDLE_MAX_MINUTES,
        }


def get_session_policy(tenant_id: str | None) -> SessionPolicy:
    """Return the session policy for ``tenant_id``.

    Empty/unknown tenant returns the "use global default" sentinel so
    callers can blindly pass it through to ``issue_session`` without
    branching on whether the tenant has ever opened settings.
    """
    if not tenant_id:
        return SessionPolicy(tenant_id="", session_ttl_minutes=None, session_idle_minutes=None)
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            return SessionPolicy(tenant_id=tenant_id, session_ttl_minutes=None, session_idle_minutes=None)
        return SessionPolicy(
            tenant_id=tenant_id,
            session_ttl_minutes=getattr(row, "session_ttl_minutes", None),
            session_idle_minutes=getattr(row, "session_idle_minutes", None),
        )


def set_session_policy(
    tenant_id: str,
    *,
    session_ttl_minutes: int | None,
    updated_by: str | None,
) -> SessionPolicy:
    """Persist a per-tenant cookie session TTL (in minutes) or clear it.

    ``None`` clears the override and the tenant returns to the global
    default. Raises ``ValueError`` for out-of-range or non-integer values
    so the API layer can surface a 422 with a precise message.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    norm: int | None
    if session_ttl_minutes is None:
        norm = None
    else:
        if isinstance(session_ttl_minutes, bool) or not isinstance(
            session_ttl_minutes, int
        ):
            raise ValueError("session_ttl_minutes must be an integer or null")
        if (
            session_ttl_minutes < SESSION_TTL_MIN_MINUTES
            or session_ttl_minutes > SESSION_TTL_MAX_MINUTES
        ):
            raise ValueError(
                f"session_ttl_minutes must be between "
                f"{SESSION_TTL_MIN_MINUTES} and {SESSION_TTL_MAX_MINUTES} minutes"
            )
        norm = session_ttl_minutes
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                ip_allowlist=[],
                session_ttl_minutes=norm,
                updated_at=datetime.now(UTC),
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.session_ttl_minutes = norm
            row.updated_at = datetime.now(UTC)
            row.updated_by = updated_by
        idle = getattr(row, "session_idle_minutes", None)
        s.commit()
    return SessionPolicy(
        tenant_id=tenant_id, session_ttl_minutes=norm, session_idle_minutes=idle
    )


def set_session_idle_policy(
    tenant_id: str,
    *,
    session_idle_minutes: int | None,
    updated_by: str | None,
) -> SessionPolicy:
    """Persist a per-tenant session idle timeout (in minutes) or clear it.

    ``None`` removes the idle requirement entirely; sessions are then
    only bounded by their absolute TTL. Raises ``ValueError`` for
    out-of-range or non-integer values so the API layer can surface a
    structured 422.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    norm: int | None
    if session_idle_minutes is None:
        norm = None
    else:
        if isinstance(session_idle_minutes, bool) or not isinstance(
            session_idle_minutes, int
        ):
            raise ValueError("session_idle_minutes must be an integer or null")
        if (
            session_idle_minutes < SESSION_IDLE_MIN_MINUTES
            or session_idle_minutes > SESSION_IDLE_MAX_MINUTES
        ):
            raise ValueError(
                f"session_idle_minutes must be between "
                f"{SESSION_IDLE_MIN_MINUTES} and {SESSION_IDLE_MAX_MINUTES} minutes"
            )
        norm = session_idle_minutes
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                ip_allowlist=[],
                session_idle_minutes=norm,
                updated_at=datetime.now(UTC),
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.session_idle_minutes = norm
            row.updated_at = datetime.now(UTC)
            row.updated_by = updated_by
        s.commit()
        ttl = getattr(row, "session_ttl_minutes", None)
    return SessionPolicy(
        tenant_id=tenant_id, session_ttl_minutes=ttl, session_idle_minutes=norm
    )


# ---------------------------------------------------------------------------
# Per-tenant OIDC identity provider.
#
# Large customers reject SaaS that requires them to hand their corporate
# Okta / Azure AD / Google Workspace OIDC client credentials to the vendor's
# shared deployment client. These helpers let each tenant register its own
# OIDC application; ``/auth/sso/login`` consults this config (keyed by the
# email domain via ``tenant_for_sso_domain``) before falling back to the
# deployment-level ``AUTH_SSO_*`` env config.
#
# ``client_secret`` is treated as a secret: never echoed back by any API.
# Reads return a SHA-256 fingerprint + last-four for operator confirmation.
# ---------------------------------------------------------------------------

import hashlib as _hashlib

OIDC_DEFAULT_SCOPES = "openid email profile"


@dataclass(frozen=True)
class TenantOidcConfig:
    tenant_id: str
    configured: bool
    issuer: str | None
    client_id: str | None
    scopes: str | None
    client_secret_fingerprint: str | None  # sha256 hex of secret, or None
    client_secret_last_four: str | None
    updated_at: datetime | None

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "configured": self.configured,
            "issuer": self.issuer,
            "client_id": self.client_id,
            "scopes": self.scopes,
            "client_secret_fingerprint": self.client_secret_fingerprint,
            "client_secret_last_four": self.client_secret_last_four,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


def _normalize_issuer(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    if not s.startswith("https://"):
        raise ValueError("oidc_issuer must be an https:// URL")
    if len(s) > 256:
        raise ValueError("oidc_issuer is too long (max 256 chars)")
    return s.rstrip("/")


def _normalize_scopes(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = " ".join(raw.split())
    if not s:
        return None
    if len(s) > 256:
        raise ValueError("oidc_scopes is too long (max 256 chars)")
    parts = s.split(" ")
    if "openid" not in parts:
        raise ValueError("oidc_scopes must include 'openid'")
    return s


def _fingerprint(secret: str | None) -> tuple[str | None, str | None]:
    if not secret:
        return None, None
    digest = _hashlib.sha256(secret.encode("utf-8")).hexdigest()
    last_four = secret[-4:] if len(secret) >= 4 else None
    return digest, last_four


def get_tenant_oidc(tenant_id: str) -> TenantOidcConfig:
    """Return the per-tenant OIDC IdP config; never returns the secret itself."""
    if not tenant_id:
        return TenantOidcConfig(
            tenant_id="", configured=False, issuer=None, client_id=None,
            scopes=None, client_secret_fingerprint=None, client_secret_last_four=None,
            updated_at=None,
        )
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            return TenantOidcConfig(
                tenant_id=tenant_id, configured=False, issuer=None, client_id=None,
                scopes=None, client_secret_fingerprint=None, client_secret_last_four=None,
                updated_at=None,
            )
        secret = getattr(row, "oidc_client_secret", None)
        fp, l4 = _fingerprint(secret)
        issuer = getattr(row, "oidc_issuer", None)
        client_id = getattr(row, "oidc_client_id", None)
        configured = bool(issuer and client_id and secret)
        return TenantOidcConfig(
            tenant_id=tenant_id,
            configured=configured,
            issuer=issuer,
            client_id=client_id,
            scopes=getattr(row, "oidc_scopes", None),
            client_secret_fingerprint=fp,
            client_secret_last_four=l4,
            updated_at=getattr(row, "oidc_updated_at", None),
        )


def get_tenant_oidc_secret(tenant_id: str) -> str | None:
    """Internal: return the raw client_secret. Auth code-exchange only.

    This is the only function that returns the plaintext secret. Callers
    must never log or echo this value. Used by the OIDC callback to POST
    to the IdP's token endpoint.
    """
    if not tenant_id:
        return None
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            return None
        return getattr(row, "oidc_client_secret", None)


def set_tenant_oidc(
    tenant_id: str,
    *,
    issuer: str | None,
    client_id: str | None,
    client_secret: str | None,
    scopes: str | None,
    updated_by: str | None,
) -> TenantOidcConfig:
    """Replace the per-tenant OIDC IdP config.

    Pass all four core fields (issuer, client_id, client_secret, scopes)
    or pass them all as None to clear. A partial config is rejected so a
    tenant can never end up with a half-broken IdP that authenticates
    against the wrong issuer or leaks a stale client_id.

    ``client_secret`` is required when ``issuer`` is set, but if ``issuer``
    is unchanged and the caller passes ``client_secret=None`` we keep the
    existing secret rather than wiping it. This lets the admin UI update
    just the issuer label without re-entering the secret every time.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    norm_issuer = _normalize_issuer(issuer)
    norm_client_id = (client_id or "").strip() or None
    if norm_client_id and len(norm_client_id) > 256:
        raise ValueError("oidc_client_id is too long (max 256 chars)")
    norm_scopes = _normalize_scopes(scopes) if scopes else (OIDC_DEFAULT_SCOPES if norm_issuer else None)

    # All-or-nothing: either fully configure or fully clear.
    clearing = not (norm_issuer or norm_client_id)
    if not clearing:
        if not (norm_issuer and norm_client_id):
            raise ValueError("oidc_issuer and oidc_client_id are both required")

    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        # Decide what to do with the secret. New configs require an explicit
        # secret. Edits of an existing config preserve the stored secret
        # when the caller omits it.
        existing_secret = getattr(row, "oidc_client_secret", None) if row else None
        if clearing:
            new_secret: str | None = None
        else:
            if client_secret:
                cs = client_secret.strip()
                if not cs or len(cs) > 512:
                    raise ValueError("oidc_client_secret must be 1..512 chars")
                new_secret = cs
            else:
                if not existing_secret:
                    raise ValueError("oidc_client_secret is required to configure OIDC")
                new_secret = existing_secret

        now = datetime.now(UTC)
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                ip_allowlist=[],
                oidc_issuer=norm_issuer,
                oidc_client_id=norm_client_id,
                oidc_client_secret=new_secret,
                oidc_scopes=norm_scopes,
                oidc_updated_at=now,
                updated_at=now,
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.oidc_issuer = norm_issuer
            row.oidc_client_id = norm_client_id
            row.oidc_client_secret = new_secret
            row.oidc_scopes = norm_scopes
            row.oidc_updated_at = now
            row.updated_at = now
            row.updated_by = updated_by
        s.commit()

    return get_tenant_oidc(tenant_id)


# ---------------------------------------------------------------------------
# Per-tenant API key max-TTL policy.
#
# Enterprise buyers (and SOC 2 CC6.1) routinely require a documented and
# *enforced* credential rotation window. Setting a per-tenant cap here
# makes ``api_keys.create_key`` reject any ttl_days longer than the cap
# and clamps the successor's expiry on ``api_keys.rotate``. NULL means
# no policy: existing deployments keep working unchanged until an admin
# opts in.

# Smallest cap is 1 day (anything shorter is operationally hostile). The
# upper bound is 10 years so a tenant can still document "we don't rotate
# integration keys" without code changes, while preventing a no-op
# 100-year setting that defeats the audit answer.
API_KEY_MIN_TTL_DAYS = 1
API_KEY_MAX_TTL_DAYS = 3650


@dataclass(frozen=True)
class ApiKeyTtlPolicy:
    tenant_id: str
    max_ttl_days: int | None  # None = no policy (legacy)

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "max_ttl_days": self.max_ttl_days,
            "min_days": API_KEY_MIN_TTL_DAYS,
            "max_days": API_KEY_MAX_TTL_DAYS,
        }


def get_api_key_ttl_policy(tenant_id: str | None) -> ApiKeyTtlPolicy:
    """Return the per-tenant API key TTL cap, or a no-policy sentinel."""
    if not tenant_id:
        return ApiKeyTtlPolicy(tenant_id="", max_ttl_days=None)
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            return ApiKeyTtlPolicy(tenant_id=tenant_id, max_ttl_days=None)
        return ApiKeyTtlPolicy(
            tenant_id=tenant_id,
            max_ttl_days=getattr(row, "api_key_max_ttl_days", None),
        )


def set_api_key_ttl_policy(
    tenant_id: str,
    *,
    max_ttl_days: int | None,
    updated_by: str | None,
) -> ApiKeyTtlPolicy:
    """Persist (or clear) the per-tenant max API key TTL in days.

    ``None`` clears the policy. Raises ``ValueError`` for non-integer or
    out-of-range values so the API layer can return 422.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    norm: int | None
    if max_ttl_days is None:
        norm = None
    else:
        if isinstance(max_ttl_days, bool) or not isinstance(max_ttl_days, int):
            raise ValueError("max_ttl_days must be an integer or null")
        if max_ttl_days < API_KEY_MIN_TTL_DAYS or max_ttl_days > API_KEY_MAX_TTL_DAYS:
            raise ValueError(
                f"max_ttl_days must be between {API_KEY_MIN_TTL_DAYS} "
                f"and {API_KEY_MAX_TTL_DAYS} days"
            )
        norm = max_ttl_days
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                ip_allowlist=[],
                api_key_max_ttl_days=norm,
                updated_at=datetime.now(UTC),
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.api_key_max_ttl_days = norm
            row.updated_at = datetime.now(UTC)
            row.updated_by = updated_by
        s.commit()
    return ApiKeyTtlPolicy(tenant_id=tenant_id, max_ttl_days=norm)


# --- Workspace-wide MFA enrolment policy ---------------------------------


@dataclass(frozen=True)
class MfaPolicy:
    """Per-tenant policy: must every member have a confirmed TOTP credential?

    When ``required`` is True the API auth middleware refuses cookie
    sessions whose principal does not have a confirmed MFA credential,
    except on a small allowlist of paths needed to complete enrolment
    (the ``/v1/mfa/*`` endpoints, ``/v1/me``, ``/v1/sessions``, logout,
    and the unauth healthchecks). API-key callers are exempt because
    machine integrations cover the m2m surface with scoped keys.
    """

    tenant_id: str
    required: bool

    def to_dict(self) -> dict:
        return {"tenant_id": self.tenant_id, "required": self.required}


def get_mfa_policy(tenant_id: str | None) -> MfaPolicy:
    """Return the MFA enrolment policy for ``tenant_id``.

    Missing tenant or missing row return ``required=False`` so existing
    deployments keep working unchanged until an admin opts in.
    """
    if not tenant_id:
        return MfaPolicy(tenant_id="", required=False)
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            return MfaPolicy(tenant_id=tenant_id, required=False)
        return MfaPolicy(
            tenant_id=tenant_id,
            required=bool(getattr(row, "mfa_required_for_members", False)),
        )


def set_mfa_policy(
    tenant_id: str, *, required: bool, updated_by: str | None
) -> MfaPolicy:
    """Persist the per-tenant member MFA enrolment requirement."""
    if not tenant_id:
        raise ValueError("tenant_id is required")
    if not isinstance(required, bool):
        raise ValueError("required must be a boolean")
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                ip_allowlist=[],
                mfa_required_for_members=required,
                updated_at=datetime.now(UTC),
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.mfa_required_for_members = required
            row.updated_at = datetime.now(UTC)
            row.updated_by = updated_by
        s.commit()
    return MfaPolicy(tenant_id=tenant_id, required=required)


# --- Browser-origin (CORS) allowlist --------------------------------------

# Schemes accepted in a per-tenant browser-origin allowlist. ``file://`` and
# arbitrary custom schemes are rejected so we never allow a packaged
# Electron build or local HTML file to call the API of an enforced tenant
# unless an admin explicitly opts in via a future scheme allowlist.
_ORIGIN_SCHEMES: tuple[str, ...] = ("https", "http")


def _normalize_origin(raw: str) -> str:
    """Validate and canonicalize a single browser ``Origin`` value.

    Accepts ``scheme://host[:port]``. Strips trailing slashes, lowercases
    scheme and host, drops the default port for the scheme. Raises
    ``ValueError`` on anything that is not a valid web origin so the API
    layer can 422 with a useful message.
    """
    if not isinstance(raw, str):
        raise ValueError(f"origin must be a string: {raw!r}")
    s = raw.strip()
    if not s:
        raise ValueError("origin must not be empty")
    if "://" not in s:
        raise ValueError(f"origin must be scheme://host[:port], got {raw!r}")
    scheme, rest = s.split("://", 1)
    scheme = scheme.lower()
    if scheme not in _ORIGIN_SCHEMES:
        raise ValueError(
            f"origin scheme must be one of {_ORIGIN_SCHEMES}, got {scheme!r}"
        )
    # Strip path / query / fragment. Browsers never send them in Origin
    # but admins paste full URLs all the time.
    host_port = rest.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if not host_port:
        raise ValueError(f"origin must include a host: {raw!r}")
    if ":" in host_port:
        host, port_str = host_port.rsplit(":", 1)
        if not port_str.isdigit():
            raise ValueError(f"origin port must be numeric: {raw!r}")
        port = int(port_str)
        if not (1 <= port <= 65535):
            raise ValueError(f"origin port out of range: {raw!r}")
        default = 443 if scheme == "https" else 80
        if port == default:
            host_port = host
    host = host_port.split(":", 1)[0].lower()
    if not host:
        raise ValueError(f"origin must include a host: {raw!r}")
    # No wildcards. Tenants who want "*" should not configure a policy at
    # all. We explicitly refuse "*" so an admin cannot accidentally
    # disable the control while believing they enabled it.
    if "*" in host:
        raise ValueError("wildcard hosts are not permitted in the origin allowlist")
    if ":" in host_port:
        return f"{scheme}://{host_port.lower()}"
    return f"{scheme}://{host}"


def _normalize_origins(raw: list[str] | None) -> list[str]:
    if not raw:
        return []
    if len(raw) > 64:
        raise ValueError("at most 64 origins are allowed per tenant")
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        norm = _normalize_origin(item)
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def get_cors_origins(tenant_id: str) -> list[str]:
    """Return the browser-origin allowlist for ``tenant_id``.

    Empty list means no policy: every browser origin is accepted (the
    deployment-level CORS middleware still applies). Server-side callers
    that omit the ``Origin`` header are never affected.
    """
    if not tenant_id:
        return []
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None or not row.cors_origins:
            return []
        return list(row.cors_origins)


def set_cors_origins(
    tenant_id: str, origins: list[str], updated_by: str | None
) -> list[str]:
    """Persist a normalized browser-origin allowlist for ``tenant_id``."""
    if not tenant_id:
        raise ValueError("tenant_id is required")
    normalized = _normalize_origins(origins)
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                ip_allowlist=[],
                cors_origins=normalized,
                updated_at=datetime.now(UTC),
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.cors_origins = normalized
            row.updated_at = datetime.now(UTC)
            row.updated_by = updated_by
        s.commit()
    return normalized


def origin_matches_allowlist(origin: str, allowlist: list[str]) -> bool:
    """Return True when ``origin`` matches any normalized allowlist entry."""
    if not origin or not allowlist:
        return False
    try:
        normalized = _normalize_origin(origin)
    except ValueError:
        return False
    return normalized in set(allowlist)


# --- API key inactivity (auto-revoke) policy ------------------------------

# Smallest meaningful cap is 1 day (anything shorter would auto-revoke
# legitimate weekly cron integrations). Upper bound is 10 years so
# admins can document an intentionally lenient policy without code
# changes.
API_KEY_INACTIVITY_MIN_DAYS = 1
API_KEY_INACTIVITY_MAX_DAYS = 3650


@dataclass(frozen=True)
class ApiKeyInactivityPolicy:
    tenant_id: str
    inactivity_days: int | None  # None = no policy (legacy)

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "inactivity_days": self.inactivity_days,
            "min_days": API_KEY_INACTIVITY_MIN_DAYS,
            "max_days": API_KEY_INACTIVITY_MAX_DAYS,
        }


def get_api_key_inactivity_policy(tenant_id: str | None) -> ApiKeyInactivityPolicy:
    """Return the per-tenant API key inactivity policy.

    Missing tenant or missing settings row return ``inactivity_days=None``
    so existing deployments and unauthenticated paths keep working until
    an admin opts in.
    """
    if not tenant_id:
        return ApiKeyInactivityPolicy(tenant_id="", inactivity_days=None)
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            return ApiKeyInactivityPolicy(tenant_id=tenant_id, inactivity_days=None)
        return ApiKeyInactivityPolicy(
            tenant_id=tenant_id,
            inactivity_days=getattr(row, "api_key_inactivity_days", None),
        )


def set_api_key_inactivity_policy(
    tenant_id: str,
    *,
    inactivity_days: int | None,
    updated_by: str | None,
) -> ApiKeyInactivityPolicy:
    """Persist (or clear) the per-tenant API key inactivity cap in days.

    ``None`` clears the policy and disables auto-revocation. Raises
    :class:`ValueError` for non-integer or out-of-range values so the
    API layer can return 422.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    norm: int | None
    if inactivity_days is None:
        norm = None
    else:
        if isinstance(inactivity_days, bool) or not isinstance(inactivity_days, int):
            raise ValueError("inactivity_days must be an integer or null")
        if (
            inactivity_days < API_KEY_INACTIVITY_MIN_DAYS
            or inactivity_days > API_KEY_INACTIVITY_MAX_DAYS
        ):
            raise ValueError(
                f"inactivity_days must be between {API_KEY_INACTIVITY_MIN_DAYS} "
                f"and {API_KEY_INACTIVITY_MAX_DAYS} days"
            )
        norm = inactivity_days
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                ip_allowlist=[],
                api_key_inactivity_days=norm,
                updated_at=datetime.now(UTC),
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.api_key_inactivity_days = norm
            row.updated_at = datetime.now(UTC)
            row.updated_by = updated_by
        s.commit()
    return ApiKeyInactivityPolicy(tenant_id=tenant_id, inactivity_days=norm)


# ---------------------------------------------------------------------------
# Per-tenant cap on the number of active (non-revoked) API keys
# ---------------------------------------------------------------------------

# Range chosen so the smallest meaningful policy (1 key) and a generous
# upper bound (1000) both fit, while still being something an admin must
# opt into. SOC 2 CC6.1 / NIST AC-2 want a documented cap, not infinity.
API_KEY_MAX_ACTIVE_MIN = 1
API_KEY_MAX_ACTIVE_MAX = 1000


@dataclass(frozen=True)
class ApiKeyMaxActivePolicy:
    tenant_id: str
    max_active: int | None  # None = no policy (legacy unbounded)

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "max_active": self.max_active,
            "min": API_KEY_MAX_ACTIVE_MIN,
            "max": API_KEY_MAX_ACTIVE_MAX,
        }


def get_api_key_max_active_policy(tenant_id: str | None) -> ApiKeyMaxActivePolicy:
    """Return the per-tenant cap on active (non-revoked) API keys.

    Missing tenant or missing settings row return ``max_active=None`` so
    existing deployments and unauthenticated paths keep working until an
    admin opts in.
    """
    if not tenant_id:
        return ApiKeyMaxActivePolicy(tenant_id="", max_active=None)
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            return ApiKeyMaxActivePolicy(tenant_id=tenant_id, max_active=None)
        return ApiKeyMaxActivePolicy(
            tenant_id=tenant_id,
            max_active=getattr(row, "api_key_max_active", None),
        )


def set_api_key_max_active_policy(
    tenant_id: str,
    *,
    max_active: int | None,
    updated_by: str | None,
) -> ApiKeyMaxActivePolicy:
    """Persist (or clear) the per-tenant active-API-key cap.

    ``None`` clears the policy and reverts to unbounded. Raises
    :class:`ValueError` for non-integer or out-of-range values so the
    API layer can return 422. Tightening the policy below the current
    active count does NOT retroactively revoke existing keys: the cap
    only takes effect on the next mint or rotation.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    norm: int | None
    if max_active is None:
        norm = None
    else:
        if isinstance(max_active, bool) or not isinstance(max_active, int):
            raise ValueError("max_active must be an integer or null")
        if max_active < API_KEY_MAX_ACTIVE_MIN or max_active > API_KEY_MAX_ACTIVE_MAX:
            raise ValueError(
                f"max_active must be between {API_KEY_MAX_ACTIVE_MIN} "
                f"and {API_KEY_MAX_ACTIVE_MAX}"
            )
        norm = max_active
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                ip_allowlist=[],
                api_key_max_active=norm,
                updated_at=datetime.now(UTC),
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.api_key_max_active = norm
            row.updated_at = datetime.now(UTC)
            row.updated_by = updated_by
        s.commit()
    return ApiKeyMaxActivePolicy(tenant_id=tenant_id, max_active=norm)


# --- Webhook egress host allowlist ---------------------------------------

# Hostname pattern semantics:
#   "hooks.example.com"   matches exactly that host
#   ".example.com"        matches any subdomain of example.com (and
#                         example.com itself), so suffix rules are
#                         spelled with a leading dot for clarity
# No bare wildcards. No IP ranges (the existing SSRF block already
# refuses private/loopback/metadata addresses; this list is for the
# public-internet destinations the tenant has explicitly approved).
WEBHOOK_EGRESS_HOSTS_MAX = 64
_WEBHOOK_HOST_RE = __import__("re").compile(r"^[a-z0-9]([a-z0-9\-\.]{0,253}[a-z0-9])?$")


def _normalize_webhook_host(raw: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"host must be a string: {raw!r}")
    s = raw.strip().lower()
    if not s:
        raise ValueError("host must not be empty")
    if len(s) > 253:
        raise ValueError("host too long")
    # Strip an accidental scheme so an admin pasting "https://x.com"
    # does not silently configure a non-matching entry.
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    # Strip port: matching is done against the resolved hostname only.
    if ":" in s and not s.startswith("["):
        s = s.rsplit(":", 1)[0]
    if "*" in s:
        raise ValueError("wildcards are not permitted; use a leading dot for suffix matches")
    # Allow leading dot suffix form.
    candidate = s[1:] if s.startswith(".") else s
    if not _WEBHOOK_HOST_RE.match(candidate):
        raise ValueError(f"invalid host: {raw!r}")
    if ".." in s:
        raise ValueError(f"invalid host: {raw!r}")
    return s


def _normalize_webhook_hosts(raw: list[str] | None) -> list[str]:
    if not raw:
        return []
    if len(raw) > WEBHOOK_EGRESS_HOSTS_MAX:
        raise ValueError(
            f"at most {WEBHOOK_EGRESS_HOSTS_MAX} webhook egress hosts are allowed per tenant"
        )
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        norm = _normalize_webhook_host(item)
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def get_webhook_egress_allowed_hosts(tenant_id: str) -> list[str]:
    """Return the per-tenant webhook destination host allowlist.

    Empty list means no policy: only the deployment-level SSRF block
    applies (the dispatcher still refuses private/loopback/metadata
    addresses). When non-empty, every subscription URL host must match.
    """
    if not tenant_id:
        return []
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None or not row.webhook_egress_allowed_hosts:
            return []
        return list(row.webhook_egress_allowed_hosts)


def set_webhook_egress_allowed_hosts(
    tenant_id: str, hosts: list[str], updated_by: str | None
) -> list[str]:
    """Persist a normalized webhook egress host allowlist for ``tenant_id``."""
    if not tenant_id:
        raise ValueError("tenant_id is required")
    normalized = _normalize_webhook_hosts(hosts)
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                ip_allowlist=[],
                webhook_egress_allowed_hosts=normalized,
                updated_at=datetime.now(UTC),
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.webhook_egress_allowed_hosts = normalized
            row.updated_at = datetime.now(UTC)
            row.updated_by = updated_by
        s.commit()
    return normalized


def webhook_host_matches_allowlist(host: str, allowlist: list[str]) -> bool:
    """Return True when ``host`` matches any normalized allowlist entry.

    Exact hostnames match case-insensitively. Leading-dot entries
    (``.example.com``) match the bare apex (``example.com``) and any
    subdomain (``hooks.example.com``, ``api.eu.example.com``). IP
    literals must match exactly; we never treat ``.0.0.1`` style as a
    suffix to keep the IP path explicit.
    """
    if not host or not allowlist:
        return False
    h = host.strip().lower().rstrip(".")
    if not h:
        return False
    for entry in allowlist:
        e = entry.strip().lower()
        if not e:
            continue
        if e.startswith("."):
            apex = e[1:]
            if h == apex or h.endswith(e):
                return True
        else:
            if h == e:
                return True
    return False
