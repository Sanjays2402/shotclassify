"""Fail-closed production secret and configuration validation.

The :class:`Settings` model accepts permissive defaults so a developer can
``uvicorn`` the API with no environment file. Those same defaults are
dangerous in production: a hardcoded API key, the literal string
``dev-secret-change-me-please-32bytes!!`` signing sessions, a wildcard CORS
origin, or a SQLite file masquerading as a real database.

This module collects every "you must override this before going live" rule in
one place and raises :class:`InsecureConfigurationError` from the application
lifespan when running in ``staging`` or ``production``. The check is a no-op
in ``development`` so local iteration keeps working.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .settings import Settings, get_settings

# Sentinel values shipped in defaults / .env.example. If any of these appear
# in a non-development environment we refuse to start.
_DANGEROUS_SECRET_VALUES: frozenset[str] = frozenset(
    {
        "dev-secret-change-me-please-32bytes!!",
        "dev-api-key-change-me",
        "change-me",
        "changeme",
        "secret",
        "password",
        "",
    }
)

_MIN_SECRET_LENGTH = 32


@dataclass(frozen=True)
class ConfigIssue:
    """A single validation failure with the setting name and why it failed."""

    field: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.field}: {self.message}"


class InsecureConfigurationError(RuntimeError):
    """Raised when production-grade settings are missing or unsafe."""

    def __init__(self, issues: Iterable[ConfigIssue]):
        self.issues: tuple[ConfigIssue, ...] = tuple(issues)
        joined = "\n  - ".join(str(i) for i in self.issues)
        super().__init__(
            "Refusing to start: insecure configuration for app_env="
            f"non-development. Fix the following before deploying:\n  - {joined}"
        )


def _is_dangerous(value: str) -> bool:
    return value.strip().lower() in {v.lower() for v in _DANGEROUS_SECRET_VALUES}


def collect_issues(settings: Settings) -> list[ConfigIssue]:
    """Return the list of configuration problems for the given settings.

    Empty list means the configuration is acceptable for the declared
    ``app_env``. In ``development`` this always returns ``[]``.
    """
    if settings.app_env == "development":
        return []

    issues: list[ConfigIssue] = []

    # Session signing key. Must be overridden and long enough to be useful as
    # an HMAC key (32 bytes is the conventional minimum).
    if _is_dangerous(settings.app_secret_key):
        issues.append(
            ConfigIssue(
                "app_secret_key",
                "default/placeholder value used. Set APP_SECRET_KEY to a"
                f" random string of at least {_MIN_SECRET_LENGTH} bytes.",
            )
        )
    elif len(settings.app_secret_key) < _MIN_SECRET_LENGTH:
        issues.append(
            ConfigIssue(
                "app_secret_key",
                f"too short ({len(settings.app_secret_key)} chars); need at"
                f" least {_MIN_SECRET_LENGTH}.",
            )
        )

    # Auth must be enabled outside dev.
    if not settings.auth_enabled:
        issues.append(
            ConfigIssue(
                "auth_enabled",
                "must be true outside development; disabling auth in"
                " staging/production exposes every route to the internet.",
            )
        )

    # API key default is well known; reject it.
    if _is_dangerous(settings.auth_api_key):
        issues.append(
            ConfigIssue(
                "auth_api_key",
                "default placeholder API key in use. Rotate AUTH_API_KEY"
                " to a unique high-entropy value or remove it and rely on"
                " AUTH_API_KEYS / OAuth.",
            )
        )

    # CORS wildcard is never appropriate for authenticated APIs outside dev.
    origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
    if not origins or "*" in origins:
        issues.append(
            ConfigIssue(
                "cors_allowed_origins",
                "wildcard or empty origin allowlist. Set"
                " CORS_ALLOWED_ORIGINS to an explicit comma-separated list.",
            )
        )

    # SQLite is fine for tests, not for a multi-tenant production service.
    if settings.database_url.startswith("sqlite"):
        issues.append(
            ConfigIssue(
                "database_url",
                "sqlite is not safe for concurrent multi-tenant production"
                " traffic. Point DATABASE_URL at Postgres/MySQL.",
            )
        )

    # Storage: local disk does not survive pod restarts in k8s.
    if settings.storage_backend == "local":
        issues.append(
            ConfigIssue(
                "storage_backend",
                "local disk storage is ephemeral in containerized deploys."
                " Set STORAGE_BACKEND=s3 and configure STORAGE_S3_BUCKET.",
            )
        )
    elif settings.storage_backend == "s3" and not settings.storage_s3_bucket:
        issues.append(
            ConfigIssue(
                "storage_s3_bucket",
                "STORAGE_BACKEND=s3 requires STORAGE_S3_BUCKET to be set.",
            )
        )

    # LLM credentials. The placeholder "copilot" is the dev default.
    if not settings.llm_api_key or settings.llm_api_key.strip().lower() in {
        "copilot",
        "changeme",
        "change-me",
    }:
        issues.append(
            ConfigIssue(
                "llm_api_key",
                "missing or default LLM_API_KEY; classification will fail"
                " against any real provider.",
            )
        )

    return issues


def validate_for_production(settings: Settings | None = None) -> None:
    """Validate runtime configuration and raise if it is unsafe.

    Called from the API and worker lifespans so a misconfigured deploy fails
    fast at boot instead of leaking the dev API key under load.
    """
    s = settings or get_settings()
    issues = collect_issues(s)
    if issues:
        raise InsecureConfigurationError(issues)
