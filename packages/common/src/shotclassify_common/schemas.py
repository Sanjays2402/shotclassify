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
    # Line-item modifiers / customisations printed on the indented
    # lines beneath the parent item. Restaurant POS systems print
    # add-ons / removes / substitutions / extras directly under the
    # item they belong to:
    #
    #   Burger                   12.00
    #     + Add bacon              2.00
    #     + Extra cheese           1.50
    #     - No onions
    #     * Substitute fries
    #   Latte                     5.00
    #     + Oat milk               0.75
    #
    # Each entry is a ``{"kind": str, "text": str, "price": float | None}``
    # dict capturing one modifier line. The ``kind`` is one of:
    #
    #   ``add``   -- ``+ Add bacon`` / ``+ Extra cheese`` (the customer
    #                added something to the standard item)
    #   ``remove`` -- ``- No onions`` / ``- Hold the mayo`` (the customer
    #                 removed something from the standard item)
    #   ``sub``   -- ``* Substitute fries`` / ``Sub: side salad`` (the
    #                customer swapped one component for another)
    #   ``note``  -- bare text without a +/-/* prefix (a freeform note
    #                like ``Well done`` or ``Cut in halves``)
    #
    # ``text`` is the cleaned modifier text with the prefix /
    # punctuation stripped. ``price`` is the additional charge when
    # printed on the modifier line (typical for add-on extras), or
    # ``None`` for free customisations.
    #
    # Empty list for items without modifiers (every retail line and
    # most restaurant base items). Capped at 10 modifiers per item
    # (a single base item rarely has more in practice).
    modifiers: list[dict] = Field(default_factory=list)


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
    # Free-form reason text printed alongside a refund line. Many
    # POS systems prompt the cashier to enter a reason when issuing
    # a refund / void / return so the receipt prints it for the
    # customer:
    #
    #   Refund - damaged goods
    #   Refund: customer changed mind
    #   Reason: wrong size
    #   Void Reason: pricing error
    #   Return Reason: defective
    #
    # Stored as the cleaned reason string verbatim (case-preserved
    # because some prompt cashiers to use the customer's exact
    # wording). ``None`` when the receipt is not a refund / void OR
    # is a refund with no reason printed.
    #
    # Recognised inline shapes:
    # * ``Refund - <reason>`` / ``Refund: <reason>`` (single line,
    #   reason follows separator)
    # * ``Reason: <reason>`` / ``Reason - <reason>`` (bare reason
    #   keyword anywhere on the receipt, only when refund_amount is
    #   also populated to anchor it)
    # * ``Void Reason: <reason>`` / ``Return Reason: <reason>`` /
    #   ``Refund Reason: <reason>`` (compound keyword forms)
    #
    # Dashboards use this to bucket refunds by reason (damaged /
    # wrong-size / customer-error / pricing / quality / etc) to
    # surface operational problems.
    refund_reason: str | None = None
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
    # Suggested-tip table printed at the bottom of restaurant receipts
    # as a quick-pick reference for the customer. Example shapes:
    #
    #   Suggested Tips:
    #   15% = 1.80
    #   18% = 2.16
    #   20% = 2.40
    #
    # or the inline form:
    #
    #   Tip suggestions: 15% $1.80 | 18% $2.16 | 20% $2.40
    #
    # Each entry is a ``{"percent": float, "amount": float}`` dict
    # capturing one suggested-tip row. ``percent`` is the raw
    # percentage value (15.0, not 0.15) for consistency with the
    # ``tip_percent`` slot. ``amount`` is the positive currency
    # amount printed alongside.
    #
    # Distinct from ``tip`` (the actual gratuity the customer chose
    # to pay) and ``tip_percent`` (the derived percentage of that
    # actual tip). This slot captures the merchant's PRINTED
    # suggestions -- always 2+ rows when present, never the
    # customer's chosen line. Dashboards use this to spot when a
    # merchant's suggested-tip table is unusually steep / shallow
    # and to differentiate "no tip printed" from "tip table was
    # printed but customer skipped it".
    #
    # Empty list when the receipt prints no suggested-tip table.
    # Capped at 6 entries because real-world tables rarely exceed
    # 5 rows (a screenshot showing more is almost certainly OCR
    # noise picking up unrelated percentages).
    suggested_tips: list[dict[str, float]] = Field(default_factory=list)
    # Loyalty / rewards points earned for THIS transaction. Surfaces on
    # receipts from programmes that issue per-transaction points
    # (Starbucks Stars, Air Miles, hotel reward points, supermarket
    # clubcard, airline frequent-flyer miles). Examples:
    #
    #   Points Earned: 25
    #   Stars Awarded: 3
    #   Miles Earned: 100
    #   Rewards Points: 50
    #   Air Miles: 12
    #   Points: 35
    #
    # Stored as an int (the count of points / stars / miles awarded
    # for this single receipt). Distinct from ``loyalty_id`` which is
    # the customer's account identifier.
    #
    # ``None`` when the receipt doesn't print a points-earned line,
    # when the value isn't a positive integer, or when the line refers
    # to the BALANCE (``Total Points: 1245``, ``Points Balance:
    # 1245``) rather than the per-receipt earn (``Points Earned:
    # 25``). The earn-vs-balance distinction is enforced by
    # keyword vocabulary: only EARN keywords populate this slot, never
    # BALANCE / TOTAL / CURRENT.
    #
    # Dashboards use this to sum points earned per period, detect
    # missing-points complaints (receipt printed earn but the account
    # didn't credit), and benchmark per-transaction earn rates across
    # merchants.
    points_earned: int | None = None
    # Tip-jar / digital-tip URL printed at the bottom of restaurant /
    # cafe / service-industry receipts. Modern POS terminals (Square,
    # Stripe Terminal, Toast, Clover, etc.) now print a short URL or
    # QR-code target so the customer can leave a digital tip via
    # phone instead of writing one on the printed slip. Examples:
    #
    #   Tip QR: tip.example.com/abc123
    #   Scan to tip: https://tipme.app/jane
    #   Leave a tip: tip.toasttab.com/r/123abc
    #   Add a tip online: square.link/tip/xy7
    #   Tip your server: https://venmo.com/u/jane
    #   Cash App: $jane (cash app tag form)
    #
    # Stored as the URL string verbatim (with the ``https://`` /
    # ``http://`` scheme preserved when printed; bare hostnames are
    # also accepted because most printers omit the scheme to save
    # ink). ``None`` when the receipt doesn't print a tip URL.
    #
    # Recognised keyword shapes (most-specific-first ordering):
    # * ``Tip QR:`` / ``Tip URL:`` / ``Tip Link:``
    # * ``Scan to tip`` / ``Scan to leave a tip``
    # * ``Leave a tip`` / ``Leave a tip online`` / ``Add a tip``
    # * ``Tip your server`` / ``Tip your driver``
    # * ``Digital tip`` / ``Online tip``
    # * Bare URL containing ``tip`` in the path / host
    #
    # Cash App tags (``$jane``) and Venmo tags (``@jane``) are
    # captured when paired with a Cash App / Venmo keyword on the
    # same line, but only stored as the tag (``$jane``) -- not a
    # URL -- because the apps prefer the tag handle for routing.
    #
    # Distinct from ``raw["urls"]`` which captures every URL in the
    # receipt; ``tip_url`` is the SPECIFIC tip-target URL, useful
    # for dashboards that want to surface "this merchant has a
    # digital tipping rate of X%" analytics.
    tip_url: str | None = None
    # Split-payment / multi-tender lines printed when the customer
    # paid with more than one method or split the bill across cards.
    # Restaurant and retail POS systems print one explicit line per
    # tender component:
    #
    #   Visa: 25.00
    #   Cash: 10.00
    #   Tip: 5.00
    #
    # or restaurant split-bill receipts:
    #
    #   Visa **** 1234     25.00
    #   Mastercard ** 5678 18.00
    #
    # or gift-card-plus-card receipts:
    #
    #   Gift Card: 15.00
    #   Apple Pay: 10.00
    #
    # Each entry is a ``{"kind": str, "amount": float}`` dict
    # capturing one tender component. ``kind`` is one of:
    #
    #   ``visa``        ``mastercard``    ``amex``       ``discover``
    #   ``jcb``         ``diners``        ``unionpay``
    #   ``cash``        ``check``         ``gift_card``   ``store_credit``
    #   ``apple_pay``   ``google_pay``    ``samsung_pay``
    #   ``paypal``      ``venmo``         ``cashapp``     ``zelle``
    #   ``card``        ``credit``        ``debit``       ``ebt``
    #   ``other``       (fallback for unrecognised tender names)
    #
    # ``amount`` is the POSITIVE float amount paid by that tender
    # component (the negative sign on a printed ``-25.00`` is
    # stripped because the field semantic implies sign).
    #
    # Surfaces only when 2+ distinct tender LINES are detected so
    # dashboards can rely on ``len(tenders) > 0`` meaning "this
    # receipt has a real split-tender breakdown" without per-receipt
    # special-casing. A single tender line is the ordinary case --
    # the ``payment_method`` and ``tendered`` slots already cover
    # it.
    #
    # Distinct from ``payment_method`` (which is the single primary
    # method when the receipt didn't split). The two CAN coexist:
    # ``payment_method`` reflects the dominant or last tender, while
    # ``tenders`` carries the full component breakdown for
    # reconciliation.
    #
    # Empty list when the receipt is single-tender (the typical
    # case). Capped at 10 entries because real-world split-bill
    # receipts rarely exceed 4-6 components.
    tenders: list[dict[str, str | float]] = Field(default_factory=list)
    # Recurring / subscription charge marker. SaaS invoices and
    # subscription-billing receipts (Netflix, Spotify, Adobe, AWS,
    # Stripe-issued, monthly meal-kits) print a distinctive marker
    # to tell the customer this is an automatic recurring charge,
    # not a one-off purchase:
    #
    #   Recurring monthly
    #   Auto-renew
    #   Subscription
    #   Auto-renews on 2024-03-15
    #   Next charge: 2024-03-15
    #   Renews on April 1, 2024
    #   Monthly subscription
    #   Annual subscription
    #   Billed monthly
    #   This is a recurring charge
    #
    # Each entry is a ``{"interval": str | None, "next_charge": str
    # | None, "keyword": str}`` dict.
    #
    # * ``interval`` is the canonical billing cadence tag inferred
    #   from the keyword: ``monthly`` / ``annual`` / ``weekly`` /
    #   ``quarterly`` / ``daily`` / ``yearly`` (alias for annual) /
    #   ``biweekly`` / ``semiannual`` / ``trial`` / ``None`` when
    #   the receipt only said "recurring" / "subscription" without
    #   the cadence.
    # * ``next_charge`` is the captured next-billing-date as a
    #   string (preserved verbatim from the receipt, format varies
    #   by merchant) when printed alongside the marker, or
    #   ``None``.
    # * ``keyword`` is the literal marker phrase that fired so
    #   dashboards can render "recognised as: Auto-renew on
    #   2024-03-15" without recomputing.
    #
    # ``None`` when the receipt is a one-off purchase (most
    # receipts). Dashboards use this to surface "this customer
    # spent $50 of recurring revenue this month" without having
    # to read every receipt.
    recurring: dict[str, str | None] | None = None
    # Warranty / return-period notice printed in the small-print
    # footer of most retail receipts. Recognised forms:
    #
    #   Returns accepted within 30 days
    #   30 day return policy
    #   1-year warranty
    #   90-day warranty
    #   No returns
    #   Final sale - no refunds
    #   Manufacturer warranty: 2 years
    #   Limited 1-year warranty
    #   Return by 04/15/2024
    #
    # Stored as a ``{"kind": str, "duration_days": int | None,
    # "notice": str}`` dict. ``kind`` is one of ``return`` (a
    # return-period notice, the most common), ``warranty`` (a
    # manufacturer / limited warranty notice), ``no_returns`` (an
    # explicit final-sale / no-returns notice). ``duration_days``
    # is the normalised duration in days when the notice carries a
    # numeric duration (``30 days`` -> 30, ``1 year`` -> 365,
    # ``2 weeks`` -> 14, ``18 months`` -> 540); ``None`` for
    # qualitative notices like ``Final sale`` that carry no
    # explicit duration. ``notice`` is the raw matched phrase
    # preserved verbatim so dashboards can surface the original
    # wording for the customer.
    #
    # Dashboards use this to drive a "this receipt's return
    # window expires in 4 days" reminder workflow and to bucket
    # purchases by warranty length.
    #
    # ``None`` when no warranty / return notice is printed (most
    # restaurant receipts and small-vendor receipts).
    warranty: dict[str, str | int | None] | None = None
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
    # TODO / FIXME tracker tickets referenced from code comments. Many
    # codebases include a JIRA / GitHub-issue / Linear / Asana ticket
    # ref alongside a TODO so the comment links back to the work
    # item:
    #
    #   # TODO(JIRA-1234): wire up retry logic
    #   // FIXME: ABC-99 - off-by-one on binary search
    #   /* HACK: see #issue-42 */
    #   // TODO PROJ-100 deprecate this once Foo is replaced
    #   # NOTE: GH-789 covers the rewrite
    #   // BUG ENG-455: race condition under load
    #
    # Each entry is a ``{"marker": str, "ticket": str}`` dict
    # capturing the marker (TODO / FIXME / XXX / HACK / BUG / NOTE /
    # OPTIMIZE) and the canonical ticket identifier:
    #
    # * JIRA-style ``PROJECT-NUMBER`` (case-insensitive project tag,
    #   2..10 ALL-CAPS letters, hyphen, 1..6 digits): ``JIRA-1234``,
    #   ``ABC-99``, ``PROJ-100``, ``ENG-455``, ``GH-789``.
    # * GitHub-style hash-prefixed ``#NUMBER`` (issue / PR reference;
    #   1..6 digits): ``#1234``, ``#42``.
    # * Hash-prefixed slug ``#identifier-NUMBER`` (some bug-trackers
    #   use this shape): ``#issue-42``, ``#bug-99``.
    #
    # The matcher requires the ticket to sit on the SAME LINE as the
    # marker and inside the comment body (preceded by the language's
    # comment leader, mirroring the ``todo_count`` / ``todo_authors``
    # rules). Multiple tickets per marker count separately so a TODO
    # that cites two issues yields two entries. Capped at 50.
    #
    # Distinct from ``todo_authors`` because that slot captures
    # ``MARKER(author)`` (a human handle); this slot captures the
    # ticket / issue reference (a work-item identifier). The two
    # CAN coexist on the same marker: ``TODO(alice): #1234`` would
    # populate both slots.
    #
    # Dashboards use this list to:
    # * Surface "this snippet references 3 open JIRA tickets"
    # * Detect dead-ticket references (a TODO mentioning #42 when
    #   the issue is closed)
    # * Group TODOs by tracker for engineering reviews
    todo_tickets: list[dict[str, str]] = Field(default_factory=list)
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
    # Dependency version-pins extracted from manifest-shaped snippets.
    # Many code captures show package.json / requirements.txt /
    # Cargo.toml / Gemfile / composer.json / go.mod / pyproject.toml
    # content, and a dashboard reviewing the snippet wants to know
    # which packages it pins:
    #
    #   "react": "^18.2.0"           (package.json)
    #   requests==2.31.0             (requirements.txt)
    #   flask>=2.0,<3.0              (requirements.txt range)
    #   serde = "1.0"                (Cargo.toml)
    #   gem 'rails', '~> 7.0'        (Gemfile)
    #   "monolog/monolog": "^2.5"    (composer.json)
    #   require github.com/x v1.2.3  (go.mod)
    #   tokio = { version = "1.0", features = ["full"] }  (Cargo.toml)
    #
    # Each entry is a ``{"package": str, "version": str,
    # "ecosystem": str}`` dict. ``package`` is the package /
    # dependency name verbatim (preserving namespace separators
    # like the ``vendor/package`` form for composer or the
    # ``github.com/user/repo`` form for go). ``version`` is the
    # version specifier as printed (exact pin ``2.31.0``, caret
    # ``^18.2.0``, tilde ``~> 7.0``, range ``>=2.0,<3.0``, etc).
    # ``ecosystem`` is the inferred package-manager tag:
    # ``npm`` / ``pip`` / ``cargo`` / ``gem`` / ``composer`` /
    # ``go`` / ``maven`` / ``gradle``.
    #
    # Dashboards use this list to surface "this snippet pins 7
    # dependencies" annotations, detect outdated pins against a
    # known-bad version list, and flag snippets that should be
    # auto-updated by Dependabot / Renovate.
    #
    # De-duped on the (ecosystem, package, version) tuple; first-
    # seen order preserved. Capped at 100 entries because a
    # package.json / Cargo.lock screenshot can legitimately list
    # 50+ dependencies. Empty list when no recognised pin is present.
    dep_pins: list[dict[str, str]] = Field(default_factory=list)
    # Linter suppression / "dead code" annotation markers detected
    # in the snippet. Many code captures show ``# noqa``,
    # ``# type: ignore``, ``// eslint-disable``, ``// nolint``,
    # ``# pylint: disable=...`` and similar markers that suppress
    # one specific linter check at one specific call site.
    # Examples:
    #
    #   foo = eval(s)  # noqa: S307
    #   bar: int = "x"  # type: ignore[assignment]
    #   const x: any = 1; // eslint-disable-line @typescript-eslint/no-explicit-any
    #   if cond { ... } // nolint:errcheck
    #   def f(x): return x  # pylint: disable=missing-docstring
    #   #pragma warning disable CS0168
    #   #[allow(dead_code)]
    #   @SuppressWarnings("unchecked")
    #   /* tslint:disable:no-any */
    #
    # Each entry is a ``{"tool": str, "code": str | None,
    # "scope": str}`` dict:
    #
    #   * ``tool`` is the lowercased name of the linter / analyser
    #     whose check is being suppressed. Recognised tools:
    #     ``noqa`` (flake8 / ruff), ``mypy``, ``pyright``,
    #     ``pylint``, ``eslint``, ``tslint``, ``stylelint``,
    #     ``prettier``, ``nolint`` (golangci-lint),
    #     ``rustc``, ``clippy``, ``csharp`` (#pragma warning),
    #     ``cppcheck``, ``checkstyle``, ``spotbugs``,
    #     ``suppresswarnings`` (Java), ``swiftlint``, ``ktlint``,
    #     ``detekt``, ``sonarqube``, ``coverage``,
    #     ``shellcheck``. The catalogue is permissive -- any
    #     ``<tool>:disable`` / ``<tool>: ignore`` form catches.
    #   * ``code`` is the specific check code being suppressed
    #     when printed (``S307``, ``no-explicit-any``,
    #     ``CS0168``, ``unchecked``, ``dead_code``,
    #     ``errcheck``), or ``None`` when the suppression is a
    #     blanket "ignore everything on this line / block" (a
    #     bare ``# noqa`` with no code).
    #   * ``scope`` is the suppression scope keyword captured
    #     from the marker: ``line`` (per-line marker, the most
    #     common), ``next-line`` / ``next_line`` (suppresses the
    #     FOLLOWING line), ``block`` (multi-line ``disable`` /
    #     ``enable`` pair), ``file`` (file-level suppression),
    #     or ``unknown`` when the marker doesn't include a
    #     scope hint.
    #
    # Dashboards use this list to surface "this snippet
    # suppresses 4 linter checks" annotations, detect cargo-
    # culted blanket ``# noqa`` markers that mask real bugs,
    # and flag screenshots where multiple checks are
    # suppressed in the same hunk (often a smell during code
    # review).
    #
    # De-duped on the (tool, code, scope) tuple; first-seen
    # order preserved. Capped at 50 entries. Empty list when
    # no recognised marker is present.
    dead_code: list[dict[str, str | None]] = Field(default_factory=list)
    # Shell-script style detected from a shell snippet (one of
    # ``posix`` / ``bash`` / ``zsh`` / ``fish`` / ``powershell`` /
    # ``tcsh``). Only meaningful when the snippet is a shell
    # script (language detector tagged it as bash / sh / shell /
    # zsh / fish / powershell). Useful to discriminate which
    # shell-specific extensions a snippet relies on:
    #
    # * ``bash``        -- uses bash-specific features like
    #                      ``[[ ... ]]`` double-brackets,
    #                      ``$'...'`` ANSI-C quoting, process
    #                      substitution ``<(...)``, arrays
    #                      ``arr=(a b c)``, ``function f { }``
    #                      keyword-form, ``=~`` regex match
    # * ``zsh``         -- uses zsh-specific features like
    #                      glob qualifiers ``*(.)``, parameter
    #                      flags ``${(U)x}``, autoload, anonymous
    #                      functions ``() { ... } "$@"``, prompt
    #                      ``%F{red}`` color escapes
    # * ``fish``        -- uses fish-specific syntax like
    #                      ``set -x VAR value`` (no ``=`` assignment),
    #                      ``string match -r`` builtin, ``-- arg``
    #                      function args, fish-conf functions
    # * ``powershell``  -- uses PS-specific syntax like
    #                      ``$Variable`` PascalCase, ``-eq`` /
    #                      ``-ne`` operators, cmdlets (Get-X /
    #                      Set-X / Invoke-X), ``[CmdletBinding()]``
    # * ``tcsh``        -- uses (t)csh-specific syntax like
    #                      ``set foo = bar``, ``if (cond) then``,
    #                      ``foreach``, ``setenv``
    # * ``posix``       -- portable shell using only POSIX-defined
    #                      syntax: ``[ ... ]`` single brackets,
    #                      ``foo() { ... }`` function form, no
    #                      bash-isms. The conservative tag for
    #                      a snippet that COULD run under sh /
    #                      dash without bash extensions.
    #
    # Detection is precedence-based: PowerShell signals win
    # immediately (highly distinctive cmdlet vocabulary); fish
    # next (set-x syntax is unique); tcsh next (set= and foreach);
    # zsh next (glob qualifiers / autoload); bash next (double-
    # brackets / process-sub / ANSI-quoting); finally ``posix``
    # as the fallback for shell snippets with none of the above.
    #
    # ``None`` when the snippet's language is not shell at all
    # (a Python / JS / etc snippet returns None unconditionally),
    # OR when the snippet IS shell but the detector can't decide
    # between the styles (no signal in either direction).
    shell_style: str | None = None
    # Suspected secret literals sniffed from the snippet body.
    # Captures string literals that LOOK like API keys / credentials /
    # OAuth secrets / private keys even when not caught by the typed
    # redact modes. Useful for surfacing accidental leaks in
    # screenshot captures of .env files, config snippets, terminal
    # pastes, and code-review screenshots before the dashboard
    # renders the snippet.
    #
    # Each entry is a ``{"kind": str, "hint": str}`` dict:
    #
    # * ``kind`` is the canonical suspected-secret category tag:
    #     ``private_key``      -- BEGIN ... PRIVATE KEY block
    #     ``api_key``          -- assignment like KEY=... with
    #                             high-entropy alphanumeric value
    #     ``bearer_token``     -- Authorization: Bearer <hex>
    #     ``basic_auth``       -- Authorization: Basic <base64>
    #     ``oauth_token``      -- access_token = ... / refresh_token
    #     ``db_password``      -- password = ... / DB_PASSWORD = ...
    #     ``secret_key``       -- SECRET_KEY = ... in env / config
    #     ``connection_string`` -- postgres:// / mysql:// / mongodb://
    #                             with user:pass@ embedded
    #     ``hex_secret``       -- long hex blob (32+ chars) on an
    #                             assignment line
    # * ``hint`` is a SHORT redacted preview of the suspected
    #   value -- the first 4 chars + ``...`` + the last 4 chars
    #   so dashboards can render \"sk-1...AB89\" without leaking
    #   the full secret. For private-key blocks the hint is the
    #   block header (e.g. ``-----BEGIN RSA PRIVATE KEY-----``).
    #
    # The FULL VALUE IS NEVER STORED in this slot as a security
    # guarantee. Pair with the typed redact modes (``aws_access_key``,
    # ``github_pat``, ``slack_token``, ``jwt``, ``credit_card``) in
    # shotclassify_common.redact for defence-in-depth -- this slot
    # surfaces SUSPECTED secrets that the typed matchers missed
    # (custom env-var names, vendor-specific tokens, generic
    # high-entropy blobs).
    #
    # Empty list when no suspected secrets are detected. Capped at
    # 20 entries because a single snippet rarely contains more
    # than a handful of secret-shaped literals.
    suspected_secrets: list[dict[str, str]] = Field(default_factory=list)
    # Type-annotation density of the snippet as a fraction in [0.0, 1.0]:
    # the share of function-arg / variable / return slots that carry a
    # type annotation. Useful for surfacing "this Python is fully
    # typed" / "this Java has missing generics" annotations on
    # code-review screenshots without an LLM round trip.
    #
    # Counts the following slots PER FUNCTION DEFINITION:
    #
    #   Python:
    #     def foo(x: int, y, z: str) -> bool:    # 3 slots, 2 typed -> 0.67
    #     def bar(x, y, z):                      # 3 slots, 0 typed -> 0.0
    #     def baz(x: int) -> None:               # 1 slot + return -> 1.0
    #
    #   TypeScript:
    #     function f(x: number, y): string {}    # 2 slots + return -> 0.67
    #     const g = (x: T): void => {}           # 1 slot + return -> 1.0
    #
    #   Java / Kotlin / Scala / Go / Rust / C# / Swift:
    #     Generally always typed (the language requires annotations
    #     on every function arg) so this metric is less useful.
    #     The detector returns 1.0 for these languages when at least
    #     one function definition is detected.
    #
    # The denominator is total slots (args + returns) across all
    # function definitions in the snippet. The numerator is the
    # subset that carry a type annotation. ``self`` / ``cls`` / ``this``
    # are excluded from both counts because they're not annotated
    # in idiomatic code.
    #
    # 0.0 means "no slots are typed" (untyped Python, dynamic
    # JavaScript). 1.0 means "every slot is typed" (a fully-typed
    # snippet). The default 0.0 also covers snippets with NO
    # function definitions (which dashboards interpret as "not
    # applicable" rather than "untyped" -- check ``line_count`` to
    # distinguish).
    #
    # Distinct from ``comment_density`` which is about comment
    # coverage. This metric is about TYPE coverage.
    type_annotation_density: float = 0.0
    # Detected unused / dead imports in the snippet -- modules that
    # are imported but never referenced anywhere in the rest of the
    # code body. Each entry is the imported module / symbol name as
    # it appears in the import statement (matching the ``imports``
    # slot's format).
    #
    # Language coverage: Python (``import X``, ``import X as Y``,
    # ``from X import a, b``), JavaScript / TypeScript
    # (``import X from 'mod'``, ``import { a, b } from 'mod'``,
    # ``const { a } = require('mod')``), and Java / Kotlin / Scala
    # single-import lines (``import com.foo.Bar;``).
    #
    # Detection is lexical -- we scan the snippet body (excluding
    # the import statements themselves) for any whitespace-/punctuation-
    # bounded occurrence of the imported name. This catches the
    # common case of "imported a module, never called it" and the
    # equally common case of "removed the last usage but forgot to
    # remove the import". It does NOT understand scope -- a Python
    # module imported inside a try/except branch is treated as
    # globally available -- but the goal is "surface obvious dead
    # imports on a code-review screenshot", not "ship a full lint
    # pass".
    #
    # For ``from X import a, b`` the SYMBOLS (a, b) are checked
    # individually rather than the module name X, because that's
    # how readers think about Python "unused import" warnings.
    # For ``import X as Y`` the ALIAS Y is checked, not X.
    # For ``import X.Y.Z`` the TOP-LEVEL name X is checked.
    #
    # Pure data languages (json / csv / tsv / yaml / xml /
    # markdown / sql) and shell languages return ``[]`` because
    # the "import" concept doesn't apply.
    #
    # Empty list when no dead imports are detected (or when the
    # snippet has no imports at all). Dashboards use this to
    # surface a "code cleanup opportunity" annotation on code
    # captures.
    unused_imports: list[str] = Field(default_factory=list)
    # Per-function cyclomatic-complexity-like score for each
    # function definition detected in the snippet. Each entry is a
    # ``{"name": str, "complexity": int}`` dict.
    #
    # The score approximates McCabe's cyclomatic complexity by
    # counting decision points inside the function body:
    #
    #   * ``if`` / ``elif`` / ``else if``
    #   * ``for`` / ``while``
    #   * ``case`` / ``when`` (switch-like branches)
    #   * ``catch`` / ``except``
    #   * boolean operators ``and`` / ``or`` / ``&&`` / ``||``
    #   * ternary ``? :`` (JS / C-family)
    #
    # The base value is 1 (a function with no branches has
    # complexity 1) plus one for each decision point inside the
    # body. A function with 12 branches yields complexity 13.
    #
    # Language coverage: Python (``def`` / ``async def`` bodies
    # delimited by indentation), JavaScript / TypeScript
    # (``function`` / arrow / class methods delimited by braces),
    # Java / Kotlin / Scala / C# (method declarations delimited by
    # braces), Go (``func`` declarations delimited by braces),
    # Rust (``fn`` declarations delimited by braces).
    #
    # Functions are identified by name (the simple identifier
    # after ``def`` / ``function`` / ``fn`` / ``func``). For
    # anonymous arrow functions in JS / TS, the entry name is
    # ``<anonymous>`` so dashboards can distinguish them from
    # named functions.
    #
    # Pure data languages (json / csv / tsv / yaml / xml / sql)
    # and shell languages return ``[]`` because the "function"
    # concept doesn't apply uniformly.
    #
    # Empty list when no functions are detected. Dashboards use
    # this to flag "this function has 12 branches" on code-review
    # screenshots, surfacing potentially overcomplicated
    # functions for refactoring attention.
    complexity: list[dict[str, int | str]] = Field(default_factory=list)


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
    # Poll / survey blocks detected in the screenshot. Telegram,
    # Slack, Discord, Teams, and WhatsApp all support inline polls
    # rendered as a header line + per-option vote-count rows:
    #
    #   Telegram:
    #     📊 Poll: What's for lunch?
    #     Option 1: Pizza - 5 votes
    #     Option 2: Sushi - 3 votes
    #     Option 3: Tacos - 8 votes
    #     16 voters
    #
    #   Slack:
    #     :bar_chart: Poll: Friday demo time?
    #     1. 10am  ▓▓▓▓▓ 5
    #     2. 2pm   ▓▓▓ 3
    #     3. 4pm   ▓▓ 2
    #
    #   Discord:
    #     📊 What's the best deploy strategy?
    #     • Rolling: 12 votes
    #     • Blue/green: 8 votes
    #     • Canary: 4 votes
    #
    # Each entry is a ``{"question": str, "options": list[dict]}``
    # dict where ``question`` is the poll prompt (with the ``Poll:``
    # / emoji prefix stripped) and ``options`` is a list of
    # ``{"label": str, "votes": int}`` dicts -- one per choice.
    #
    # Recognised header shapes:
    # * Emoji-prefixed: 📊 / 📈 / 📉 / :bar_chart: / :poll:
    # * Keyword-prefixed: ``Poll:`` / ``Survey:`` / ``Vote:`` /
    #   ``Question:``
    # * Mixed: ``📊 Poll: <question>`` / ``Poll: <question>`` /
    #   ``📊 <question>``
    #
    # Recognised option shapes:
    # * Numbered: ``1. Pizza - 5 votes`` / ``1) Pizza 5`` /
    #   ``Option 1: Pizza - 5 votes``
    # * Bulleted: ``• Pizza: 5 votes`` / ``- Pizza - 5 votes`` /
    #   ``* Pizza (5)``
    # * Progress-bar: ``Pizza ▓▓▓▓▓ 5`` (Slack-style bar form)
    #
    # Each option line MUST contain BOTH a label and a vote count
    # to register; bare numbered lists without counts don't qualify
    # as poll options (they'd false-positive on every numbered prose
    # list in a chat).
    #
    # Ordering preserves first-seen-in-OCR order (across polls in
    # the same screenshot). Capped at 10 polls per screenshot, each
    # with up to 20 options. Distinct from ``messages`` because
    # polls have structured option arrays. Dashboards use this list
    # to surface poll results without an LLM round trip and to
    # detect engagement spikes (a poll with >50 votes is a notable
    # thread).
    polls: list[dict] = Field(default_factory=list)
    # Pinned / starred / favourite message markers detected in the
    # screenshot. Most chat platforms render a small badge or
    # action footer when a message is pinned to a channel or
    # starred / favourited by a user:
    #
    #   Slack:
    #     📌 Pinned by Alice
    #     ⭐ Starred
    #     Bob pinned a message to this channel
    #     Alice added a saved item
    #
    #   Telegram:
    #     📌 Pinned Message
    #     📌 Pinned by Bob
    #     Bob pinned "Welcome everyone"
    #
    #   Discord:
    #     📌 Pinned
    #     Alice pinned a message to this channel.
    #
    #   iMessage:
    #     Pinned by You
    #
    #   WhatsApp:
    #     📌 Pinned by Bob (admin)
    #
    # Each entry is a ``{"kind": str, "sender": str | None,
    # "actor": str | None}`` dict:
    #
    # * ``kind`` is one of ``pin`` (pinned to channel / thread) or
    #   ``star`` (starred / favourited / saved item).
    # * ``sender`` is the speaker the marker is attached to (the
    #   nearest preceding ``Sender:`` line) when extractable, or
    #   ``None`` for floating markers / action footers that don't
    #   sit inside a transcript.
    # * ``actor`` is the user who performed the pin / star (when
    #   captured from a ``Pinned by <name>`` / ``<name> pinned``
    #   form) or ``None`` for bare markers (``📌 Pinned``).
    #
    # Ordering preserves first-seen-in-OCR order. Capped at 30
    # entries. Dashboards use this list to surface "this thread
    # has 4 pinned messages" annotations and to spot moderation /
    # admin activity (most pins are performed by channel admins).
    pins: list[dict[str, str | None]] = Field(default_factory=list)
    # Forwarded-message markers detected in the screenshot. Most
    # chat platforms render a small badge or footer when a message
    # was forwarded from another conversation:
    #
    #   Telegram:
    #     Forwarded from Alice
    #     ↪️ Forwarded from @newschannel
    #     Forwarded from Bob via Channel-X
    #
    #   WhatsApp:
    #     Forwarded
    #     Forwarded many times
    #     -> Forwarded
    #
    #   Discord:
    #     [Forwarded from #general]
    #     ↪️ Forwarded
    #
    #   Slack:
    #     Bob shared a message from #channel
    #     (forwarded from Alice)
    #
    # Each entry is a ``{"kind": str, "forwarded_from": str | None,
    # "sender": str | None}`` dict.
    #
    # * ``kind`` is the canonical lowercase forward tag:
    #     ``forwarded``        -- single forward marker
    #     ``forwarded_many``   -- WhatsApp "Forwarded many times"
    #                             chain-marker for viral messages
    #     ``shared``           -- Slack-style "Bob shared a message"
    #
    # * ``forwarded_from`` is the source (the original sender or
    #   channel the message was forwarded from) when extractable
    #   from a ``Forwarded from X`` / ``[Forwarded from #channel]``
    #   shape, or ``None`` for bare ``Forwarded`` badges that
    #   don't surface the origin.
    #
    # * ``sender`` is the speaker in the CURRENT transcript whose
    #   message carries the forward badge (the person doing the
    #   forwarding -- nearest preceding ``Sender:`` line), or
    #   ``None`` for floating markers.
    #
    # Ordering preserves first-seen-in-OCR order. Capped at 30
    # entries. Dashboards use this list to surface "this thread
    # has 3 forwarded messages" annotations and to detect viral-
    # message propagation chains (a high-forward-count thread is
    # often misinformation in real-world Telegram / WhatsApp).
    forwards: list[dict[str, str | None]] = Field(default_factory=list)
    # Thread-reply marker detection. Slack, Discord, Microsoft Teams,
    # and some chat clients render a small footer beneath messages
    # that received sub-thread replies, surfacing the count of
    # replies and (optionally) the time of the most recent reply:
    #
    #   Slack:
    #     2 replies
    #     Last reply 2h ago
    #     5 replies   Last reply 3m ago
    #     View thread
    #     1 reply
    #
    #   Discord:
    #     12 messages ›
    #     Thread - 4 replies
    #     Replying in thread
    #
    #   Teams:
    #     Reply (3)
    #     3 replies
    #
    # Each entry is a ``{"count": int, "last_reply": str | None,
    # "sender": str | None}`` dict.
    #
    # * ``count`` is the number of replies the thread contains
    #   (parsed from the integer in the footer). For ``View thread``
    #   bare footers without a count, this is ``0`` because the
    #   thread exists but the printed count is unknown.
    # * ``last_reply`` is the elapsed-time tail ``2h ago`` /
    #   ``3m ago`` / ``just now`` when printed, or ``None`` when
    #   the platform doesn't surface one.
    # * ``sender`` is the speaker the thread-marker is attached to
    #   (the nearest preceding ``Sender:`` line) when extractable,
    #   or ``None`` for floating footers.
    #
    # Ordering preserves first-seen-in-OCR order. Capped at 20
    # entries because a single screenshot rarely shows more than
    # a handful of thread footers. Dashboards use this list to
    # surface "this thread has 4 sub-replies" annotations and to
    # detect engagement spikes (a 100-reply thread is a notable
    # discussion).
    threads: list[dict] = Field(default_factory=list)


