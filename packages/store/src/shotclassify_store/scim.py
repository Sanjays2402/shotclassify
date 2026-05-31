"""Per-tenant SCIM 2.0 provisioning configuration.

An external identity provider (Okta, Azure AD, Google Workspace, Rippling)
calls our SCIM endpoints with a bearer token to provision and de-provision
users. The token is generated here, only its SHA-256 hash is persisted, and
the plaintext value is returned exactly once so a leaked database snapshot
cannot replay a token. Lookup goes hash-first so we never need to scan all
tenants to authenticate a request: the index on ``scim_token_hash`` answers
the lookup in O(log n) and the row's ``tenant_id`` is what scopes the rest
of the request.

The plumbing here is intentionally narrow. Token issuance, revoke, and
metadata reads live here; the actual SCIM resource handlers live in
``services/api/app/routes/scim.py`` and the auth middleware uses
:func:`get_tenant_by_scim_token` to resolve a bearer to a tenant.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from .db import TenantSettingsRow, get_session, init_db

SCIM_TOKEN_PREFIX = "scim_"
DEFAULT_SCIM_ROLE = "viewer"
VALID_SCIM_DEFAULT_ROLES = ("viewer", "operator")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    return SCIM_TOKEN_PREFIX + secrets.token_urlsafe(32)


@dataclass(frozen=True)
class ScimConfig:
    tenant_id: str
    enabled: bool
    token_last_four: str | None
    token_rotated_at: datetime | None
    default_role: str

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "enabled": self.enabled,
            "token_last_four": self.token_last_four,
            "token_rotated_at": (
                self.token_rotated_at.isoformat() if self.token_rotated_at else None
            ),
            "default_role": self.default_role,
            "has_token": self.token_last_four is not None,
        }


def _row_to_config(row: TenantSettingsRow | None, tenant_id: str) -> ScimConfig:
    if row is None:
        return ScimConfig(
            tenant_id=tenant_id,
            enabled=False,
            token_last_four=None,
            token_rotated_at=None,
            default_role=DEFAULT_SCIM_ROLE,
        )
    return ScimConfig(
        tenant_id=tenant_id,
        enabled=bool(getattr(row, "scim_enabled", False)),
        token_last_four=getattr(row, "scim_token_last_four", None),
        token_rotated_at=getattr(row, "scim_token_rotated_at", None),
        default_role=getattr(row, "scim_default_role", None) or DEFAULT_SCIM_ROLE,
    )


def get_scim_config(tenant_id: str) -> ScimConfig:
    if not tenant_id:
        return ScimConfig(
            tenant_id="",
            enabled=False,
            token_last_four=None,
            token_rotated_at=None,
            default_role=DEFAULT_SCIM_ROLE,
        )
    init_db()
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        return _row_to_config(row, tenant_id)


def get_tenant_by_scim_token(token: str) -> str | None:
    """Resolve a presented bearer token to a tenant_id.

    Lookup is by SHA-256 hash so the plaintext token never appears in the
    database, in query logs, or in backups. Returns ``None`` when the token
    is unknown or the matching tenant has disabled SCIM, so a previously
    leaked token stops working the moment an admin clicks "Disable".
    """
    if not token:
        return None
    init_db()
    digest = _hash(token)
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.scim_token_hash == digest)
        ).scalar_one_or_none()
        if row is None:
            return None
        if not getattr(row, "scim_enabled", False):
            return None
        return row.tenant_id


def set_scim_enabled(
    tenant_id: str, enabled: bool, *, updated_by: str | None = None
) -> ScimConfig:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    init_db()
    now = datetime.now(UTC)
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                scim_enabled=bool(enabled),
                updated_at=now,
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.scim_enabled = bool(enabled)
            row.updated_at = now
            row.updated_by = updated_by
        s.commit()
        s.refresh(row)
        return _row_to_config(row, tenant_id)


def set_scim_default_role(
    tenant_id: str, role: str, *, updated_by: str | None = None
) -> ScimConfig:
    if role not in VALID_SCIM_DEFAULT_ROLES:
        raise ValueError(
            f"default role must be one of {VALID_SCIM_DEFAULT_ROLES}; "
            "admin is rejected on purpose so an IdP rule cannot mint admins."
        )
    init_db()
    now = datetime.now(UTC)
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                scim_default_role=role,
                updated_at=now,
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.scim_default_role = role
            row.updated_at = now
            row.updated_by = updated_by
        s.commit()
        s.refresh(row)
        return _row_to_config(row, tenant_id)


def rotate_scim_token(
    tenant_id: str, *, updated_by: str | None = None
) -> tuple[ScimConfig, str]:
    """Mint a new SCIM bearer token. The plaintext is returned exactly once.

    Any previously issued token is invalidated atomically in the same
    transaction so there is never a window where two valid tokens exist.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    init_db()
    token = _new_token()
    digest = _hash(token)
    last_four = token[-4:]
    now = datetime.now(UTC)
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            row = TenantSettingsRow(
                tenant_id=tenant_id,
                scim_enabled=True,
                scim_token_hash=digest,
                scim_token_last_four=last_four,
                scim_token_rotated_at=now,
                updated_at=now,
                updated_by=updated_by,
            )
            s.add(row)
        else:
            row.scim_enabled = True
            row.scim_token_hash = digest
            row.scim_token_last_four = last_four
            row.scim_token_rotated_at = now
            row.updated_at = now
            row.updated_by = updated_by
        s.commit()
        s.refresh(row)
        return _row_to_config(row, tenant_id), token


def revoke_scim_token(
    tenant_id: str, *, updated_by: str | None = None
) -> ScimConfig:
    """Wipe the bearer token without disabling the feature flag.

    Useful when an IdP key is compromised and the customer needs to break
    glass immediately but keep the SCIM endpoint enabled so a follow-up
    rotation can happen without flipping the toggle twice.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    init_db()
    now = datetime.now(UTC)
    with get_session() as s:
        row = s.execute(
            select(TenantSettingsRow).where(TenantSettingsRow.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            return _row_to_config(None, tenant_id)
        row.scim_token_hash = None
        row.scim_token_last_four = None
        row.scim_token_rotated_at = None
        row.updated_at = now
        row.updated_by = updated_by
        s.commit()
        s.refresh(row)
        return _row_to_config(row, tenant_id)
