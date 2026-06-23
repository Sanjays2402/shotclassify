"""Pipeline that runs the right extractor for the classified category."""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult

from .airports import extract_airports
from .amounts import extract_amounts
from .arns import extract_arns
from .chat import enrich_chat
from .code import enrich_code
from .colors import extract_colors
from .credit_cards import extract_credit_cards
from .crypto import extract_crypto
from .discord_ids import extract_discord_ids
from .document import enrich_document
from .emails import extract_emails
from .emojis import extract_emoji_density, extract_emojis
from .error import enrich_error
from .error_fingerprints import extract_error_fingerprints
from .fx_pairs import extract_fx_pairs
from .git_shas import extract_git_shas
from .identifiers import extract_identifiers
from .invoice_ids import extract_invoice_ids
from .jwts import extract_jwts
from .macs import extract_macs
from .network import extract_network
from .paths import extract_paths
from .percentages import extract_percentages
from .phones import extract_phones
from .postal_codes import extract_postal_codes
from .receipt import enrich_receipt
from .slack_ids import extract_slack_ids
from .social import extract_social
from .stripe_ids import extract_stripe_ids
from .timezones import extract_timezones
from .twilio_ids import extract_twilio_ids
from .urls import extract_urls
from .uuids import extract_uuids


def enrich(category: Category, fields: ExtractedFields, ocr: OCRResult) -> ExtractedFields:
    out = fields.model_copy(deep=True)
    if category == Category.receipt:
        out.receipt = enrich_receipt(out.receipt, ocr)
    elif category == Category.code_snippet:
        out.code = enrich_code(out.code, ocr)
    elif category == Category.error_stacktrace:
        out.error = enrich_error(out.error, ocr)
    elif category == Category.chat_screenshot:
        out.chat = enrich_chat(out.chat, ocr)
    elif category == Category.document:
        out.document = enrich_document(out.document, ocr)
    # meme/ui_mockup/chart/other rely on LLM fields; nothing to enrich

    # Cross-category: stash every http(s) URL found in the OCR text
    # under raw["urls"]. Runs for EVERY category because URLs show up
    # everywhere (error -> docs link, receipt -> Yelp page, chat ->
    # mostly links). Callers that need only one category's URLs can
    # ignore the key; storage already persists raw as a JSON column.
    text = ocr.text or ""
    urls = extract_urls(text)
    if urls:
        out.raw = dict(out.raw or {})
        out.raw["urls"] = urls

    # Cross-category: stash filesystem paths found in the OCR text
    # under raw["paths"]. Mirrors the URL extractor (also runs for
    # every category) -- error stacktraces, code snippets, terminal
    # screenshots, and documents all reference paths and dashboards
    # want a single key to look at. URL spans are masked out before
    # scanning so a URL's path component does not double-count.
    paths = extract_paths(text)
    if paths:
        out.raw = dict(out.raw or {})
        out.raw["paths"] = paths

    # Cross-category: stash IP / IPv6 / host:port endpoints found in
    # the OCR text under raw["network"]. Network endpoints appear in
    # every category -- error stacktraces print the upstream that
    # refused the connection, code snippets bind to ``0.0.0.0:8080``,
    # terminal screenshots paste shell URIs. URL spans are masked
    # before scanning so a URL's authority does not double-count.
    network = extract_network(text)
    if network:
        out.raw = dict(out.raw or {})
        out.raw["network"] = network

    # Cross-category: stash email addresses found in the OCR text
    # under raw["emails"]. Emails appear across every category --
    # error reports cite the on-call address, receipts include the
    # merchant's billing email, code snippets reference test
    # fixtures, chats are mostly emails between people. Email
    # spans never overlap URL spans (a URL has ``://`` between the
    # scheme and authority, while an email has ``@`` between local
    # and domain) so no masking is required.
    emails = extract_emails(text)
    if emails:
        out.raw = dict(out.raw or {})
        out.raw["emails"] = emails

    # Cross-category: stash academic / publishing identifiers (ISBN,
    # DOI, arXiv, ISSN) found in the OCR text under
    # raw["identifiers"] as a list of {"type", "value"} dicts. These
    # show up on document and chart captures most often but a code
    # snippet's docstring or a chat message can also cite a DOI, so
    # we run the matcher cross-category and let the consumer filter
    # by type. Each identifier passes its respective check-digit
    # validation (EAN-13 / mod-11 / arXiv shape) so 13-digit barcode
    # noise does not false-positive as an ISBN.
    identifiers = extract_identifiers(text)
    if identifiers:
        out.raw = dict(out.raw or {})
        out.raw["identifiers"] = identifiers

    # Cross-category: stash phone numbers found in the OCR text under
    # raw["phones"]. Phone numbers appear across categories --
    # receipts print the merchant's contact line, chat captures show
    # contact cards, signatures embed direct lines, error pages list
    # the on-call number, document captures cite source citations.
    # Output is in canonical digits-only form (with a leading ``+``
    # for E.164 matches) so dashboards de-dupe trivially across
    # printer formatting variation.
    phones = extract_phones(text)
    if phones:
        out.raw = dict(out.raw or {})
        out.raw["phones"] = phones

    # Cross-category: stash UUIDs found in the OCR text under
    # raw["uuids"]. UUIDs appear everywhere -- correlation IDs in
    # error logs, test fixtures in code snippets, resource IDs in
    # document URLs, invite links in chats. Output is canonical
    # lowercase + hyphenated RFC 4122 form so the same UUID printed
    # compact vs dashed collapses to one entry. The "nil" UUID
    # (all zeros) is rejected as a placeholder.
    uuids = extract_uuids(text)
    if uuids:
        out.raw = dict(out.raw or {})
        out.raw["uuids"] = uuids

    # Cross-category: stash git commit SHAs found in the OCR text
    # under raw["git_shas"]. SHAs appear in error stacktraces that
    # cite the release tag, code snippet docstrings, terminal
    # ``git log`` output, document build provenance, and chat PR
    # references. Full 40-hex SHAs are matched standalone; short
    # 7..12 hex SHAs require a git-vocabulary context (commit /
    # revision / rev / Fixes: / Refs: etc.) to avoid false-
    # positiving on UUIDs and color codes. Output is lowercase.
    git_shas = extract_git_shas(text)
    if git_shas:
        out.raw = dict(out.raw or {})
        out.raw["git_shas"] = git_shas

    # Cross-category: stash MAC addresses found in the OCR text under
    # raw["macs"]. MACs surface in terminal screenshots (``ifconfig``
    # / ``ip link`` output), network-config captures, ARP / DHCP
    # tables, router console output, and asset-inventory documents.
    # Output is canonical lowercase + colon-separated EUI-48 form so
    # the same MAC printed colon / dash / Cisco-dot-quad collapses to
    # one entry. The null MAC (all zeros) and broadcast MAC (all
    # ones) are rejected because they don't identify a specific
    # device. IPv6 spans are masked before scanning so a compressed
    # IPv6 doesn't false-positive as a MAC.
    macs = extract_macs(text)
    if macs:
        out.raw = dict(out.raw or {})
        out.raw["macs"] = macs

    # Cross-category: stash timezone tokens found in the OCR text
    # under raw["timezones"]. Timezones surface in chat captures
    # (message timestamps with offsets), error logs (ISO-8601
    # timestamps), receipts (merchant's local time), calendar shots,
    # and terminal date(1) output. Output normalises numeric offsets
    # to canonical +hh / +hh:mm form, the Z suffix to +00, named
    # abbreviations to uppercase, and IANA names to their canonical
    # Region/City form so the same zone printed multiple ways
    # collapses to one entry. Z-suffix matches only when adjacent to
    # an ISO-8601-ish digit so a bare "Z" in prose doesn't fire.
    timezones = extract_timezones(text)
    if timezones:
        out.raw = dict(out.raw or {})
        out.raw["timezones"] = timezones

    # Cross-category: stash credit-card BIN+last4 metadata found in
    # the OCR text under raw["credit_cards"]. PANs surface on
    # receipts (last4 with brand keyword), code snippets (test
    # fixtures), error logs (occasional leak inside a request body),
    # and chat captures (shared card details). The full PAN is NEVER
    # stored -- we deliberately persist only BIN (first 6) and last4
    # so dashboards can identify the issuing network and the
    # customer's last-4 without exposing the secret. Pair this with
    # the `credit_card` redact mode in shotclassify_common.redact to
    # strip the raw PAN from the persisted OCR text.
    cards = extract_credit_cards(text)
    if cards:
        out.raw = dict(out.raw or {})
        out.raw["credit_cards"] = cards

    # Cross-category: stash airport codes (IATA + ICAO) found in the
    # OCR text under raw["airports"]. Airport codes surface on every
    # travel-related capture -- boarding passes, flight-search
    # results, frequent-flyer dashboards, itinerary emails, chat
    # threads sharing trip plans. We accept IATA (3 letters) when
    # the code sits in our curated catalogue OR has a travel-
    # vocabulary anchor (flight / gate / depart / etc) on the same
    # or previous line OR forms a XXX-XXX / XXX -> XXX route pair.
    # ICAO (4 letters) requires the curated catalogue OR a
    # vocabulary anchor with a valid region prefix. Currency codes,
    # country codes, and common prose acronyms are rejected
    # unconditionally so a CSS / API / USD line doesn't bleed into
    # the list.
    airports = extract_airports(text)
    if airports:
        out.raw = dict(out.raw or {})
        out.raw["airports"] = airports

    # Cross-category: stash social-media handles (Twitter / X / GitHub /
    # LinkedIn / Instagram / TikTok / YouTube / Reddit / Mastodon)
    # found in the OCR text under raw["social"]. Handles surface
    # across every category -- chat captures cite creators, code
    # snippets paste GitHub repo links, document captures cite
    # LinkedIn profiles, error logs reference upstream repos,
    # receipts print the merchant's Instagram handle. We capture
    # URL forms always, and @-prefixed handles only when a
    # platform anchor (twitter / x / insta / etc) sits on the same
    # line so a generic chat ``@user`` mention doesn't bleed into
    # the list. Distinct from ChatFields.mentions because that one
    # is platform-agnostic chat-only; this one is typed social
    # handles cross-category.
    social = extract_social(text)
    if social:
        out.raw = dict(out.raw or {})
        out.raw["social"] = social

    # Cross-category: stash Slack IDs (channel / DM / user / private
    # channel / enterprise user / bot / team / enterprise / file /
    # usergroup) found in the OCR text under raw["slack_ids"]. Slack
    # IDs surface in code snippets that paste API URLs, error logs
    # that cite a failing webhook, chat captures from Slack itself
    # (the <@U012345ABCD> mention syntax), and document captures of
    # API responses. Output is a list of {kind, id} dicts so
    # downstream consumers don't have to maintain their own
    # letter-to-name table. Distinct from raw["social"] (which is
    # the cross-platform handle list) and ChatFields.mentions (chat
    # platform-agnostic).
    slack_ids = extract_slack_ids(text)
    if slack_ids:
        out.raw = dict(out.raw or {})
        out.raw["slack_ids"] = slack_ids

    # Cross-category: stash crypto addresses (Bitcoin / Ethereum /
    # Solana) found in the OCR text under raw["crypto"]. Crypto
    # addresses surface in code snippets that paste contract or
    # wallet addresses, chat captures with donation links, error
    # logs from on-chain RPC clients ("Invalid address 0xabc..."),
    # and document captures of whitepapers / exchange landing
    # pages. Bitcoin Base58Check addresses (P2PKH / P2SH) and
    # Bech32 / Bech32m addresses (SegWit / Taproot) are validated
    # against their respective checksums to keep random 34-char
    # alphanumeric runs out. Ethereum is shape-only because EIP-55
    # validation requires keccak256 (not stdlib). Solana is
    # shape-only AND requires a Solana-context anchor on the same
    # or previous line because the Base58 alphabet overlaps with
    # random base58-shaped IDs that are not addresses.
    crypto = extract_crypto(text)
    if crypto:
        out.raw = dict(out.raw or {})
        out.raw["crypto"] = crypto

    # Cross-category: stash Stripe object IDs (customer / charge /
    # payment_intent / invoice / subscription / product / price /
    # account / refund / payment_method / setup_intent / checkout_session
    # / transfer / payout / balance_transaction / file / coupon /
    # promotion_code / invoice_item / credit_note / tax_rate /
    # subscription_item / source / token) found in the OCR text under
    # raw["stripe_ids"]. Stripe IDs surface on dashboard URLs, API
    # responses pasted into code snippets, webhook payloads in error
    # logs, and developer chat captures. Each entry is a {kind, id}
    # dict so downstream consumers don't have to maintain their own
    # prefix-to-name table. Distinct from raw["slack_ids"] (Slack
    # workspace IDs) -- Stripe IDs use a typed-prefix + underscore
    # scheme that's unambiguous.
    stripe_ids = extract_stripe_ids(text)
    if stripe_ids:
        out.raw = dict(out.raw or {})
        out.raw["stripe_ids"] = stripe_ids

    # Cross-category: stash AWS resource ARNs found in the OCR text
    # under raw["arns"]. ARNs surface in error logs (IAM
    # "user X is not authorized" on a specific resource), code
    # snippets (AWS SDK calls), terraform / cloudformation captures
    # (resource declarations), document captures (security audit
    # reports), and chat captures (paste-the-ARN-when-asking-for-help).
    # Each entry is a {service, region, account, resource, arn}
    # dict so downstream consumers can route on service or region
    # without re-parsing the ARN. Accepts the three AWS partitions:
    # ``aws`` (commercial), ``aws-cn`` (China), ``aws-us-gov``
    # (GovCloud).
    arns = extract_arns(text)
    if arns:
        out.raw = dict(out.raw or {})
        out.raw["arns"] = arns

    # Cross-category: stash Discord snowflake IDs (user / channel /
    # role / guild / message / webhook / raw) found in the OCR text
    # under raw["discord_ids"]. Discord IDs surface in code snippets
    # (discord.py / discord.js SDKs), error logs from those clients,
    # chat captures of Discord conversations (the
    # ``<@123456789012345678>`` mention syntax), and document
    # captures of Discord API responses. Each entry is a {kind, id}
    # dict.
    #
    # The bare snowflake matcher REQUIRES a Discord-context anchor
    # because a 17..19 digit decimal blob is too common (UNIX
    # nanosecond timestamps, sequence numbers, opaque IDs from
    # other systems) to land safely without an anchor. Webhook
    # tokens are NEVER emitted (security guarantee).
    discord_ids = extract_discord_ids(text)
    if discord_ids:
        out.raw = dict(out.raw or {})
        out.raw["discord_ids"] = discord_ids

    # Cross-category: stash JSON Web Tokens (JWTs) found in the OCR
    # text under raw["jwts"]. JWTs surface across categories --
    # .env editors, terminal pastes of Bearer tokens, error logs
    # citing failing Authorization headers, chat captures of API
    # debugging, browser DevTools captures of cookies/localStorage.
    #
    # Each entry is a dict summarising the JWT's JOSE header and the
    # standard registered claims from the payload. The FULL TOKEN is
    # NEVER stored -- the signature segment is discarded entirely
    # and the header/payload are stored as their decoded fields.
    # Pair this with the `jwt` redact mode in
    # shotclassify_common.redact (which strips the raw token from
    # persisted OCR text) for defence-in-depth.
    jwts = extract_jwts(text)
    if jwts:
        out.raw = dict(out.raw or {})
        out.raw["jwts"] = jwts

    # Cross-category: stash currency amounts found in the OCR text
    # under raw["amounts"]. Amounts surface across every category --
    # receipts are the obvious case but error logs cite billing
    # thresholds, code snippets quote prices in test fixtures, chat
    # captures share pricing discussions, and document captures of
    # invoices / quotes / contracts.
    #
    # Each entry is a {"currency", "amount"} dict where currency is
    # the ISO 4217 three-letter code (USD / EUR / GBP / JPY / etc.)
    # when we can infer one from a symbol or explicit code, or None
    # for bare-number-with-currency-keyword shapes. Recognises
    # symbol-prefix ($12.99), symbol-suffix (12.99$), ISO-code-prefix
    # (USD 12.99), and ISO-code-suffix (12.99 USD) shapes. Decimal
    # normalisation handles both US (1,234.56) and EU (1.234,56)
    # conventions.
    amounts = extract_amounts(text)
    if amounts:
        out.raw = dict(out.raw or {})
        out.raw["amounts"] = amounts

    # Cross-category: stash postal codes (US ZIP / UK postcode / CA
    # / DE / FR / NL / AU / JP / IN / BR) found in the OCR text
    # under raw["postal_codes"]. Postal codes surface across every
    # category -- addresses on receipts, customer info in code
    # snippets, error pages that cite a billing address, chat
    # captures of shipping discussions, document captures of
    # letters / invoices / forms.
    #
    # Each entry is a {"country", "code"} dict where country is the
    # ISO 3166-1 alpha-2 code (US / GB / CA / DE / FR / NL / AU /
    # JP / IN / BR) and code is the postal code in its canonical
    # printed form for that country.
    #
    # Anchored shapes (US ZIP, German PLZ, French CP, Australian
    # postcode, Indian PIN) require a same-line country / state /
    # city anchor because bare digit-runs of those lengths are too
    # common to land safely without one. Self-anchored shapes
    # (UK postcode, Canadian, Japanese, Brazilian, Dutch) fire
    # without an extra anchor because their format is unique.
    postal_codes = extract_postal_codes(text)
    if postal_codes:
        out.raw = dict(out.raw or {})
        out.raw["postal_codes"] = postal_codes

    # Cross-category: stash error-monitoring vendor fingerprints
    # (Sentry event IDs, Datadog trace_id / span_id pairs, Rollbar
    # / New Relic / Bugsnag / Honeybadger / Airbrake event IDs)
    # found in the OCR text under raw["error_fingerprints"].
    # Fingerprints surface across categories: chat captures of
    # on-call threads, document captures of runbooks, code-snippet
    # captures of error logs, error-stacktrace captures with the
    # vendor's footer attached.
    #
    # Each entry is a {vendor, kind, id} dict. Hex IDs are
    # lowercased for stable dedupe; alphanumeric IDs preserve case.
    # Distinct from raw["uuids"] (which catches every UUID
    # regardless of vendor context) because error fingerprints
    # carry the vendor tag so dashboards can route them to the
    # correct deep-link template.
    fingerprints = extract_error_fingerprints(text)
    if fingerprints:
        out.raw = dict(out.raw or {})
        out.raw["error_fingerprints"] = fingerprints

    # Cross-category: stash currency / crypto trading pairs found in
    # the OCR text under raw["fx_pairs"]. Trading pairs surface on
    # fintech / trading-app screenshots, exchange dashboards, broker
    # captures, and developer chats about forex / crypto positions.
    # Each entry is a {base, quote, rate} dict where base is the
    # asset being priced, quote is the asset doing the pricing, and
    # rate is the float rate when printed alongside the pair (after
    # @ / : / bare whitespace) or None for bare-pair captures.
    #
    # Both sides MUST be in the curated catalogue (40 fiat ISO 4217
    # codes + ~60 top-by-market-cap crypto tickers) so a stray
    # USD/RED on a recipe website doesn't false-positive. The
    # word-boundary defence on both ends stops false-positives on
    # filesystem paths and date ranges.
    fx_pairs = extract_fx_pairs(text)
    if fx_pairs:
        out.raw = dict(out.raw or {})
        out.raw["fx_pairs"] = fx_pairs

    # Cross-category: stash Twilio SIDs (account / SMS / MMS / call /
    # recording / WhatsApp / conference / conversation / messaging
    # service / phone number / TaskRouter worker / etc) found in the
    # OCR text under raw["twilio_ids"]. SIDs surface on Twilio Console
    # URLs, code-snippet captures of Twilio SDK calls, error-log
    # captures of failing webhook payloads, and developer chat
    # captures debugging an SMS / call failure. Each entry is a
    # {kind, id} dict so downstream consumers don't have to maintain
    # their own two-letter prefix table.
    #
    # The matcher requires a two-letter ALL-CAPS prefix from the
    # recognised catalogue followed by exactly 32 LOWERCASE hex
    # chars. Lowercase-only on the tail keeps random uppercase
    # MD5/SHA hashes that happen to start with one of our prefixes
    # from misfiring. Distinct from raw["stripe_ids"] (typed prefix
    # + underscore + alphanumeric) and raw["slack_ids"] (single
    # uppercase letter + 8..10 uppercase-alphanumeric) -- Twilio
    # uses two-letter prefix + 32-lowercase-hex.
    twilio_ids = extract_twilio_ids(text)
    if twilio_ids:
        out.raw = dict(out.raw or {})
        out.raw["twilio_ids"] = twilio_ids

    # Cross-category: stash accounting invoice / quote / bill /
    # purchase-order / credit-note / estimate IDs found in the OCR
    # text under raw["invoice_ids"]. These IDs surface across every
    # category -- receipts and document captures of accounting
    # paperwork are the obvious case, but chats cite "did you pay
    # INV-2024-0099?", code snippets paste a Stripe / QuickBooks /
    # Xero invoice ID into a test fixture, and error logs reference
    # the invoice ID that failed to process. Each entry is a
    # {kind, id} dict where kind is one of invoice / bill / quote /
    # estimate / credit_note / purchase_order / accounts_receivable.
    #
    # Distinct from receipt.order_number (which is the per-receipt
    # primary number for a SINGLE receipt) and from raw["stripe_ids"]
    # (which catches Stripe-prefixed cus_ / inv_ / etc. IDs with a
    # different shape).
    invoice_ids = extract_invoice_ids(text)
    if invoice_ids:
        out.raw = dict(out.raw or {})
        out.raw["invoice_ids"] = invoice_ids

    # Cross-category: stash emoji-codepoint tally found in the OCR
    # text under raw["emojis"]. Each entry is a {emoji, codepoint,
    # count} dict capturing one distinct emoji and how many times
    # it appeared in the capture.
    #
    # Useful for meme-format dashboards, sentiment monitoring
    # (lots of 😡 vs lots of 🎉), and detecting reaction-heavy
    # chats. Sorted by descending count for "most-used-first"
    # rendering. ZWJ sequences (family / professions), skin-tone
    # modifiers, and variation selectors are combined with the
    # preceding base emoji so a compound emoji 👨‍👩‍👧‍👦 stays
    # as one logical unit.
    #
    # Distinct from chat.reactions which is per-message reaction
    # footers; this extractor is text-density tally across the
    # WHOLE OCR capture.
    emojis = extract_emojis(text)
    if emojis:
        out.raw = dict(out.raw or {})
        out.raw["emojis"] = emojis

    # Cross-category: stash an emoji-density score under
    # raw["emoji_density"]. A single float in [0.0, 1.0]
    # representing the share of non-whitespace characters that
    # are part of an emoji codepoint sequence. Useful as a
    # quick "this capture is meme-heavy" signal without having
    # to scan the raw["emojis"] per-emoji tally.
    #
    # We surface this even when raw["emojis"] is empty, BECAUSE
    # the absence of emoji is itself a legitimate dashboard
    # signal -- a density of 0.0 confirms "no emoji content"
    # and lets dashboards filter "emoji-free vs emoji-heavy"
    # captures consistently. The denominator excludes whitespace
    # so a sparse capture with lots of newlines and a compact
    # one are compared on the same content scale.
    emoji_density = extract_emoji_density(text)
    if emoji_density is not None:
        out.raw = dict(out.raw or {})
        out.raw["emoji_density"] = emoji_density

    # Cross-category: stash percent values found in the OCR text
    # under raw["percentages"]. Percentages surface across every
    # category -- performance dashboards print ``CPU 87%`` /
    # ``Memory 64%``, sentiment-poll captures show ``Yes 65% No
    # 35%``, financial captures cite ``+12.5%`` / ``-3.2%`` price
    # moves, code-review captures show coverage ``Tests passed
    # 98.5%``, marketing receipts print discount percentages
    # ``20% off``, and battery / progress indicators all use
    # percent units.
    #
    # Each entry is a {value, label, sign} dict where ``value``
    # is the numeric percent (negative when ``-`` was printed),
    # ``label`` is the nearest preceding lowercase context word
    # from a curated vocabulary (cpu / memory / yes / battery /
    # discount / etc.), and ``sign`` captures the printed
    # direction (``+`` / ``-`` / ``±``) so dashboards know an
    # ``+12%`` is an up-move.
    #
    # Range endpoints (``5-10%``) are emitted as two separate
    # entries so dashboards can sort by either bound. Out-of-
    # range values (>1000% or <-1000%) are rejected as OCR noise.
    percentages = extract_percentages(text)
    if percentages:
        out.raw = dict(out.raw or {})
        out.raw["percentages"] = percentages

    # Cross-category: stash colour values found in the OCR text
    # under raw["colors"]. Colours surface on every design /
    # frontend / brand capture -- Figma / Sketch screenshots cite
    # the colour picker's hex / rgb / hsl values, CSS / SCSS /
    # Tailwind code declares them per-rule, design-system docs
    # list the brand palette in named or hex form, accessibility
    # audits annotate contrast pairs as hex codes.
    #
    # Each entry is a {model, value} dict where ``model`` is one
    # of: hex / rgb / hsl / hsv / oklch / oklab / lab / lch /
    # named. ``value`` is the canonical string form (hex
    # lowercased + expanded from short form, function-form
    # re-rendered with comma separators, named colour
    # lowercased from the curated catalogue).
    #
    # Safety: hex requires a # or 0x prefix so bare hex blobs
    # don't misfire. Named colours use a CURATED ~100-entry
    # catalogue that EXCLUDES common prose words (red / blue /
    # green / black / white / yellow / grey) so a sentence
    # containing those words doesn't false-positive.
    #
    # Useful for design-system tooling (extract a theme palette
    # from a Figma screenshot), accessibility audits (find all
    # contrast pairs), and brand-consistency dashboards (group
    # captures by dominant colour scheme).
    colors = extract_colors(text)
    if colors:
        out.raw = dict(out.raw or {})
        out.raw["colors"] = colors

    return out
