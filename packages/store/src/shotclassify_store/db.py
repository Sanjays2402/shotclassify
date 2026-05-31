"""SQLAlchemy models + session factory."""
from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from shotclassify_common import get_settings
from sqlalchemy import JSON, Boolean, DateTime, Float, String, Text, create_engine
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


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
    except Exception:
        # Best-effort. Real schema management lives in alembic.
        pass
