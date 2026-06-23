"""OpenAI-compatible vision client."""
from __future__ import annotations

import base64
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shotclassify_common import (
    Category,
    ChartFields,
    ChatFields,
    Classification,
    CodeFields,
    Confidence,
    DocumentFields,
    ErrorFields,
    ExtractedFields,
    MemeFields,
    OCRResult,
    ReceiptFields,
    ReceiptLine,
    UIMockupFields,
    get_logger,
    get_settings,
)

from .prompts import CLASSIFY_SYSTEM, build_user_prompt

log = get_logger(__name__)


def _encode_data_url(path: str | Path) -> str:
    p = Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    b = p.read_bytes()
    return f"data:{mime};base64,{base64.b64encode(b).decode('ascii')}"


def _fallback_classification(ocr: OCRResult) -> tuple[Classification, ExtractedFields]:
    """Heuristic classification used when no LLM is reachable.

    This keeps the system functional offline (CI, demos, air-gapped) and
    gives extractors something to chew on.
    """
    text = (ocr.text or "").lower()
    scores: dict[Category, float] = {c: 0.02 for c in Category}
    if any(k in text for k in ["total", "subtotal", "tax", "$", "€", "£"]):
        scores[Category.receipt] = 0.55
    if any(k in text for k in ["traceback", "exception", "error:", "at ", "stacktrace"]):
        scores[Category.error_stacktrace] = 0.6
    if any(k in text for k in ["def ", "function", "const ", "import ", "class ", "=>"]):
        scores[Category.code_snippet] = 0.5
    if any(k in text for k in ["imessage", "delivered", "read at", "online", "typing"]):
        scores[Category.chat_screenshot] = 0.45
    if not text.strip():
        scores[Category.meme] = 0.3
    primary = max(scores, key=scores.get)
    # normalize
    total = sum(scores.values()) or 1.0
    confidences = [Confidence(category=c, score=round(s / total, 4)) for c, s in scores.items()]
    fields = ExtractedFields(raw={"source": "heuristic", "primary": primary.value})
    return Classification(
        primary=primary, confidences=confidences, rationale="Heuristic fallback (no LLM)."
    ), fields