class MemeFields(BaseModel):
    template: str | None = None
    top_text: str | None = None
    bottom_text: str | None = None


class DocumentFields(BaseModel):
    title: str | None = None
    summary: str | None = None
    page_kind: str | None = None
    # Page-number footer / header info detected in the document
    # capture. Multi-page documents (PDFs, slide decks, scanned
    # contracts, wiki pages) print a page number at the bottom or
    # top of each page in one of these conventional forms:
    #
    #   Page 3 of 12
    #   Page 1
    #   3 / 12
    #   - 5 -
    #   (continued)
    #   p. 7
    #
    # Stored as a ``{"current": int | None, "total": int | None,
    # "label": str, "continued": bool}`` dict.
    #
    # * ``current`` is the current page number when extractable
    #   (``Page 3 of 12`` -> 3, ``- 5 -`` -> 5), else ``None``.
    # * ``total`` is the total page count when extractable
    #   (``Page 3 of 12`` -> 12), else ``None`` for bare
    #   ``Page 1`` style.
    # * ``label`` is the raw matched footer phrase preserved
    #   verbatim so dashboards can surface ``"Page 3 of 12"`` as
    #   typeset by the source document.
    # * ``continued`` is ``True`` when a ``(continued)`` marker
    #   appeared alongside the page number, signalling a section
    #   that spans pages. ``False`` otherwise.
    #
    # Dashboards use this to drive "this is page 3 of 12" /
    # "this document continues" annotations on multi-page document
    # captures without re-OCRing the surrounding text.
    #
    # ``None`` for single-page captures and document-style captures
    # that print no explicit page marker (most slide-deck screenshots
    # rely on slide-counter overlays from the presenter view rather
    # than a printed footer).
    page_info: dict[str, int | str | bool | None] | None = None
    # Heading-hierarchy detection for document captures. Slide
    # decks, scanned reports, wiki pages, and contracts almost
    # always use a tiered heading structure (H1 chapter title,
    # H2 section, H3 subsection, etc.) that dashboards want to
    # surface as a document outline.
    #
    # Stored as a list of ``{"level": int, "text": str}`` dicts
    # where ``level`` is 1..6 (mirroring HTML h1..h6) and ``text``
    # is the heading line with markup / numbering stripped.
    #
    # Recognised shapes:
    # * Markdown ATX:  ``# Heading`` (h1), ``## Heading`` (h2),
    #   ``### Heading`` (h3), etc. up to ``###### Heading`` (h6).
    # * Markdown setext: a line of text followed by ``===`` (h1)
    #   or ``---`` (h2) on the next line.
    # * Numbered: ``1. Chapter`` (h1), ``1.1 Section`` (h2),
    #   ``1.1.1 Subsection`` (h3). Depth = number of dot-separated
    #   segments. ``2.3.4.5 Detail`` -> h4.
    # * Capitalised standalone line that is short (3..80 chars),
    #   sits with blank lines around it, contains no trailing
    #   punctuation, and is followed by body text. Tagged as h1
    #   for the FIRST such block when no other heading shape is
    #   present (this is the conservative title-detection rule
    #   most slide decks rely on).
    #
    # Empty list when no recognised heading shape is present
    # (typical for single-paragraph captures). Order preserves
    # source-text appearance so dashboards render the outline
    # top-to-bottom.
    headings: list[dict[str, int | str]] = Field(default_factory=list)


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
