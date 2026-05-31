"""SQLAlchemy models + session factory."""
from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from shotclassify_common import get_settings
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class ClassificationRow(Base):
    __tablename__ = "classifications"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512))
    image_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    primary_category: Mapped[str] = mapped_column(String(64), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    ocr_text: Mapped[str] = mapped_column(Text, default="")
    ocr_lang: Mapped[str] = mapped_column(String(16), default="und")
    extracted: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    route: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    user_corrected_to: Mapped[str | None] = mapped_column(String(64), nullable=True)
    elapsed_ms: Mapped[int] = mapped_column(default=0)
    # GDPR / data lifecycle: principal that created the record. Nullable so
    # existing rows from before the migration remain valid; new rows are
    # tagged from request.state.principal by the classify route.
    principal: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # Multi-tenancy: rows are scoped to a tenant. Resolved from the caller's
    # principal via AUTH_TENANT_MAP (falls back to AUTH_DEFAULT_TENANT).
    # Nullable so rows written before the migration remain readable; the
    # repository normalizes NULL to the default tenant at query time.
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # User-editable label (rename) and free-form tags. Both are optional and
    # surfaced through PATCH /v1/history/{id}. ``tags`` is a JSON list of
    # lowercase strings; the repository normalizes input before write.
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # "Star" flag for the history page. Lets users mark important shots and
    # filter to just their pinned set. Indexed for cheap pinned-only queries.
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)


class ApiKeyRow(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(128))
    token_hash: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # JSON list of scope strings. ``None`` is treated as "no explicit scopes"
    # and is interpreted by the auth layer using the legacy role mapping so
    # rows written before migration 0012 keep working.
    scopes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Principal that minted the key. Recorded so the audit trail can answer
    # "who issued this credential" without joining against the audit log.
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Optional per-key requests/minute override. NULL means inherit the
    # workspace/global default from settings; setting a value lets admins
    # carve out elevated quotas for trusted integrations without lifting
    # the ceiling for everyone else.
    rpm_override: Mapped[int | None] = mapped_column(nullable=True)
    # Optional per-key source-IP allowlist. ``None`` or ``[]`` means the
    # key is accepted from any IP (default); a non-empty list of CIDR
    # ranges restricts the key to callers whose source IP is contained
    # by at least one range. Enforced in the auth middleware so adding
    # a new route cannot accidentally bypass it.
    allowed_cidrs: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)


