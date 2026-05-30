"""Pydantic-settings based configuration loader."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_env: Literal["development", "staging", "production"] = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 7441
    app_secret_key: str = Field(default="dev-secret-change-me-please-32bytes!!")
    app_log_level: str = "INFO"
    app_log_format: Literal["json", "console"] = "json"

    # Storage
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_dir: str = "./storage"
    storage_s3_bucket: str = ""
    storage_s3_region: str = "us-west-2"

    # Database
    database_url: str = "sqlite:///./shotclassify.db"

    # Queue
    redis_url: str = "redis://localhost:6379/0"
    queue_name: str = "shotclassify"

    # LLM
    llm_base_url: str = "http://127.0.0.1:4141/v1"
    llm_api_key: str = "copilot"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_s: int = 60
    llm_max_retries: int = 2

    # OCR
    ocr_lang: str = "eng"
    ocr_psm: int = 6
    ocr_deskew: bool = True

    # Auth
    auth_enabled: bool = True
    auth_oauth_provider: str = "github"
    auth_oauth_client_id: str = ""
    auth_oauth_client_secret: str = ""
    auth_allowed_github_login: str = ""
    auth_api_key: str = "dev-api-key-change-me"
    # RBAC. Roles: admin, operator, viewer. The default API key (auth_api_key)
    # always maps to ``admin`` for backward compatibility. auth_api_keys lets you
    # provision multiple non-admin keys: JSON object of {key: role}, e.g.
    # '{"viewer-key-abc": "viewer", "ops-key-xyz": "operator"}'.
    # auth_role_map assigns roles to OAuth logins, same JSON-object shape.
    # Unknown principals fall through to auth_default_role.
    auth_api_keys: str = ""
    auth_role_map: str = ""
    auth_default_role: Literal["admin", "operator", "viewer"] = "viewer"

    # Multi-tenancy. Every persisted row is tagged with a tenant_id and queries
    # are scoped to the caller's tenant so no operator/viewer can read or
    # mutate another tenant's data. Admins may opt into a cross-tenant view by
    # passing ``X-Tenant: *`` on the request, or scope to a specific tenant by
    # passing ``X-Tenant: <tenant_id>``. ``auth_tenant_map`` is a JSON object
    # ``{principal: tenant_id}`` covering both API keys and OAuth logins.
    # Anyone not matched falls through to ``auth_default_tenant``.
    auth_tenant_map: str = ""
    auth_default_tenant: str = "default"

    # Routing
    route_rules_path: str = "./packages/route/rules.example.yaml"
    route_dry_run: bool = True
    route_slack_webhook: str = ""

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_per_ip_rpm: int = 120
    rate_limit_per_key_rpm: int = 600
    rate_limit_burst: int = 20
    rate_limit_exempt_paths: str = "/healthz,/readyz,/metrics,/blob"

    # Telemetry
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "shotclassify-api"

    # CI
    enable_ci: bool = False

    # Error tracking (Sentry). Disabled when sentry_dsn is empty.
    sentry_dsn: str = ""
    sentry_release: str = ""
    sentry_sample_rate: float = 1.0
    sentry_traces_sample_rate: float = 0.0
    sentry_profiles_sample_rate: float = 0.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