def _parse_llm_payload(payload: dict[str, Any]) -> tuple[Classification, ExtractedFields]:
    primary_raw = (payload.get("primary") or "other").strip().lower()
    try:
        primary = Category(primary_raw)
    except ValueError:
        primary = Category.other
    confs_in = payload.get("confidences") or []
    confs: list[Confidence] = []
    seen: set[Category] = set()
    for c in confs_in:
        try:
            cat = Category(c.get("category", "other"))
            score = float(c.get("score", 0.0))
            score = max(0.0, min(1.0, score))
            confs.append(Confidence(category=cat, score=score))
            seen.add(cat)
        except Exception:
            continue
    for cat in Category:
        if cat not in seen:
            confs.append(Confidence(category=cat, score=0.0))
    rationale = str(payload.get("rationale", ""))[:500]
    fields_in = payload.get("fields") or {}
    fields = ExtractedFields(raw=fields_in)
    if r := fields_in.get("receipt"):
        items = [
            ReceiptLine(
                description=str(i.get("description", "")),
                qty=i.get("qty"),
                price=i.get("price"),
                discount_pct=i.get("discount_pct"),
                discount_amount=i.get("discount_amount"),
                sku=i.get("sku"),
                modifiers=i.get("modifiers") or [],
            )
            for i in (r.get("items") or [])
        ]
        fields.receipt = ReceiptFields(
            vendor=r.get("vendor"),
            date=r.get("date"),
            subtotal=r.get("subtotal"),
            tax=r.get("tax"),
            tip=r.get("tip"),
            discount=r.get("discount"),
            total=r.get("total"),
            currency=r.get("currency"),
            payment_method=r.get("payment_method"),
            order_number=r.get("order_number"),
            tax_mode=r.get("tax_mode"),
            party_size=r.get("party_size"),
            refund_amount=r.get("refund_amount"),
            refund_reason=r.get("refund_reason"),
            loyalty_id=r.get("loyalty_id"),
            store_id=r.get("store_id"),
            register_id=r.get("register_id"),
            cashier=r.get("cashier"),
            server=r.get("server"),
            signature=r.get("signature"),
            service_charge=r.get("service_charge"),
            delivery_fee=r.get("delivery_fee"),
            tendered=r.get("tendered"),
            change=r.get("change"),
            rounding=r.get("rounding"),
            tax_lines=r.get("tax_lines") or [],
            gift_card_applied=r.get("gift_card_applied"),
            promo_code=r.get("promo_code"),
            suggested_tips=r.get("suggested_tips") or [],
            points_earned=r.get("points_earned"),
            items=items,
        )
    if c := fields_in.get("code"):
        fields.code = CodeFields(
            language=c.get("language"),
            code=str(c.get("code", "")),
            line_count=int(c.get("line_count") or len(str(c.get("code", "")).splitlines())),
            dialect=c.get("dialect"),
            ts_features=c.get("ts_features") or [],
            minified=bool(c.get("minified") or False),
            interpreter=c.get("interpreter"),
            comment_density=float(c.get("comment_density") or 0.0),
            numbered=bool(c.get("numbered") or False),
            todo_count=int(c.get("todo_count") or 0),
            todo_authors=c.get("todo_authors") or [],
            todo_tickets=c.get("todo_tickets") or [],
            license=c.get("license"),
            docstring=c.get("docstring"),
            imports=c.get("imports") or [],
            copyright=c.get("copyright") or [],
            fence_language=c.get("fence_language"),
            feature_flags=c.get("feature_flags") or [],
            css_vendor_prefixes=c.get("css_vendor_prefixes") or [],
            regexes=c.get("regexes") or [],
            build_commands=c.get("build_commands") or [],
            dep_pins=c.get("dep_pins") or [],
        )
    if e := fields_in.get("error"):
        fields.error = ErrorFields(**{k: e.get(k) for k in ErrorFields.model_fields})
    if ch := fields_in.get("chat"):
        fields.chat = ChatFields(
            platform=ch.get("platform"),
            participants=ch.get("participants") or [],
            messages=ch.get("messages") or [],
            hashtags=ch.get("hashtags") or [],
            mentions=ch.get("mentions") or [],
            statuses=ch.get("statuses") or [],
            edits=ch.get("edits") or [],
            reactions=ch.get("reactions") or [],
            quotes=ch.get("quotes") or [],
            attachments=ch.get("attachments") or [],
        )
    if m := fields_in.get("meme"):
        fields.meme = MemeFields(**{k: m.get(k) for k in MemeFields.model_fields})
    if d := fields_in.get("document"):
        fields.document = DocumentFields(**{k: d.get(k) for k in DocumentFields.model_fields})
    if u := fields_in.get("ui_mockup"):
        fields.ui_mockup = UIMockupFields(
            framework_guess=u.get("framework_guess"),
            components=u.get("components") or [],
        )
    if ch := fields_in.get("chart"):
        fields.chart = ChartFields(
            chart_type=ch.get("chart_type"),
            title=ch.get("title"),
            axes=ch.get("axes") or {},
            series=ch.get("series") or [],
        )
    return Classification(primary=primary, confidences=confs, rationale=rationale), fields


@dataclass
class VisionClient:
    base_url: str
    api_key: str
    model: str
    timeout: int = 60
    max_retries: int = 2

    @classmethod
    def from_settings(cls) -> "VisionClient":
        s = get_settings()
        return cls(
            base_url=s.llm_base_url,
            api_key=s.llm_api_key,
            model=s.llm_model,
            timeout=s.llm_timeout_s,
            max_retries=s.llm_max_retries,
        )

    def classify(
        self, image_path: str | Path, ocr: OCRResult, note: str | None = None
    ) -> tuple[Classification, ExtractedFields]:
        try:
            from openai import OpenAI  # type: ignore
        except Exception:
            log.warning("openai_sdk_unavailable_using_heuristic")
            return _fallback_classification(ocr)
        try:
            client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key or "x",
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
            data_url = _encode_data_url(image_path)
            resp = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": CLASSIFY_SYSTEM},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": build_user_prompt(ocr.text, note)},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            content = resp.choices[0].message.content or "{}"
            payload = json.loads(content)
            return _parse_llm_payload(payload)
        except Exception as exc:
            log.warning("llm_classify_failed", error=str(exc))
            return _fallback_classification(ocr)


def classify_image(
    image_path: str | Path, ocr: OCRResult, note: str | None = None
) -> tuple[Classification, ExtractedFields]:
    return VisionClient.from_settings().classify(image_path, ocr, note=note)