class AuditLogRow(Base):
    """Persisted audit trail: who did what when, for compliance and forensics."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    principal: Mapped[str] = mapped_column(String(128), index=True)
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(512), index=True)
    status_code: Mapped[int] = mapped_column(default=0)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    elapsed_ms: Mapped[int] = mapped_column(default=0)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Tamper-evident chain: sha256 of (prev_hash || canonical_json(fields)),
    # linked per-tenant. `prev_hash` is the previous row's `entry_hash`, or
    # the literal string "GENESIS" for the first row in a tenant. Verifier
    # in shotclassify_store.audit recomputes and rejects any divergence.
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class SavedViewRow(Base):
    """Named filter combination for the history page, scoped per user.

    Lets a returning user jump straight to "low-confidence yesterday" or
    "errors tagged review" without re-entering the filter set every time.
    """

    __tablename__ = "saved_views"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    principal: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class TenantSettingsRow(Base):
    """Per-tenant security settings (currently the IP allowlist)."""

    __tablename__ = "tenant_settings"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ip_allowlist: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # Data retention policy: classifications older than ``retention_days``
    # are purged by the retention job. NULL or <= 0 means keep forever.
    # Enforced per tenant so different customers can pick their own
    # compliance window without code changes.
    retention_days: Mapped[int | None] = mapped_column(nullable=True)
    # SSO (OIDC) config and enforcement. When ``sso_enforced`` is True the
    # auth middleware rejects any session for this tenant that was not
    # minted via the SSO callback. ``sso_domain`` is the email domain that
    # auto-routes to this tenant during /auth/sso/login (Google Workspace /
    # Okta / Azure AD). ``sso_provider`` is a free-form label for UX only.
    sso_enforced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sso_domain: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    sso_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Domain auto-join: when set, an SSO sign-in whose email domain matches
    # ``sso_domain`` and who is not yet a member of this tenant gets a
    # membership created automatically with this role. NULL disables auto-join
    # so admins keep the legacy invite-only flow. ``viewer`` is the safe
    # default we recommend; ``admin`` is rejected at the API layer to prevent
    # a self-service privilege escalation path through DNS-controlled email.
    sso_auto_join_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Per-tenant OIDC IdP. The deployment-level OIDC client (env
    # ``AUTH_SSO_*``) is shared across tenants; large customers refuse
    # this because their identity team will not hand their Okta /
    # Azure AD credentials to a SaaS vendor. These columns let each
    # tenant register its own OIDC application. When ``oidc_issuer``
    # and ``oidc_client_id`` are populated, ``/auth/sso/login`` routes
    # a sign-in attempt for that tenant's ``sso_domain`` to the
    # tenant's own IdP, exchanging the code with ``oidc_client_secret``
    # against the tenant's own token endpoint. NULL = fall back to the
    # deployment-level OIDC client (existing behaviour).
    #
    # ``oidc_client_secret`` is treated as a secret: never returned by
    # any API; only a SHA-256 fingerprint + last-four are surfaced for
    # operator confirmation. Stored as-is at rest because we do not yet
    # have an in-tree key wrapping primitive; documented in security.md.
    oidc_issuer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    oidc_client_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    oidc_client_secret: Mapped[str | None] = mapped_column(String(512), nullable=True)
    oidc_scopes: Mapped[str | None] = mapped_column(String(256), nullable=True)
    oidc_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # PII redaction: list of modes (email, phone, ssn, credit_card, ip, iban)
    # applied to OCR text and extracted text fields before persistence and
    # before any outbound webhook delivery. Empty/NULL means no redaction
    # (existing behavior). Set via /v1/settings/security/privacy by admins
    # with a fresh MFA step-up; change is recorded in the audit log.
    pii_redact_modes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # Data residency hint: a free-form region label (e.g. "us", "eu",
    # "ap-south-1") that the admin console surfaces to operators and that
    # this tenant's responses echo back in the X-Data-Residency header so
    # buyers can prove which storage region is in effect during a security
    # review. Storage backend selection itself is a deploy-time concern.
    data_residency: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Per-tenant cookie session lifetime, in minutes. NULL falls back to
    # the global default in ``sessions.SESSION_TTL``. Enterprise buyers
    # routinely require a max session age (often 480 minutes for SOC2 or
    # 60 for high-risk admin tenancy); this column lets each workspace
    # pick its own without redeploying. Enforced at session creation in
    # ``issue_session`` and clipped on existing rows when the policy is
    # lowered so a sleeping browser tab cannot outlive the new rule.
    session_ttl_minutes: Mapped[int | None] = mapped_column(nullable=True)
    # Per-tenant session inactivity (idle) timeout, in minutes. NULL means
    # "no idle timeout" -- session lifetime is bounded only by
    # ``session_ttl_minutes`` / the global default. When set, the auth
    # middleware revokes any session whose ``last_seen_at`` is older than
    # this many minutes on the next request, regardless of the absolute
    # TTL. This is what SOC2 CC6.1 and most enterprise security
    # questionnaires call "idle session timeout" and is a hard
    # procurement gate. Bounds enforced in :mod:`tenant_settings`.
    session_idle_minutes: Mapped[int | None] = mapped_column(nullable=True)
    # SCIM 2.0 provisioning token. When ``scim_enabled`` is True an external
    # identity provider (Okta, Azure AD, Google Workspace) can call
    # ``/scim/v2/*`` with ``Authorization: Bearer <token>`` to provision and
    # de-provision users in this tenant. ``scim_token_hash`` is a SHA-256 of
    # the bearer token; the plaintext is shown exactly once at rotation time.
    # Tenant-scoped so a leaked token can never reach another workspace.
    scim_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    scim_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    scim_token_last_four: Mapped[str | None] = mapped_column(String(8), nullable=True)
    scim_token_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scim_default_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Seat limit: maximum number of paid seats this workspace can fill.
    # A "seat" = one active membership row OR one pending (non-expired,
    # non-revoked, non-accepted) invitation. NULL means unlimited (legacy
    # behavior). Enforced inside ``memberships.upsert_member`` and
    # ``memberships.create_invitation`` so every path that adds a seat
    # (manual invite, SSO auto-join, SCIM provisioning) is gated
    # consistently. Lowering the cap below current usage is allowed: it
    # blocks new seats but does not retro-evict existing members. Wired
    # into the admin console and the audit log; lets ops sell tiered
    # plans ("Team: 10", "Business: 50") without a redeploy.
    seat_limit: Mapped[int | None] = mapped_column(nullable=True)
    # Max TTL (in days) the tenant will allow on any newly minted or rotated
    # API key. NULL means no policy (legacy behaviour). When set, the API
    # keys store rejects ``create_key`` calls with a longer ttl_days and
    # clamps the successor's expiry on ``rotate``. Recorded changes go
    # through the audit log via the security_settings route.
    api_key_max_ttl_days: Mapped[int | None] = mapped_column(nullable=True)
    # Per-tenant API key inactivity cap. When set (days), a presented
    # DB-backed API key whose effective last-use (falling back to
    # ``created_at``) is older than this is auto-revoked at the auth
    # layer and the request is rejected with 401 ``api_key_stale_inactive``.
    # NULL = no policy (legacy). Wired into security_settings + admin UI.
    api_key_inactivity_days: Mapped[int | None] = mapped_column(nullable=True)
    # Per-tenant cap on the number of active (non-revoked) DB-backed API
    # keys. When set, ``api_keys_store.create_key`` (and the rotation
    # path, which mints a successor) reject with ``ValueError`` once the
    # tenant already has this many active keys. NULL keeps legacy
    # unbounded behaviour. Recorded by the security_settings route +
    # admin UI under "API key active cap".
    api_key_max_active: Mapped[int | None] = mapped_column(nullable=True)
    # Workspace-wide MFA enrollment policy. When True, every cookie-
    # authenticated request from a member of this tenant must have a
    # confirmed TOTP credential or the auth middleware rejects the call
    # with 403 ``mfa_enrollment_required``. A small allowlist of paths
    # (the MFA enrolment endpoints, the calling-principal endpoint, the
    # active-sessions list, logout, and healthchecks) is exempt so a
    # member without a second factor can still complete enrolment
    # without being locked out of the UI flow that lets them enrol.
    # NULL/False means no policy and existing behaviour (per-action MFA
    # step-up only on admin mutations).
    mfa_required_for_members: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    # Per-tenant browser-origin allowlist for the dashboard. When set, every
    # cookie-authenticated request that arrives with an ``Origin`` header
    # (i.e. a browser cross-origin call to the API) must come from one of
    # the listed origins or it is rejected with HTTP 403
    # ``origin_not_allowed`` before the route handler runs. Server-to-server
    # traffic (no ``Origin`` header, or ``X-API-Key`` callers) is unaffected
    # so SDK / CI integrations keep working. NULL or empty list means no
    # policy and existing behaviour. Complements the IP allowlist (which
    # covers server-side callers) with a browser-side control that
    # procurement teams ask for under SOC 2 CC6.6.
    cors_origins: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


class SessionRow(Base):
    """Server-side record of an issued session cookie.

    Lets the app revoke individual sessions or force-logout every session
    for a principal, which the stateless signed-cookie approach cannot do
    on its own. Every authenticated request validates the cookie's ``sid``
    against this table and bumps ``last_seen_at`` so admins can see live
    activity.
    """

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    principal: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # How the session was authenticated. ``oauth`` (legacy GitHub) or
    # ``sso`` (OIDC). Used by enforce-SSO middleware to reject password /
    # legacy oauth sessions for tenants that have switched to SSO-only.
    auth_method: Mapped[str] = mapped_column(String(16), default="oauth", nullable=False)
    # Step-up MFA timestamp. When set, the session has presented a valid
    # TOTP code within the step-up window. Admin mutations require this to
    # be recent (see ``require_mfa_step_up``). NULL means MFA has not been
    # verified on this session yet.
    mfa_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MfaCredentialRow(Base):
    """TOTP enrollment for a principal.

    One row per principal. ``confirmed_at`` is NULL until the user proves
    they configured their authenticator app by submitting a valid code
    against the pending secret. Only confirmed credentials gate access;
    pending enrollments are ignored by step-up checks so a half-enrolled
    account is not locked out.
    """

    __tablename__ = "mfa_credentials"

    principal: Mapped[str] = mapped_column(String(128), primary_key=True)
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MfaRecoveryCodeRow(Base):
    """Single-use TOTP recovery (backup) code.

    Generated in batches of N (default 10) when the user clicks
    "Regenerate recovery codes" on the MFA page. Plaintext is shown to
    the user exactly once; only the SHA-256 hash of the salted code is
    stored. Consuming a code stamps ``used_at`` so the same value cannot
    be used twice (NIST 800-63B 5.1.2).

    Generating a new batch deletes prior unused rows for the same
    principal so users never have two active sets at once.
    """

    __tablename__ = "mfa_recovery_codes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    principal: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    salt: Mapped[str] = mapped_column(String(64), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MembershipRow(Base):
    """Binds a principal (OAuth/SSO login) to a tenant with a role.

    Membership rows are the authoritative source of role assignment once a
    tenant has any rows for a principal; the legacy ``AUTH_ROLE_MAP`` env
    var only applies as a fallback. A principal may be a member of
    multiple tenants (different roles per tenant) since enterprise users
    typically belong to more than one workspace.
    """

    __tablename__ = "memberships"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    principal: Mapped[str] = mapped_column(String(128), index=True)
    role: Mapped[str] = mapped_column(String(16))
    invited_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class InvitationRow(Base):
    """Pending email invitation to join a tenant with a preset role.

    The plaintext invite token is shown exactly once when the invite is
    created; the row stores only its SHA-256 hash so a leaked DB backup
    cannot be replayed. Accept consumes the row by setting
    ``accepted_at``/``accepted_by`` and a membership row is created in the
    same transaction.
    """

    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    invited_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WebhookSubscriptionRow(Base):
    """Outbound webhook subscription, scoped to a tenant.

    The plaintext signing secret is shown exactly once at create time; this
    row stores only its SHA-256 hash so a DB leak cannot be used to forge
    HMAC signatures. ``events`` is a JSON list of event names the dispatcher
    matches against the event it is about to send (``["*"]`` matches all).
    """

    __tablename__ = "webhook_subscriptions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    secret_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    events: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    success_count: Mapped[int] = mapped_column(default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(default=0, nullable=False)
    # Secret rotation with overlap. When ``secret_hash_next`` is set the
    # dispatcher signs every outbound delivery with BOTH the old key (in
    # ``X-Shotclassify-Signature``) and the new key (in
    # ``X-Shotclassify-Signature-Next``) so receivers can roll over with
    # zero downtime. Finalising the rotation promotes ``next`` to the
    # primary and clears the overlap.
    secret_hash_next: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    secret_rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WebhookDeliveryRow(Base):
    """One attempted POST to a subscription endpoint.

    Every attempt is recorded - successes, transient retries, and permanent
    failures - so the admin UI can show the full delivery history and the
    replay endpoint has something concrete to re-send. Scoped by tenant_id
    so cross-workspace reads are impossible at the query layer.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subscription_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(default=1, nullable=False)
    http_status: Mapped[int | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    payload_preview: Mapped[str] = mapped_column(Text, default="", nullable=False)
    signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )


