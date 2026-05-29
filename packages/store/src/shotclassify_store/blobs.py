"""Blob storage: local FS now, S3 in prod."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from shotclassify_common import get_settings
from shotclassify_common.utils import ensure_dir


class BlobStore(ABC):
    @abstractmethod
    def put(self, key: str, data: bytes) -> str: ...

    @abstractmethod
    def path(self, key: str) -> str: ...


class LocalBlobStore(BlobStore):
    def __init__(self, root: str | Path) -> None:
        self.root = ensure_dir(root)

    def put(self, key: str, data: bytes) -> str:
        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return str(dest)

    def path(self, key: str) -> str:
        return str(self.root / key)


def get_blob_store() -> BlobStore:
    s = get_settings()
    if s.storage_backend == "local":
        return LocalBlobStore(s.storage_local_dir)
    # S3 stub left for prod; LocalBlobStore is the actual implementation.
    return LocalBlobStore(s.storage_local_dir)
