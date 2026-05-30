"""Tests for production secrets/config validation.

We construct Settings instances directly (bypassing .env discovery) to keep
these tests hermetic and fast.
"""
from __future__ import annotations

import pytest
from shotclassify_common.secrets_validation import (
    InsecureConfigurationError,
    collect_issues,
    validate_for_production,
)
from shotclassify_common.settings import Settings


def _prod_settings(**overrides) -> Settings:
    """Build a Settings that would pass validation, then apply overrides."""
    base = dict(
        app_env="production",
        app_secret_key="x" * 48,
        auth_enabled=True,
        auth_api_key="rotated-prod-key-with-enough-entropy-1234",
        cors_allowed_origins="https://app.example.com,https://admin.example.com",
        database_url="postgresql://u:p@db.internal:5432/shotclassify",
        storage_backend="s3",
        storage_s3_bucket="shotclassify-prod-blobs",
        llm_api_key="sk-real-llm-token-xyz",
    )
    base.update(overrides)
    return Settings(**base)


def test_development_is_always_accepted():
    # Even with every dangerous default in place, dev should pass cleanly.
    s = Settings(app_env="development")
    assert collect_issues(s) == []
    validate_for_production(s)  # must not raise


def test_clean_production_passes():
    s = _prod_settings()
    assert collect_issues(s) == []
    validate_for_production(s)  # must not raise


def test_default_secret_key_rejected():
    s = _prod_settings(app_secret_key="dev-secret-change-me-please-32bytes!!")
    issues = collect_issues(s)
    fields = {i.field for i in issues}
    assert "app_secret_key" in fields


def test_short_secret_key_rejected():
    s = _prod_settings(app_secret_key="short")
    fields = {i.field for i in collect_issues(s)}
    assert "app_secret_key" in fields


def test_default_api_key_rejected():
    s = _prod_settings(auth_api_key="dev-api-key-change-me")
    fields = {i.field for i in collect_issues(s)}
    assert "auth_api_key" in fields


def test_wildcard_cors_rejected():
    s = _prod_settings(cors_allowed_origins="*")
    fields = {i.field for i in collect_issues(s)}
    assert "cors_allowed_origins" in fields


def test_empty_cors_rejected():
    s = _prod_settings(cors_allowed_origins="")
    fields = {i.field for i in collect_issues(s)}
    assert "cors_allowed_origins" in fields


def test_sqlite_rejected_in_production():
    s = _prod_settings(database_url="sqlite:///./shotclassify.db")
    fields = {i.field for i in collect_issues(s)}
    assert "database_url" in fields


def test_local_storage_rejected_in_production():
    s = _prod_settings(storage_backend="local")
    fields = {i.field for i in collect_issues(s)}
    assert "storage_backend" in fields


def test_s3_without_bucket_rejected():
    s = _prod_settings(storage_backend="s3", storage_s3_bucket="")
    fields = {i.field for i in collect_issues(s)}
    assert "storage_s3_bucket" in fields


def test_auth_disabled_rejected():
    s = _prod_settings(auth_enabled=False)
    fields = {i.field for i in collect_issues(s)}
    assert "auth_enabled" in fields


def test_placeholder_llm_key_rejected():
    s = _prod_settings(llm_api_key="copilot")
    fields = {i.field for i in collect_issues(s)}
    assert "llm_api_key" in fields


def test_validate_raises_with_all_issues_listed():
    s = Settings(app_env="production")  # every default in place
    with pytest.raises(InsecureConfigurationError) as exc:
        validate_for_production(s)
    msg = str(exc.value)
    # Spot-check that we surface the worst offenders rather than dying on
    # the first one. Ops needs the full list to fix the deploy in one pass.
    for field in (
        "app_secret_key",
        "auth_api_key",
        "cors_allowed_origins",
        "database_url",
        "storage_backend",
    ):
        assert field in msg


def test_staging_is_also_validated():
    s = Settings(app_env="staging")
    with pytest.raises(InsecureConfigurationError):
        validate_for_production(s)