class LegalHoldRow(Base):
    """Active or lifted legal hold on a workspace.

    While at least one row exists for a tenant with ``lifted_at IS NULL``,
    every hard-delete and retention-purge code path must refuse to remove
    rows for that tenant. Lifting a hold sets ``lifted_at`` / ``lifted_by``
    instead of deleting the row so the e-discovery audit trail survives.
    """

    __tablename__ = "legal_holds"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    matter: Mapped[str] = mapped_column(String(256), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    lifted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lifted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lifted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class SubprocessorAckRow(Base):
    """Per-tenant acknowledgement of the active sub-processor catalog.

    Enterprise procurement requires the buyer to view and accept the list
    of third-party data processors. The catalog itself is vendor-owned
    (seeded from config), but each workspace records which version of
    that catalog it has acknowledged, plus who accepted and from where.
    Bumping the catalog version re-arms the unacknowledged banner on the
    next page load.
    """

    __tablename__ = "subprocessor_acks"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    acknowledged_by: Mapped[str] = mapped_column(String(256), nullable=False)
    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    acknowledged_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)


class LegalAgreementAcceptanceRow(Base):
    """Per-tenant acceptance of a vendor-owned legal agreement version.

    Append-only ledger; the 'current' view is derived by selecting the
    latest row per (tenant_id, agreement_id). Strictly tenant-scoped.
    """

    __tablename__ = "legal_agreement_acceptances"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    agreement_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_by: Mapped[str] = mapped_column(String(256), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    accepted_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class LegalEnforcementRow(Base):
    """Per-tenant toggle: block mutating /v1 routes until acceptances are current."""

    __tablename__ = "legal_enforcement"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enforce: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class IncidentSubscriptionRow(Base):
    """Per-tenant security incident notification subscription.

    Enterprise procurement (DPAs, SOC2) requires the vendor to commit to
    a notification channel for security incidents and breaches. This row
    captures which contact (email or webhook URL) a given workspace wants
    notified, at what minimum severity, and who set it up.

    Rows are strictly tenant-scoped; every query path filters on
    ``tenant_id`` so one workspace can never enumerate or mutate another
    workspace's contacts.
    """

    __tablename__ = "incident_subscriptions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(512), nullable=False)
    severity_min: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    last_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_incident_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class SupportAccessGrantRow(Base):
    """Time-boxed tenant consent for vendor-side admin cross-tenant access.

    By default admins of the vendor deployment cannot cross-scope into a
    customer workspace via ``X-Tenant: <other>`` unless that workspace has
    an active grant on file. The grant carries a reason (ticket id or
    short narrative), a hard expiry, and the actor who created and
    optionally revoked it. Every cross-tenant action taken under a grant
    records the grant id in the audit log ``extra`` field, so the
    workspace can later prove who looked at what under which ticket.

    Grants are owned by the *customer* tenant (``tenant_id`` is the
    workspace whose data is being unlocked). The acting admin login is
    optionally pinned in ``allowed_admin`` so a grant for one support
    engineer cannot be used by another. ``revoked_at`` is a soft
    revocation; rows are never deleted so the audit trail survives.
    """

    __tablename__ = "support_access_grants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_admin: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    use_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )


@lru_cache(maxsize=1)
def get_engine():
    s = get_settings()
    url = s.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, connect_args=connect_args)


