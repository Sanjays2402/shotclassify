"""RQ jobs."""
from __future__ import annotations

from shotclassify_common.pipeline import process_image


def process_image_job(path: str, note: str | None = None, item_id: str | None = None) -> dict:
    result = process_image(path, note=note, save=True, item_id=item_id)
    return result.model_dump(mode="json")
