"""Pydantic schemas shared across services."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Category(str, Enum):
    receipt = "receipt"
    code_snippet = "code_snippet"
    error_stacktrace = "error_stacktrace"
    chat_screenshot = "chat_screenshot"
    meme = "meme"
    document = "document"
    ui_mockup = "ui_mockup"
    chart = "chart"
    other = "other"

    @classmethod
    def all(cls) -> list[str]:
        return [c.value for c in cls]


class Confidence(BaseModel):
    category: Category
    score: float = Field(ge=0.0, le=1.0)


class Classification(BaseModel):
    primary: Category
    confidences: list[Confidence]
    rationale: str = ""

    def confidence_of(self, c: Category) -> float:
        for conf in self.confidences:
            if conf.category == c:
                return conf.score
        return 0.0


class OCRResult(BaseModel):
    text: str
    language: str = "und"
    word_count: int = 0
    mean_confidence: float = 0.0
    deskew_angle: float = 0.0
    preprocessed: bool = False


class ReceiptLine(BaseModel):
    description: str
    qty: float | None = None
    price: float | None = None
    # When the line item carries a percent-off promo (``50% off Latte``),
    # ``discount_pct`` is the percentage that was knocked off. Stored
    # as the raw percent value (50.0, not 0.5) so dashboards can display
    # ``50%`` directly.
    discount_pct: float | None = None
    # When the line item carries an absolute-amount discount (e.g.
    # ``Latte 5.00 -1.50``), ``discount_amount`` is the positive
    # absolute amount knocked off. Stored positive so callers can
    # subtract without sign confusion.
    discount_amount: float | None = None


class ReceiptFields(BaseModel):
    vendor: str | None = None
    date: str | None = None
    subtotal: float | None = None
    tax: float | None = None
    tip: float | None = None
    tip_percent: float | None = None
    discount: float | None = None
    total: float | None = None
    currency: str | None = None
    payment_method: str | None = None
    # Order / invoice / receipt number printed near the top or bottom
    # of most receipts. Stored as a string because vendors mix digits
    # with letters (``ABC-12345``, ``INV-00099``, ``#TKT-2024-007``).
    # Captured verbatim from the OCR pass (with any ``#`` prefix kept
    # because dashboards almost always render it back with the hash).
    order_number: str | None = None
    # How the printed prices relate to tax: ``inclusive`` when the
    # receipt explicitly notes ``VAT included`` / ``tax incl.`` /
    # ``incl. GST`` (common in EU / AU / NZ / IN), ``exclusive`` when
    # the receipt prints ``+ tax`` / ``plus tax`` / ``tax extra``
    # (common in US sales-tax regions), and ``None`` when the receipt
    # gives no signal either way. Dashboards use this to decide
    # whether the subtotal should be displayed as the pre-tax base or
    # the customer-facing all-in price.
    tax_mode: str | None = None
    items: list[ReceiptLine] = Field(default_factory=list)


class CodeFields(BaseModel):
    language: str | None = None
    code: str = ""
    line_count: int = 0
    # When ``language == "sql"`` (or any SQL-flavoured tag), this field
    # narrows the SQL dialect to one of: ``mysql`` / ``postgres`` /
    # ``sqlite`` / ``mssql``. ``None`` means either non-SQL code or
    # ambiguous ANSI SQL without dialect-specific syntax.
    dialect: str | None = None


class ErrorFields(BaseModel):
    framework: str | None = None
    exception: str | None = None
    message: str | None = None
    likely_cause: str | None = None
    file: str | None = None
    line: int | None = None


class ChatFields(BaseModel):
    platform: str | None = None
    participants: list[str] = Field(default_factory=list)
    messages: list[dict[str, str]] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    # Read / delivered / unread status markers visible in the
    # screenshot. Each entry is a dict with at minimum a ``status``
    # tag (``delivered`` / ``read`` / ``unread`` / ``sent`` /
    # ``seen`` / ``typing``) and optionally a ``time`` (normalised by
    # parse_timestamp) so dashboards can answer "when was the last
    # message read?" without re-scanning the OCR text. Stored as a
    # list of dicts to mirror how ``messages`` is shaped; ordering
    # preserves first-seen-in-OCR order.
    statuses: list[dict[str, str]] = Field(default_factory=list)


class MemeFields(BaseModel):
    template: str | None = None
    top_text: str | None = None
    bottom_text: str | None = None


class DocumentFields(BaseModel):
    title: str | None = None
    summary: str | None = None
    page_kind: str | None = None


class UIMockupFields(BaseModel):
    framework_guess: str | None = None
    components: list[str] = Field(default_factory=list)


class ChartFields(BaseModel):
    chart_type: str | None = None
    title: str | None = None
    axes: dict[str, str] = Field(default_factory=dict)
    series: list[str] = Field(default_factory=list)


class ExtractedFields(BaseModel):
    """Discriminated bag of per-category extracted fields."""

    receipt: ReceiptFields | None = None
    code: CodeFields | None = None
    error: ErrorFields | None = None
    chat: ChatFields | None = None
    meme: MemeFields | None = None
    document: DocumentFields | None = None
    ui_mockup: UIMockupFields | None = None
    chart: ChartFields | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class RouteAction(str, Enum):
    none = "none"
    save_to_dir = "save_to_dir"
    copy_to_clipboard = "copy_to_clipboard"
    post_to_slack_webhook = "post_to_slack_webhook"
    open_url_template = "open_url_template"


class RouteDecision(BaseModel):
    action: RouteAction
    target: str | None = None
    executed: bool = False
    dry_run: bool = True
    detail: str = ""
    reason: str = ""


class ProcessRequest(BaseModel):
    filename: str
    note: str | None = None


class ProcessResult(BaseModel):
    id: str
    filename: str
    created_at: datetime
    classification: Classification
    ocr: OCRResult
    extracted: ExtractedFields
    route: RouteDecision
    elapsed_ms: int
    image_url: str | None = None


class ClassificationRecord(BaseModel):
    id: str
    filename: str
    created_at: datetime
    primary_category: Category
    confidence: float
    ocr_text: str
    extracted: ExtractedFields
    route: RouteDecision
    image_path: str | None = None
    user_corrected_to: Category | None = None
    label: str | None = None
    tags: list[str] = Field(default_factory=list)
    pinned: bool = False
