"""Orchestration pipeline: OCR -> classify -> extract -> route -> store."""
from __future__ import annotations

import time
from pathlib import Path

from shotclassify_classify import classify_image
from shotclassify_common import ProcessResult, get_logger
from shotclassify_common.redact import redact_fields, redact_text
from shotclassify_common.utils import new_id, utcnow
from shotclassify_extract import enrich
from shotclassify_ocr import run_ocr
from shotclassify_route import route_decision
from shotclassify_store import Repository

log = get_logger(__name__)


def _tenant_redact_modes(tenant_id: str | None) -> list[str]:
    """Return the active PII redaction modes for ``tenant_id``.

    Returns an empty list (no redaction) when the tenant is unknown or
    when looking up settings fails for any reason, so a degraded store
    never blocks classification.
    """
    if not tenant_id:
        return []
    try:
        from shotclassify_store import get_privacy_settings

        return list(get_privacy_settings(tenant_id).redact_modes)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("privacy_lookup_failed", tenant_id=tenant_id, error=str(exc))
        return []


def process_image(
    image_path: str | Path,
    note: str | None = None,
    save: bool = True,
    item_id: str | None = None,
    principal: str | None = None,
    tenant_id: str | None = None,
) -> ProcessResult:
    image_path = str(image_path)
    started = time.perf_counter()
    ocr = run_ocr(image_path)
    classification, fields = classify_image(image_path, ocr, note=note)
    enriched = enrich(classification.primary, fields, ocr)
    # Apply per-tenant PII redaction BEFORE routing and persistence so
    # neither the audit trail, the saved classification, nor an outbound
    # webhook ever sees the raw OCR text. Classification itself is run
    # against the unredacted image+OCR because the model needs real
    # tokens to decide what the screenshot is; only stored / shipped
    # text is sanitized.
    redact_modes = _tenant_redact_modes(tenant_id)
    if redact_modes:
        ocr = ocr.model_copy(update={"text": redact_text(ocr.text, redact_modes)})
        enriched_dict = redact_fields(
            enriched.model_dump(), redact_modes
        )
        enriched = type(enriched).model_validate(enriched_dict)
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
            Repository().save_result(
                result,
                image_path=image_path,
                principal=principal,
                tenant_id=tenant_id,
            )
        except Exception as exc:
            log.warning("persist_failed", error=str(exc))
    log.info(
        "processed_image",
        id=result.id,
        primary=classification.primary.value,
        elapsed_ms=elapsed_ms,
    )
    return result
