"""SQLAlchemy models + session factory."""
from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from shotclassify_common import get_settings
from sqlalchemy import JSON, DateTime, Float, String, Text, create_engine
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
    Base.metadata.create_all(get_engine())
