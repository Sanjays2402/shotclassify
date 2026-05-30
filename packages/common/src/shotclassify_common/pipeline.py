"""Orchestration pipeline: OCR -> classify -> extract -> route -> store."""
from __future__ import annotations

import time
from pathlib import Path

from shotclassify_classify import classify_image
from shotclassify_common import ProcessResult, get_logger
from shotclassify_common.utils import new_id, utcnow
from shotclassify_extract import enrich
from shotclassify_ocr import run_ocr
from shotclassify_route import route_decision
from shotclassify_store import Repository

log = get_logger(__name__)


def process_image(
    image_path: str | Path,
    note: str | None = None,
    save: bool = True,
    item_id: str | None = None,
    principal: str | None = None,
) -> ProcessResult:
    image_path = str(image_path)
    started = time.perf_counter()
    ocr = run_ocr(image_path)
    classification, fields = classify_image(image_path, ocr, note=note)
    enriched = enrich(classification.primary, fields, ocr)
    route = route_decision(classification, enriched, image_path)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    result = ProcessResult(
        id=item_id or new_id(),
        filename=Path(image_path).name,
        created_at=utcnow(),
        classification=classification,
        ocr=ocr,
        extracted=enriched,
        route=route,
        elapsed_ms=elapsed_ms,
        image_url=None,
    )
    if save:
        try:
            Repository().save_result(result, image_path=image_path, principal=principal)
        except Exception as exc:
            log.warning("persist_failed", error=str(exc))
    log.info(
        "processed_image",
        id=result.id,
        primary=classification.primary.value,
        elapsed_ms=elapsed_ms,
    )
    return result
