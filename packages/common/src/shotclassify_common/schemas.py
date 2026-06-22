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
    # Stock-keeping unit / barcode / UPC / EAN printed alongside the
    # line item on many retail receipts (``SKU: 1234567`` /
    # ``Barcode 0123456789012`` / ``Item #ABC-99`` / ``UPC 0420700``).
    # Stored as a string (alphanumeric IDs are common -- retail chains
    # mix digits, letters, and dashes). ``None`` for restaurant-style
    # receipts that do not break out per-item SKUs and for items that
    # appear without an explicit SKU/barcode line. Dashboards use this
    # to link a captured receipt back to the item catalogue without
    # forcing an LLM round trip.
    sku: str | None = None


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
    # Service charge billed separately from the tip. Restaurants and
    # delivery-aggregator receipts often print an explicit "Service
    # Charge" / "Service Fee" line that represents a mandatory
    # auto-gratuity (a 15% added for parties of 6+) or a platform fee
    # (a $2.99 DoorDash service fee). Distinct from ``tip`` because:
    #
    # * ``tip`` is the customer-discretionary gratuity (or the
    #   automatically computed gratuity if printed under a "Tip" /
    #   "Gratuity" label).
    # * ``service_charge`` is the line-itemed service / platform fee
    #   the merchant charges regardless of customer choice.
    #
    # The two CAN coexist on the same receipt -- a restaurant may
    # print both "Service Charge 5.00" (mandatory) and "Tip 4.00"
    # (additional voluntary). Stored as a positive float; ``None``
    # when the receipt does not break out a service charge.
    service_charge: float | None = None
    # Delivery / shipping fee billed for receipts that involve
    # off-premise fulfilment. Surfaces on food-delivery (UberEats /
    # DoorDash / Deliveroo), e-commerce (Amazon / Shopify), and
    # grocery-delivery receipts (Instacart). Recognised wording:
    # "Delivery Fee", "Delivery Charge", "Delivery", "Shipping",
    # "Shipping Fee", "Shipping & Handling". Stored as a positive
    # float; ``None`` for in-person retail and dine-in restaurant
    # receipts. Dashboards split this out from tax / tip / service
    # to surface per-fulfilment-channel margin.
    delivery_fee: float | None = None
    # Cash tendered by the customer. On cash-handling receipts the
    # printer typically writes "Tendered 20.00", "Cash 20.00", or
    # "Paid 20.00" followed by the change due. Stored as a positive
    # float; ``None`` for card-only receipts that do not break out a
    # tender amount.
    tendered: float | None = None
    # Change handed back to the customer. Printed as "Change 7.50",
    # "Change Due 7.50", or "Change Given 7.50" on cash receipts.
    # Stored as a positive float; ``None`` when no change line is
    # printed (card-only receipts or cash receipts that paid the
    # exact amount). Dashboards use the (tendered, change) pair to
    # spot till-discrepancy anomalies.
    change: float | None = None
    # Cash-rounding adjustment printed on receipts in countries where
    # small denomination coins are out of circulation (Australia,
    # Canada, Denmark, Finland, Hungary, Ireland, Netherlands, New
    # Zealand, Norway, Sweden, Switzerland, etc.). The printer
    # typically adds a single line like:
    #
    #   Rounding             -0.02
    #   Cash Rounding         0.03
    #   Rounding Adjustment  -0.04
    #   Cash Discrepancy      0.01
    #
    # to round the cash-payable total to the nearest 5 cents (NZD,
    # AUD, CAD) or the nearest 10 cents / NOK (NZD legacy, NOK, SEK).
    # The amount is stored SIGNED so dashboards know whether the
    # customer benefited from rounding (negative) or paid a tiny
    # premium (positive). ``None`` for normal receipts that do not
    # apply cash-rounding. Distinct from ``discount`` (a marketing
    # reduction the merchant chose) and ``change`` (the bills /
    # coins handed back); rounding is a regulatory adjustment.
    rounding: float | None = None
    # Tax-jurisdiction breakdown. When a receipt prints MORE than one
    # tax line (``State Tax 1.50 / County Tax 0.50 / City Tax 0.25``,
    # ``VAT 2.00 / GST 0.50``, ``HST 1.30 / PST 0.40``, etc.) each
    # jurisdiction is captured as a ``{"jurisdiction": str, "amount":
    # float}`` dict. The top-level ``tax`` slot continues to carry the
    # single SUM (last-match-wins on the bare ``Tax`` keyword) for
    # backward-compat with existing dashboards.
    #
    # Recognised jurisdiction vocabulary (case-insensitive):
    # * US: State Tax, County Tax, City Tax, Local Tax, Sales Tax,
    #   Federal Tax, Use Tax
    # * Canada: HST, PST, GST, QST
    # * EU / UK: VAT, EU VAT, Import VAT
    # * AU / NZ: GST
    # * India: CGST, SGST, IGST, UTGST, CESS
    # * Other: Service Tax (legacy IN), Liquor Tax, Tobacco Tax,
    #   Hotel Tax, Lodging Tax, Tourism Tax, Restaurant Tax,
    #   Resort Fee Tax
    #
    # Jurisdictions are preserved verbatim in title-case for stable
    # dashboard rendering. Empty list when the receipt has 0 or 1 tax
    # lines (a single ``Tax 2.00`` lives in the top-level ``tax``
    # slot; we only break out the list when MULTIPLE distinct
    # jurisdictions appear so dashboards always know "len > 0 means
    # this receipt has a real jurisdiction breakdown").
    tax_lines: list[dict[str, str | float]] = Field(default_factory=list)
    # Gift-card amount applied to the receipt. Surfaces on retail
    # receipts that accept gift cards as tender, on e-commerce
    # captures, and on restaurant receipts where the customer
    # redeemed a gift card. Recognised wording:
    #
    #   Gift Card        -25.00
    #   Gift Card Applied 25.00
    #   GC Redeemed       10.00
    #   Voucher            5.00
    #   Store Credit     -15.00
    #
    # Stored as a POSITIVE float (the amount knocked off by the gift
    # card) regardless of whether the printer used a leading ``-`` or
    # wrote the value bare. ``None`` when no gift-card line is
    # present. Distinct from ``discount`` (a marketing promotion the
    # merchant chose) and ``tendered`` (the cash/card the customer
    # paid with) because the gift card is a stored-value tender that
    # dashboards want to track separately for reconciliation.
    gift_card_applied: float | None = None
    # Promo / discount code the customer applied. Surfaces on
    # e-commerce receipts, food-delivery captures, and rideshare
    # captures (UberEats / DoorDash / Shopify / Amazon).
    # Recognised wording:
    #
    #   Promo Code: SAVE10
    #   Coupon Code: SUMMER2024
    #   Discount Code: WELCOME20
    #   Code: NEWUSER          (only when paired with discount/promo on the same line)
    #   Voucher Code: GIFT5
    #
    # Stored as the code string verbatim (case-preserved) with
    # surrounding punctuation stripped. ``None`` when no promo code
    # is printed.
    promo_code: str | None = None
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
    # TODO / FIXME / XXX / HACK / BUG / NOTE / OPTIMIZE markers that
    # carry an explicit author handle in parentheses immediately
    # after the marker word. Examples:
    #
    #   # TODO(alice): hook up retries
    #   // FIXME(bob): off-by-one on the binary search
    #   /* HACK(carol-87): rewrite once we drop py3.9 */
    #   ; XXX(@dave): clean up
    #
    # Each entry is a ``{"marker": str, "author": str}`` dict
    # preserving first-seen order. The marker is the recognised
    # ALL-CAPS keyword; the author is the captured handle with
    # surrounding whitespace stripped. A leading ``@`` on the
    # handle is preserved verbatim (some codebases prefix GitHub
    # handles with ``@``). A trailing ``,`` / ``;`` / ``:`` /
    # ``)`` from the OCR pass is trimmed.
    #
    # Dashboards use this to surface "Alice owns 4 outstanding
    # TODOs in this file" annotations on code-review screenshots
    # without re-reading the snippet line by line. Capped at 50
    # entries. Dedupe is intentionally NOT done because the same
    # author may legitimately own multiple TODOs in one snippet
    # and we want to count all of them.
    todo_authors: list[dict[str, str]] = Field(default_factory=list)
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
    # List of import / require / use statements found in the snippet.
    # Each entry is the most canonical short identifier we can pull
    # off the import statement:
    #
    #   * Python ``from foo.bar import baz``          -> ``foo.bar``
    #   * Python ``import foo`` / ``import foo as f`` -> ``foo``
    #   * Python ``import foo.bar.baz``               -> ``foo.bar.baz``
    #   * JS ``import { x } from 'react'``            -> ``react``
    #   * JS ``import 'side-effects'``                -> ``side-effects``
    #   * JS ``const x = require('pkg')``             -> ``pkg``
    #   * Java ``import com.foo.Bar;``                -> ``com.foo.Bar``
    #   * Go ``import "github.com/x/y"``              -> ``github.com/x/y``
    #   * Go grouped ``import ( "fmt"; "os" )``       -> ``fmt`` + ``os``
    #   * Rust ``use std::collections::HashMap;``     -> ``std::collections::HashMap``
    #   * Ruby ``require 'json'``                     -> ``json``
    #   * Ruby ``require_relative './foo'``           -> ``./foo``
    #   * PHP ``use Foo\\Bar\\Baz;``                  -> ``Foo\\Bar\\Baz``
    #
    # De-duplicated; first-seen order preserved. Capped at 50 entries.
    # Dashboards use this to surface "uses X library" annotations and
    # group snippets by stack without forcing an LLM round trip.
    imports: list[str] = Field(default_factory=list)
    # Copyright holders extracted from the snippet's header lines.
    # Each entry is a ``{"holder": str, "year": str}`` dict. ``year``
    # is the as-printed year token (``2024``, ``2020-2024``,
    # ``2020, 2021, 2024``) so dashboards can surface the freshest
    # year without re-parsing. ``holder`` is the captured rights-
    # holder name (a person, company, or organisation), trimmed of
    # trailing periods / commas / ``All rights reserved`` boilerplate.
    #
    # Recognised printer vocabularies (case-insensitive):
    #
    #   Copyright (c) 2024 ACME Corp
    #   Copyright (C) 2020-2024 Alice Author
    #   (c) 2024 ACME, All rights reserved.
    #   (C) 2024 ACME Corp.
    #   Copyright 2024 ACME Corp           (no (c) marker)
    #   COPYRIGHT 2024 ACME CORP           (uppercase)
    #
    # Detection scans the first 30 header lines (same window as
    # ``license`` detection). Multiple distinct holders may appear on
    # the same header (a derived work that lists both upstream and
    # downstream copyrights); we capture each. De-duplicated on the
    # (holder, year) pair. Empty list when no copyright lines are
    # present.
    copyright: list[dict[str, str]] = Field(default_factory=list)
    # Markdown fence language tag when the snippet was captured
    # alongside a fenced code block. Markdown wraps code in triple-
    # backtick fences with an optional language tag immediately
    # after the opening backticks:
    #
    #   ```python
    #   def foo(): ...
    #   ```
    #
    # Dashboards use this tag as a high-confidence language signal
    # (the author explicitly declared it) which is more reliable
    # than the heuristic ``detect_language`` pass for OCR captures
    # of docs, blog posts, GitHub README sections, and chat
    # captures of code snippets shared with a fenced block.
    #
    # Stored as the normalised lowercase tag (``python`` /
    # ``javascript`` / ``ts`` / ``go`` / ``rust`` etc.) verbatim
    # from what the author wrote; we don't try to canonicalise
    # ``js`` -> ``javascript`` because the original tag carries
    # author intent.
    #
    # ``None`` when no fence is present, when the fence has no
    # language tag, or when the snippet doesn't include the fence
    # markers at all (a bare code snippet without surrounding
    # markdown).
    fence_language: str | None = None
    # Feature-flag client SDK call sites detected in the snippet.
    # Each entry is a ``{"vendor": str, "key": str}`` dict capturing
    # the feature-flag vendor (``launchdarkly`` / ``statsig`` /
    # ``unleash`` / ``optimizely`` / ``split`` / ``posthog`` /
    # ``flagsmith`` / ``configcat``) and the flag key referenced
    # in the call.
    #
    # Recognised SDK shapes:
    #
    #   * LaunchDarkly: ``ldClient.variation("flag-key", user, false)`` /
    #     ``client.variation("flag-key", ...)`` / ``boolVariation`` /
    #     ``stringVariation`` / ``jsonVariation``
    #   * Statsig: ``Statsig.checkGate("flag-key")`` /
    #     ``statsig.checkGate("flag-key")`` /
    #     ``getExperiment("exp-name")`` / ``getConfig("config-name")``
    #   * Unleash: ``unleash.isEnabled("flag-key")`` /
    #     ``client.isEnabled("flag-key")``
    #   * Optimizely: ``optimizely.isFeatureEnabled("flag-key", userId)`` /
    #     ``optimizelyClient.activate("exp-key", userId)``
    #   * Split.io: ``client.getTreatment("flag-key", userId)`` /
    #     ``splitClient.getTreatment("flag-key")``
    #   * PostHog: ``posthog.isFeatureEnabled("flag-key")`` /
    #     ``getFeatureFlag("flag-key")``
    #   * Flagsmith: ``flagsmith.hasFeature("flag-key")`` /
    #     ``flags.is_feature_enabled("flag-key")``
    #   * ConfigCat: ``configcat.getValue("flag-key", false)``
    #
    # Dashboards use this list to surface "this code references
    # 3 LaunchDarkly flags" annotations on code-review screenshots
    # and to spot when a deprecated flag is still being checked.
    # Distinct from ``imports`` because the SDK's import is the
    # library dependency (e.g. ``launchdarkly-node-sdk``) while
    # this slot is the per-call flag-key reference.
    #
    # De-duped on ``(vendor, key)`` pair; first-seen order preserved.
    # Capped at 50 entries. Empty list when no flag-client calls
    # are present.
    feature_flags: list[dict[str, str]] = Field(default_factory=list)
    # CSS vendor-prefix tags found in the snippet. Each entry is one
    # of the canonical CSS vendor prefixes:
    #
    #   ``-webkit-``  -- Chrome / Safari / Edge
    #   ``-moz-``     -- Firefox
    #   ``-ms-``      -- Internet Explorer / legacy Edge
    #   ``-o-``       -- Opera (Presto)
    #   ``-khtml-``   -- Konqueror (legacy)
    #
    # The detector scans CSS-family snippets (language ``css`` /
    # ``scss`` / ``sass`` / ``less`` / ``stylus``) for property
    # declarations and CSS function calls that use a vendor prefix.
    # Tags are de-duped first-seen-order so a snippet with five
    # ``-webkit-`` rules surfaces ``-webkit-`` once.
    #
    # Dashboards use this list to surface "this CSS still ships
    # legacy vendor prefixes" annotations on code-review screenshots
    # and to flag stylesheets that can be modernised by removing
    # obsolete prefixes (most webkit prefixes have been unprefixed
    # since 2016+; ms / o prefixes are essentially dead).
    #
    # Empty list when the snippet is non-CSS or has no recognised
    # vendor-prefix usage.
    css_vendor_prefixes: list[str] = Field(default_factory=list)
    # Regex literals extracted from the snippet. Each entry is a
    # ``{"flavor": str, "pattern": str, "flags": str}`` dict capturing
    # the regex's source pattern, the regex flags (when present), and
    # the syntax flavor (the language family the literal was found in,
    # because syntactic details differ -- Python ``re``, JS slash-
    # delimited, Ruby ``%r{...}``, Perl ``qr/.../``, Go raw-string
    # backtick blocks passed to ``regexp.MustCompile``, etc.).
    #
    # Recognised flavors:
    #
    #   * ``js``      -- JavaScript / TypeScript ``/pattern/flags``
    #                    literals (with the standard JS flag set
    #                    ``gimsuyd``)
    #   * ``python``  -- ``re.compile("pattern")`` / ``re.match`` /
    #                    ``re.search`` / ``re.findall`` / ``re.sub``
    #                    + ``r"..."`` raw-string variants
    #   * ``ruby``    -- ``%r{...}`` / ``%r!...!`` / ``%r/.../``
    #                    forms; slash-delimited Ruby regexes share
    #                    JS syntax and are captured under ``js``
    #                    flavor when the language detector hasn't
    #                    settled
    #   * ``perl``    -- ``qr/.../`` / ``qr{...}`` literals
    #   * ``go``      -- ``regexp.MustCompile(`pattern`)`` /
    #                    ``regexp.Compile(`pattern`)`` with both
    #                    backtick raw-string and double-quoted body
    #   * ``java``    -- ``Pattern.compile("pattern")`` /
    #                    ``Pattern.compile("pattern", flags)``
    #   * ``rust``    -- ``Regex::new("pattern")`` /
    #                    ``Regex::new(r"...")``
    #   * ``c#``      -- ``new Regex("pattern")`` /
    #                    ``Regex.Match("input", "pattern")``
    #   * ``shell``   -- ``grep "pattern"`` / ``sed 's/pattern/.../''``
    #                    NOT extracted -- shell regex is too varied
    #                    and the extractor would false-positive on
    #                    quoted prose. Future-work item.
    #
    # Dashboards use this list to surface "this code defines 6 regex
    # literals" annotations and to flag obviously-wrong patterns
    # (catastrophic backtracking, double-escaping bugs, unanchored
    # email regexes) on code-review screenshots.
    #
    # De-duped on ``(flavor, pattern, flags)`` tuple. First-seen
    # order preserved. Capped at 50 entries. Empty list when no
    # regex literal is present.
    regexes: list[dict[str, str]] = Field(default_factory=list)
    # Build-tool / package-manager / task-runner command lines
    # detected in the snippet. Code snippets and terminal captures
    # often paste a recipe alongside the actual code:
    #
    #   $ npm install
    #   $ yarn add react@18
    #   $ pnpm run build
    #   $ pip install -r requirements.txt
    #   $ poetry add httpx
    #   $ uv sync
    #   $ cargo build --release
    #   $ go build ./...
    #   $ make test
    #   $ bundle install
    #   $ gem install rails
    #   $ composer require monolog/monolog
    #   $ mvn clean install
    #   $ gradle wrapper
    #   $ dotnet restore
    #   $ docker build -t app .
    #   $ kubectl apply -f deploy.yaml
    #   $ terraform apply
    #   $ helm install app ./chart
    #
    # Each entry is a ``{"tool": str, "command": str}`` dict.
    # ``tool`` is the canonical lowercase package-manager / build-
    # tool name (``npm`` / ``yarn`` / ``pnpm`` / ``pip`` / ``poetry``
    # / ``uv`` / ``cargo`` / ``go`` / ``make`` / ``bundle`` / ``gem``
    # / ``composer`` / ``mvn`` / ``gradle`` / ``dotnet`` / ``docker``
    # / ``kubectl`` / ``terraform`` / ``helm`` / ``brew`` / ``apt`` /
    # ``yum`` / ``dnf`` / ``pacman`` / ``apk``). ``command`` is the
    # full command line as printed, with any leading shell prompt
    # (``$ `` / ``# `` / ``> `` / ``PS> `` / ``$ \\``) stripped.
    #
    # The detector recognises commands whether they appear:
    #   * On a leading prompt line (``$ npm install``) -- the most
    #     common shape in tutorial / README screenshots.
    #   * At line-start with no prompt (``npm install``) -- a copy-
    #     pasted recipe.
    #   * Inside a shell script (``#!/bin/bash`` followed by command
    #     lines).
    #
    # Dashboards use this list to surface "uses npm + cargo + docker"
    # toolchain annotations on code-review screenshots and to spot
    # incompatible-with-CI commands at a glance (a screenshot that
    # shows ``yarn`` when the repo's lockfile is ``package-lock.json``
    # is a red flag).
    #
    # De-duped on the (tool, command) tuple; first-seen order
    # preserved. Capped at 50 entries. Empty list when no recognised
    # command is present.
    build_commands: list[dict[str, str]] = Field(default_factory=list)


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
    # Edited-message markers detected in the screenshot. Each entry
    # is a ``{"sender": str | None, "text": str, "tail": str}`` dict
    # capturing the message that was marked as edited (``(edited)`` /
    # ``(edited 2m)`` tails appended to message bodies on iMessage,
    # Slack, Discord, WhatsApp, Telegram). ``sender`` is the speaker
    # when extractable from the surrounding context, or ``None`` for
    # bare lines. ``text`` is the message body with the edit marker
    # stripped. ``tail`` is the exact marker tail captured so
    # dashboards can surface ``"edited 2m"`` (when present) without
    # re-parsing.
    #
    # Recognised markers (case-insensitive):
    #   * ``(edited)``                  -- generic / WhatsApp
    #   * ``(edited 2m)``               -- Discord
    #   * ``(edited just now)``         -- Slack
    #   * ``(edited 2024-01-01)``       -- some clients
    #   * ``edited at 12:34``           -- Slack web
    #   * ``(modified)``                -- some bots
    #   * ``[edited]``                  -- bracket form (Telegram bots)
    #
    # Ordering preserves first-seen-in-OCR order. Capped at 30
    # entries (a single screenshot rarely shows more than a handful
    # of edits).
    edits: list[dict[str, str]] = Field(default_factory=list)
    # Per-message emoji reaction counts. Each entry is a
    # ``{"sender": str | None, "reactions": list[dict]}`` dict
    # capturing the reaction footer printed below a message body on
    # Slack / Discord / iMessage / WhatsApp / Teams. Each reaction
    # in the inner ``reactions`` list is a
    # ``{"emoji": str, "count": int}`` dict.
    #
    # Recognised footer shapes:
    #   * Slack: ``:eyes: 3  :+1: 2  :tada: 1``
    #   * Discord: ``👀 3   👍 2   🎉 1`` (inline emoji + count pairs)
    #   * iMessage: ``❤️ by Alice`` / ``👍 by Bob`` (reaction-by lines)
    #   * Generic: ``💯 5`` standalone line
    #
    # ``sender`` records the speaker the reactions belong to (the
    # nearest preceding ``Sender:`` line), or ``None`` when the
    # reactions sit outside a transcript. Ordering preserves first-
    # seen-in-OCR order. Capped at 30 entries (per-message), with
    # at most 20 reactions per message.
    reactions: list[dict] = Field(default_factory=list)
    # Replied-to / quoted-message blocks detected in the screenshot.
    # Most chat platforms render a reply by showing the quoted parent
    # message body just above the new message. Three common shapes:
    #
    #   * Slack / IRC / email-style: ``> quoted text`` (line-leading
    #     ``>`` prefix on the parent body).
    #   * iMessage / WhatsApp / Telegram: a small inline preview
    #     block above the new message body, with the parent's
    #     speaker name as a header and the parent body indented or
    #     italicised below. We detect the ``Replying to <name>: <body>``
    #     / ``In reply to <name>:`` / ``Quoting <name>:`` shapes.
    #   * Discord: the ``@<user> > quoted text`` inline form.
    #
    # Each entry is a ``{"sender": str | None, "quoted_sender": str | None,
    # "quoted_text": str, "reply_text": str}`` dict. ``sender`` is the
    # speaker of the REPLY (the message that's quoting), or ``None``
    # when the surrounding transcript context doesn't supply one.
    # ``quoted_sender`` is the speaker of the PARENT message being
    # quoted (extracted from ``Replying to <name>:`` headers or from
    # the ``> Sender: text`` Slack-style quoted-with-attribution
    # shape), or ``None`` for bare ``>`` quote blocks where the
    # platform doesn't surface a name. ``quoted_text`` is the parent
    # body with the quote marker / preamble stripped. ``reply_text``
    # is the new message body that follows the quote block (empty
    # string when the reply hasn't started yet on the same OCR line).
    #
    # Ordering preserves first-seen-in-OCR order. Capped at 20
    # entries because a single screenshot rarely shows more than a
    # handful of reply chains. Dashboards use this to thread message
    # replies without an LLM round trip and to surface "X is
    # replying to Y" annotations on chat-screenshot cards.
    quotes: list[dict[str, str]] = Field(default_factory=list)
    # Attachment markers (voice notes, images, videos, files, GIFs,
    # stickers, locations) detected in the screenshot. Most chat
    # platforms render an attachment as a small bracketed token or
    # emoji-prefixed label in place of the message body. Recognised
    # shapes:
    #
    #   * WhatsApp / iMessage:    ``[Image]`` / ``[Video]`` / ``[Voice note 0:23]``
    #                              / ``[Sticker]`` / ``[Document]`` / ``[GIF]``
    #                              / ``[Location]`` / ``[Contact]``
    #   * Telegram (italic):       ``📷 Photo`` / ``🎥 Video`` / ``🎤 Voice (0:42)``
    #                              / ``📎 Document`` / ``📍 Location``
    #                              / ``🎵 Audio (3:12)`` / ``🎬 GIF``
    #                              / ``💬 Sticker``
    #   * Slack inline:            ``📎 Attached file: <name>``
    #   * Generic English:         ``Voice message (0:42)`` / ``Photo`` / ``Image`` /
    #                              ``Video call · 1m 23s`` / ``Missed video call``
    #
    # Each entry is a ``{"sender": str | None, "kind": str,
    # "duration": str | None, "name": str | None}`` dict.
    # ``kind`` is the canonical lowercase attachment type tag:
    # ``image`` / ``video`` / ``voice`` / ``audio`` / ``document`` /
    # ``sticker`` / ``gif`` / ``location`` / ``contact`` /
    # ``video_call`` / ``audio_call``. ``duration`` (when present)
    # is the ``MM:SS`` / ``H:MM:SS`` / ``Nm Ms`` duration text from
    # voice / audio / video / call shapes. ``name`` (when present)
    # is the filename or document title for ``document`` /
    # ``image`` / ``video`` attachments that printed one.
    #
    # Ordering preserves first-seen-in-OCR order. Capped at 30
    # entries. Distinct from ``messages`` because attachments
    # carry no text body; dashboards use this list to surface
    # "this thread is mostly photos" / "this chat has 4 voice
    # notes" annotations and to bias OCR rescans toward the
    # photo / video frames.
    attachments: list[dict[str, str | None]] = Field(default_factory=list)


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
