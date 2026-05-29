"""SQLAlchemy models + session factory."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from sqlalchemy import JSON, DateTime, Float, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from shotclassify_common import get_settings


class Base(DeclarativeBase):
    pass


class ClassificationRow(Base):
    __tablename__ = "classifications"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512))
    image_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    primary_category: Mapped[str] = mapped_column(String(64), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    ocr_text: Mapped[str] = mapped_column(Text, default="")
    ocr_lang: Mapped[str] = mapped_column(String(16), default="und")
    extracted: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    route: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    user_corrected_to: Mapped[str | None] = mapped_column(String(64), nullable=True)
    elapsed_ms: Mapped[int] = mapped_column(default=0)


class ApiKeyRow(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(128))
    token_hash: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
