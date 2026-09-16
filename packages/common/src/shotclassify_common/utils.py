"""Small helpers used across packages."""
from __future__ import annotations

from .schemas import suggest_category  # noqa: F401

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path


def new_id(prefix: str = "shot") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_dir(p: str | Path) -> Path:
    path = Path(p)
    path.mkdir(parents=True, exist_ok=True)
    return path
