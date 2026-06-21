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
    # Party size / split-bill count. Restaurant receipts commonly
    # print ``Party of 4`` / ``Guests: 2`` / ``Split 3 ways`` near
    # the header or footer. Stored as an int so dashboards can sum
    # covers across the period or derive per-person spend
    # (``total / party_size``). ``None`` when the receipt gives no
    # cover-count signal (a typical retail receipt, for example).
    party_size: int | None = None
    # Refund / void amount when the receipt represents a returned or
    # cancelled transaction. Stored as a positive float (the amount
    # being refunded) regardless of whether the printer used a
    # leading ``-`` or wrote the number bare with a ``REFUND`` /
    # ``VOID`` / ``CANCELLED`` keyword. ``None`` for normal sales.
    # Dashboards use this to surface refund volume and net revenue
    # without re-parsing every receipt.
    refund_amount: float | None = None
    # Loyalty / membership programme identifier printed for repeat
    # customers (``Member: 12345``, ``Loyalty #ABC-99``, ``Rewards
    # ID: 4477``). Stored as a string verbatim because programmes
    # mix digits with letters and dashes. The store / register
    # numbers below cover the OTHER common identifier slots a
    # receipt can carry; loyalty_id is specifically the
    # customer-side identifier (linked to a person), distinct from
    # the store / register identifiers (linked to a location /
    # terminal).
    loyalty_id: str | None = None
    # Store / branch identifier printed at the top of multi-location
    # chain receipts (``Store #1234``, ``Branch 045``, ``Location
    # No. 12``). String because chains mix numeric and alphabetic
    # codes. Dashboards group sales by store using this slot.
    store_id: str | None = None
    # POS terminal / register identifier printed alongside the
    # cashier line on most receipts (``REG 02``, ``Register #3``,
    # ``Terminal 5``, ``Till 04``). String for symmetry with the
    # other id fields. Dashboards use this to spot a specific
    # terminal that is consistently dropping line items or
    # producing voids.
    register_id: str | None = None
    # Cashier / operator name printed on retail receipts (``Cashier:
    # Bob``, ``Operator: ALICE``, ``Clerk #04 - Charlie``). String
    # because the captured value is the displayed human-readable
    # name (or operator identifier). Dashboards group sales by
    # cashier to surface per-person performance and identify
    # cashier-specific anomalies (voids, refunds). ``None`` when
    # the receipt prints no operator line.
    cashier: str | None = None
    # Server / waiter name printed on restaurant receipts (``Server:
    # Alice``, ``Your server was Bob``, ``Waiter: Charlie``,
    # ``Served by Diana``). Distinct from ``cashier`` because in a
    # full-service restaurant the server (who takes orders) and the
    # cashier (who runs the register) are often different people.
    # Restaurant dashboards use this to compute per-server tip
    # rates and table-turnover metrics.
    server: str | None = None
    # Signature / signed-by marker printed on credit-card slips and
    # delivery receipts. The capture is a small dict so dashboards
    # can distinguish a present-but-blank signature box from a named
    # signer:
    #
    #   {"present": True}                 -- bare ``Signature: _____`` or
    #                                       ``X____`` placeholder, no name
    #   {"present": True, "name": "Bob"}  -- ``Signed by: Bob`` /
    #                                       ``Signature: Bob`` (named)
    #
    # ``None`` when the receipt prints no signature line at all
    # (typical for retail point-of-sale receipts).
    signature: dict[str, str | bool] | None = None
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
    # When ``language == "typescript"``, surface the TypeScript-only
    # features the snippet exercises. Each entry is a short tag in:
    # ``decorator`` (``@Component``), ``as_cast`` (``foo as Bar``),
    # ``angle_cast`` (``<Bar>foo``), ``generic`` (``Array<T>``,
    # ``function<T>(...)``), ``enum`` (``enum X { ... }``),
    # ``readonly`` (``readonly x``), ``abstract`` (``abstract class``),
    # ``access_modifier`` (``private`` / ``public`` / ``protected``),
    # ``namespace`` (``namespace X { ... }``), ``optional_chain``
    # (``foo?.bar``), ``non_null_assert`` (``foo!``). Tags are unique
    # per snippet; empty list when the snippet is non-TS or has none.
    ts_features: list[str] = Field(default_factory=list)
    # ``True`` when the snippet looks like minified / bundled JS or
    # TS (long single-line statements, near-zero whitespace, no
    # newlines after ``;`` / ``{`` / ``}``). ``False`` otherwise.
    # Dashboards use this to surface "looks bundled" annotations on
    # code captures so a reviewer knows not to read the snippet
    # line-by-line. Only meaningful for languages == javascript /
    # typescript / jsx / tsx; the detector returns False for other
    # languages even when their line stats look minified.
    minified: bool = False
    # Shebang interpreter pulled from a leading ``#!/path/to/x`` or
    # ``#!/usr/bin/env x`` line. Stored as the short interpreter name
    # (``python3``, ``bash``, ``node``, ``ruby``, etc.) so dashboards
    # can group "scripts run under bash" without parsing the full
    # path. ``None`` when the snippet has no shebang.
    interpreter: str | None = None
    # Comment density of the snippet as a fraction in [0.0, 1.0]:
    # the share of NON-BLANK lines whose first non-whitespace token
    # opens a comment for the snippet's language. Examples:
    #
    #   * Python / Ruby / Shell / Yaml: ``#``
    #   * JS / TS / Java / C / C++ / Go / Rust / C# / Kotlin / Swift /
    #     PHP / Scala: ``//``
    #   * SQL / Lua / Haskell: ``--``
    #   * Lisp / Scheme / Clojure: ``;``
    #   * Erlang / Elixir: ``%`` and ``#`` respectively
    #
    # Block-comment openers (``/*``, ``"""``, ``'''``, ``<!--``) DO
    # count when they sit at the start of a line. The denominator
    # excludes blank lines so a file padded with extra newlines
    # doesn't artificially lower the density.
    #
    # 0.0 means "no comments" (or all-blank snippet); 1.0 means
    # "every non-blank line is a comment" (a documentation-only
    # snippet). Dashboards use this to surface heavily-commented
    # snippets (educational examples) vs raw code (production
    # output) without an LLM round trip.
    comment_density: float = 0.0
    # ``True`` when the snippet was captured with a line-number
    # prefix column (every non-blank line starts ``<n>: code`` or
    # ``<n> code`` or ``<n>|code``). The detector strips the prefix
    # column from ``code`` before storage so dashboards render the
    # actual source without the line-number gutter. Common shapes:
    #
    #   * ``1: foo()``        -- pasted from a doc / blog
    #   * ``1| foo()``        -- pasted from a code review tool
    #   * ``  1  foo()``      -- right-aligned column (cat -n style)
    #   * ``1 foo()``         -- minimal form
    #
    # When ``numbered = True``, ``code`` is the de-numbered body and
    # ``line_count`` reflects the de-numbered line count (which is
    # identical to the original line count, since stripping a prefix
    # column doesn't remove any lines). Dashboards use this to surface
    # "looks copy-pasted from a doc with line numbers" annotations.
    numbered: bool = False
    # Count of TODO / FIXME / XXX / HACK / BUG / NOTE / OPTIMIZE
    # action-comment markers in the snippet. Useful for code-review
    # screenshots where a reviewer wants to surface "this file has 7
    # TODOs" annotations without re-reading the snippet line by line.
    #
    # The detector matches case-sensitive ALL-CAPS markers preceded by
    # a comment leader (the language's leader, falling back to ``#``
    # for unknown languages) and followed by a non-alphanumeric
    # boundary (``:`` / space / parens / end-of-line). Inline
    # appearances inside a comment count (``# TODO: fix this`` and
    # ``# Fix the TODO`` both register). Markers inside string
    # literals are NOT excluded because we don't tokenise -- this is
    # a conservative overcount we accept as the trade-off for keeping
    # the detector deterministic and fast.
    todo_count: int = 0
    # Detected open-source license header at the top of the snippet,
    # as a short SPDX-style tag: ``mit`` / ``apache-2.0`` / ``gpl-3.0`` /
    # ``gpl-2.0`` / ``lgpl-3.0`` / ``bsd-2-clause`` / ``bsd-3-clause`` /
    # ``mpl-2.0`` / ``isc`` / ``unlicense`` / ``cc0-1.0`` / ``agpl-3.0``.
    # ``None`` when no recognised license header is present.
    #
    # Detection scans the FIRST 30 lines of the snippet for the
    # distinctive opening phrase of each license (``Permission is
    # hereby granted, free of charge, ...`` for MIT, ``Licensed under
    # the Apache License, Version 2.0`` for Apache, etc). The shorter
    # tags (MIT / ISC) are checked LAST because their distinctive
    # wording overlaps with longer licenses (BSD also contains the
    # ``permission is granted`` phrasing) -- this ordering means a
    # full BSD-3-Clause header tags as ``bsd-3-clause``, not MIT.
    # Dashboards use this to surface license-attribution annotations
    # and to flag GPL-family snippets in code-review screenshots.
    license: str | None = None
    # Top-level docstring / JSDoc captured from the snippet. We look
    # for the structured documentation comment that sits above the
    # first top-level declaration:
    #
    #   * Python: ``\"\"\"summary\"\"\"`` / ``'''summary'''`` at module
    #     level OR as the first statement inside the first top-level
    #     ``def`` / ``class`` body.
    #   * JS / TS / Java / Go / C / C++ / C# / Kotlin / Swift / Rust /
    #     PHP: the ``/** ... */`` JSDoc block immediately above the
    #     first top-level ``function`` / ``class`` / ``def`` / ``func``
    #     / ``fn`` declaration. Per-line ``*`` continuations are
    #     stripped so the surfaced body is the docstring's natural
    #     prose.
    #   * Rust: also accepts the ``///`` line-doc-comment family
    #     (collapsed into one paragraph) and the ``//!`` inner-doc
    #     family.
    #
    # Stored as the cleaned docstring text -- delimiters stripped,
    # per-line ``*`` continuations stripped, leading / trailing
    # whitespace trimmed. ``None`` when no docstring is present.
    # Dashboards use this to surface a 1-sentence summary on a
    # code-snippet card without forcing an LLM round trip.
    docstring: str | None = None


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