@lru_cache(maxsize=1)
def _session_factory():
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


def get_session():
    return _session_factory()()


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    # Lightweight in-place migration for SQLite dev databases that predate the
    # ``label`` / ``tags`` columns. Production Postgres deploys should run
    # ``alembic upgrade head``; this just keeps local dev painless.
    try:
        from sqlalchemy import inspect, text

        insp = inspect(engine)
        if not insp.has_table("classifications"):
            return
        cols = {c["name"] for c in insp.get_columns("classifications")}
        with engine.begin() as conn:
            if "label" not in cols:
                conn.execute(text("ALTER TABLE classifications ADD COLUMN label VARCHAR(256)"))
            if "tags" not in cols:
                conn.execute(text("ALTER TABLE classifications ADD COLUMN tags JSON"))
            if "pinned" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE classifications ADD COLUMN pinned BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
            # Dev SQLite bootstrap for the saved_views table (alembic 0006).
            if not insp.has_table("saved_views"):
                Base.metadata.tables["saved_views"].create(bind=conn)
            if not insp.has_table("tenant_settings"):
                Base.metadata.tables["tenant_settings"].create(bind=conn)
            if not insp.has_table("sessions"):
                Base.metadata.tables["sessions"].create(bind=conn)
            # 0011 SSO columns. Cheap ALTERs so dev SQLite stays current.
            if insp.has_table("tenant_settings"):
                tcols = {c["name"] for c in insp.get_columns("tenant_settings")}
                if "sso_enforced" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN sso_enforced BOOLEAN NOT NULL DEFAULT 0"
                    ))
                if "sso_domain" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN sso_domain VARCHAR(128)"
                    ))
                if "sso_provider" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN sso_provider VARCHAR(64)"
                    ))
                if "sso_auto_join_role" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN sso_auto_join_role VARCHAR(16)"
                    ))
                # 0022 per-tenant OIDC IdP columns.
                if "oidc_issuer" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN oidc_issuer VARCHAR(256)"
                    ))
                if "oidc_client_id" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN oidc_client_id VARCHAR(256)"
                    ))
                if "oidc_client_secret" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN oidc_client_secret VARCHAR(512)"
                    ))
                if "oidc_scopes" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN oidc_scopes VARCHAR(256)"
                    ))
                if "oidc_updated_at" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN oidc_updated_at TIMESTAMP"
                    ))
                if "pii_redact_modes" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN pii_redact_modes JSON"
                    ))
                if "data_residency" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN data_residency VARCHAR(32)"
                    ))
                # 0017 SCIM provisioning columns.
                if "scim_enabled" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN scim_enabled BOOLEAN NOT NULL DEFAULT 0"
                    ))
                if "scim_token_hash" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN scim_token_hash VARCHAR(64)"
                    ))
                if "scim_token_last_four" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN scim_token_last_four VARCHAR(8)"
                    ))
                if "scim_token_rotated_at" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN scim_token_rotated_at TIMESTAMP"
                    ))
                if "scim_default_role" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN scim_default_role VARCHAR(16)"
                    ))
                if "session_ttl_minutes" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN session_ttl_minutes INTEGER"
                    ))
                if "session_idle_minutes" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN session_idle_minutes INTEGER"
                    ))
                if "seat_limit" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN seat_limit INTEGER"
                    ))
                # 0023 per-tenant API key max TTL policy.
                if "api_key_max_ttl_days" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN api_key_max_ttl_days INTEGER"
                    ))
                # 0030 per-tenant API key inactivity (auto-revoke) policy.
                if "api_key_inactivity_days" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN api_key_inactivity_days INTEGER"
                    ))
                # 0031 per-tenant cap on active (non-revoked) API keys.
                if "api_key_max_active" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN api_key_max_active INTEGER"
                    ))
                # 0024 workspace-wide MFA enrolment policy.
                if "mfa_required_for_members" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN mfa_required_for_members BOOLEAN NOT NULL DEFAULT 0"
                    ))
                # 0025 per-tenant browser-origin (CORS) allowlist.
                if "cors_origins" not in tcols:
                    conn.execute(text(
                        "ALTER TABLE tenant_settings ADD COLUMN cors_origins JSON"
                    ))
            if insp.has_table("sessions"):
                scols = {c["name"] for c in insp.get_columns("sessions")}
                if "auth_method" not in scols:
                    conn.execute(text(
                        "ALTER TABLE sessions ADD COLUMN auth_method VARCHAR(16) NOT NULL DEFAULT 'oauth'"
                    ))
                if "mfa_verified_at" not in scols:
                    conn.execute(text(
                        "ALTER TABLE sessions ADD COLUMN mfa_verified_at TIMESTAMP"
                    ))
            if not insp.has_table("mfa_credentials"):
                Base.metadata.tables["mfa_credentials"].create(bind=conn)
            if not insp.has_table("mfa_recovery_codes"):
                Base.metadata.tables["mfa_recovery_codes"].create(bind=conn)
            if not insp.has_table("webhook_subscriptions"):
                Base.metadata.tables["webhook_subscriptions"].create(bind=conn)
            if not insp.has_table("webhook_deliveries"):
                Base.metadata.tables["webhook_deliveries"].create(bind=conn)
            if not insp.has_table("legal_holds"):
                Base.metadata.tables["legal_holds"].create(bind=conn)
            if not insp.has_table("subprocessor_acks"):
                Base.metadata.tables["subprocessor_acks"].create(bind=conn)
            if not insp.has_table("incident_subscriptions"):
                Base.metadata.tables["incident_subscriptions"].create(bind=conn)
            if not insp.has_table("support_access_grants"):
                Base.metadata.tables["support_access_grants"].create(bind=conn)
    except Exception:
        # Best-effort. Real schema management lives in alembic.
        pass
