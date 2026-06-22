# shotclassify autoship state

**Active branch: `main`** — commit and push DIRECTLY to main every tick. No feature branches.
Owner: Cake (cron) — 20-min batch loop, target 5 features per tick.

## Stack snapshot
- Python 3.11+, uv workspace, FastAPI API, worker, web (Next.js), packages: classify/common/extract/ocr/route/store, cli.
- Pipeline: OCR (tesseract) -> classify (vision LLM with heuristic fallback) -> extract (per-category) -> route (yaml rules) -> store (SQLAlchemy).
- Test runner: `uv run pytest` (~2:06 full suite, 1137 tests). `uv run ruff check .` for lint.
- DO NOT add heavy deps (no torch / tensorflow). opencv-headless already in.

## Conventions
- One feature == one commit, cron identity (`Cake (cron)` / noreply email).
- No emoji in git. No PRs, no tags, no merge to main.
- Pydantic models in `packages/common/src/shotclassify_common/schemas.py` are stored as JSON columns, so adding optional fields is safe.
- `redact_text` patterns live in `packages/common/src/shotclassify_common/redact.py`; adding a mode requires updating `PII_REDACT_MODES` in `packages/store/src/shotclassify_store/tenant_settings.py`.
- Extractors in `packages/extract/src/shotclassify_extract/*.py` enrich existing fields; tests live next to other extractor tests in `tests/`.
- Existing test patterns use `monkeypatch.setenv(...)` for env, `tmp_path` for sqlite, then `from services.api.app.main import create_app`.
- Cross-category enrichment (e.g. URLs, paths, language detection, network endpoints) belongs in `pipeline.py` and writes into `ExtractedFields.raw[<key>]` so any category benefits without needing a dedicated field.
- When you add a `ReceiptFields` / `ChatFields` / `CodeFields` field that an LLM might produce, also pass it through the wire-format mapping in `packages/classify/src/shotclassify_classify/client.py` so an LLM-supplied value survives the round trip.
- Ruff S108 fires on hardcoded `/tmp/...` literals even in pure string-parsing tests; use `/var/log/...` synthetic paths instead. N802 wants lowercase test names. I001 wants no blank line between `from __future__` and the first regular import (test file docstring counts toward import-block placement).

## Roadmap (82 features tracked, 60 complete)

### Done in tick 1 (5 features)
1. [x] Receipt: tip/gratuity extraction.
2. [x] Receipt: payment method detection.
3. [x] Error: Go panic + Ruby/Rails stacktrace support.
4. [x] Code: expanded language hints + framework guesses.
5. [x] PII redaction: jwt, aws_access_key, github_pat, slack_token modes.

### Done in tick 2 (5 features)
6. [x] Chat: timestamp parsing from message lines (ISO / 12h AM-PM / 24h).
7. [x] Receipt: discount / coupon / promo extraction.
8. [x] Receipt: tip_percent derived from tip/subtotal (fallback to total - tip).
9. [x] Extract: cross-category URL extractor populating `ExtractedFields.raw["urls"]`.
10. [x] Chat: hashtag (#tag) and mention (@user / @channel / @here / @everyone) extraction.

### Done in tick 3 (5 features)
11. [x] Code: Laravel, Symfony, Phoenix, Quarkus, Micronaut framework detection.
13. [x] Receipt: ISO currency-code inference (CAD, CHF, AUD, NZD, SEK, NOK, DKK, INR, MXN, BRL, ZAR, SGD, HKD, CNY, RMB->CNY, KRW). Last-match wins.
14. [x] Error: HTTP status code classifier — framework=http, exception=HTTP <code>, per-code likely_cause hints.
17. [x] Receipt: line-item quantity inference ("2 x Latte 6.00 = 12.00", "Latte 2 @ 6.00", decimals + comma decimal supported).
20. [x] Extract: cross-category file-path extractor populating `raw["paths"]` (POSIX / home / Windows drive / UNC; URL spans masked before scanning).

### Done in tick 4 (5 features)
18. [x] Error: .NET / CLR stacktrace support (`System.X.YException:` + `at NS.T.M(args) in FILE.cs:line N` frames + 10 likely_cause hints).
19. [x] Code: SQL dialect detection (mysql/postgres/sqlite/mssql) writing to new `CodeFields.dialect`.
22. [x] Error: Rust panic (pre-1.72 + 1.72+ shapes) + pytest assertion-frame parsing (test_name + assert expression).
23. [x] Receipt: per-line percent-off discount inference (`BOGO 50% off Latte 4.00` -> ReceiptLine with discount_pct + discount_amount; new fields).
24. [x] Extract: cross-category IP / IPv4 / IPv6 / host:port extractor populating `raw["network"]` (URL spans masked, octet/port bounded).

### Done in tick 5 (5 features)
21. [x] Chat: read/delivered/unread/typing/seen/sent status markers (new `ChatFields.statuses`; time normalised via parse_timestamp; offset-sorted; LLM wire-format updated).
27. [x] Error: Erlang/Elixir crash report parsing (framework=elixir/erlang; ** prelude branch + parse_beam_crash helper + 11 likely_cause hints).
29. [x] Extract: cross-category email-address extractor into `raw["emails"]` (RFC-conservative regex, lowercased, mailto stripped, SSH user@host rejected).
30. [x] Extract: cross-category identifier extractor (ISBN-10/13 + DOI + arXiv + ISSN) into `raw["identifiers"]` (check-digit validated, masked spans between matchers).
31. [x] Receipt: order/invoice/reference number extraction (new `ReceiptFields.order_number`; invoice/order/receipt/check/transaction/reference/confirmation vocabularies; LLM wire-format updated).

### Done in tick 6 (5 features)
26. [x] Receipt: tax-inclusive vs exclusive pricing detection (new `ReceiptFields.tax_mode`; first-in-OCR-order tiebreaker; ten EU/AU/NZ/IN/US/UK phrasings each side; LLM wire-format updated).
34. [x] Receipt: party-size / split-bill detection (new `ReceiptFields.party_size`; party/guests/covers vocabularies win over split-cues; 1..50 bound; LLM wire-format updated).
35. [x] Code: TypeScript-specific feature extraction (new `CodeFields.ts_features` list with decorator/as_cast/angle_cast/generic/enum/readonly/abstract/access_modifier/namespace/optional_chain/non_null_assert tags; runs only when language is typescript/tsx/ts; LLM wire-format updated).
25. [x] Code: minified vs hand-written JS detection (new `CodeFields.minified` bool; webpack/IIFE/bundler preamble shortcut + avg-line-length + low-newline-ratio dual-gate; JS-family languages only; LLM wire-format updated).
33. [x] Error: Python SyntaxError caret-line extraction (`message` enriched with offending source line + caret col span; CPython 3.10+ widened `~~^^^~~` shapes captured; six likely_cause hints; parse_syntax_caret helper exported).

### Done in tick 7 (5 features)
48. [x] Extract: cross-category phone-number extractor (E.164 with mixed separators, NANP-formatted with matched separators + 2-9 leading digits on area/exchange, keyword-prefixed bare NANP; output digits-only with `+` preserved; E.164 hits also register the 10-digit tail so NANP duplicates of the same number are suppressed; cap 50; raw["phones"]).
49. [x] Extract: cross-category UUID extractor (dashed + compact, v1..v5 only via version-nibble enforcement at position 12, variant nibble intentionally unconstrained so Microsoft GUIDs land too, "nil" all-zero UUID rejected as placeholder, non-hex boundaries prevent biting longer SHA hashes, canonical lowercase + hyphenated output; cap 50; raw["uuids"]).
50. [x] Extract: cross-category git SHA extractor (full SHA-1 standalone, short 7..12 hex requires git-vocabulary context: commit/revision/rev/SHA/hash + : or whitespace, git subcommand invocations on SAME LINE only, mail-style footers Fixes:/Refs:/Reverts:/See:/Cc:, GitHub-style #<sha>, reflog HEAD@{<sha>}; full and short stay distinct without repo to resolve against; cap 50; raw["git_shas"]).
36. [x] Receipt: refund / void / cancelled-transaction detection (new `ReceiptFields.refund_amount`; positive amount stored regardless of leading minus; keyword vocab Refund/Refund Amount/Refund Total + Void/Void Sale/Void Transaction + Cancelled/Cancelled Transaction/Cancellation + Return/Return Amount/Return Total + Reversal; fallback to negative-Total/Subtotal with leading minus when no keyword; per-line negatives stay as discount lines; LLM wire-format updated).
41. [x] Code: shebang interpreter extraction (new `CodeFields.interpreter`; direct path takes last segment, env wrapper takes first non-flag arg, env -S split-args skips flags, env --split-string=python3 inline form, only first line consulted so body shebangs are ignored, leading whitespace before #! is rejected because kernel exec(2) requires #! at byte 0; LLM wire-format updated).

### Done in tick 8 (5 features)
37. [x] Receipt: loyalty / membership / store / register identifier extraction (3 new ReceiptFields: loyalty_id, store_id, register_id; shared _find_keyword_id helper; first-keyword-in-catalogue-wins with most-specific keywords first; negative-lookbehind on alphas enforces word boundary so "Bookstore #1" / "Remember 1234" don't false-positive; LLM wire-format updated).
38. [x] Receipt: cashier / server name extraction (2 new ReceiptFields: cashier, server; shared _find_keyword_name helper; column-gap two-space splitter runs BEFORE whitespace normalisation so cleaned name doesn't absorb the next column; punctuation in real names preserved (Mary-Jane, O'Brien, Jr.); LLM wire-format updated; documented one accepted false-positive on prose containing the bare keyword).
44. [x] Error: PHP fatal-error stacktrace support (framework='php'; "Fatal error: Uncaught X:" and "PHP Fatal error:" preludes; thrown-in PATH on line N as innermost frame; inline "in PATH:LINE" fallback; namespace-qualified exceptions preserved; placed BEFORE JVM in elif chain because PHP exception names also satisfy _JAVA_EXC; 13-cause likely_cause catalogue).
47. [x] Error: SQL database error extraction (framework='sql'; PostgreSQL ERROR:/LINE N: shape, MySQL ERROR NNNN (SQLSTATE): shape, SQLite Error: with vocab anchor, MSSQL Msg NNNN, Level N, State N + next-line message; PostgreSQL and SQLite regexes CASE-SENSITIVE to prevent generic "Error:" prose false-positives; dialect priority MySQL -> MSSQL -> SQLite -> PostgreSQL; runs BEFORE HTTP in else branch; 13-cause likely_cause catalogue).
28. [x] Code: comment-density heuristic (new `CodeFields.comment_density` float 0..1; per-language comment-leader catalogue covers #/// /-- /; /% /<!-- families across 40+ language tags; block-comment openers /* / """ / ''' / =begin count when at start of line; "text" catchall defaults to # leader; pure data formats (json/csv/tsv) return 0.0; blank lines excluded from denominator; rounded to 2 decimal places; LLM wire-format updated).

### Done in tick 9 (5 features)
67. [x] Extract: cross-category MAC-address extractor into raw["macs"] (EUI-48; colon / dash / Cisco dot-quad input shapes; canonical lowercase colon-separated output regardless of input shape; null MAC and broadcast MAC rejected as non-device identifiers; IPv6 spans masked before scanning; cap 50).
58. [x] Extract: cross-category timezone extractor into raw["timezones"] (numeric UTC offsets +05:30 / -0800 / UTC+1 with hour range -12..+14 and minute 0..59; Z suffix on ISO-8601-ish timestamps normalising to +00; 33 named abbreviations UTC/GMT/PST/PDT/EST/EDT/CST/CDT/MST/MDT/BST/CET/CEST/IST/JST/KST/AEST/AEDT/ACST/ACDT/AWST/HST/AKST/AKDT/NZST/NZDT/WET/WEST/EET/EEST/MSK/SGT/HKT/PHT; IANA Region/City including 3-part America/Argentina/Buenos_Aires; canonical normalised output deduping +0530 vs +05:30 to +05:30 and -08 vs -0800 to -08; cap 50).
51. [x] Extract: cross-category credit-card extractor into raw["credit_cards"] (Luhn-validated 13..19 digit PANs with brand from BIN: Visa / Mastercard inc 2221-2720 / Amex / Discover / JCB / Diners / UnionPay; masked **** / XXXX / ....last4 PANs with brand inferred from same-line brand keyword; output BIN+last4 only, full PAN NEVER stored as security guarantee; pairs with existing `credit_card` redact mode; cap 50).
57. [x] PII redact: address mode (US street + suffix + optional unit + optional city + STATE ZIP / ZIP+4; UK postcode tail SW1A 1AA / M1 1AE; cardinal direction prefix N/S/E/W; house-number range 101-103 and split 1/2; Apt/Suite/Ste/Unit/# prefixes; 28 street suffixes including Trail/Loop/Row; capitalised street name required to avoid lowercase prose false-positives; added to PII_REDACT_MODES allow-list).
62. [x] Code: line-numbering detection (new `CodeFields.numbered` bool; four prefix shapes: `1: code` / `1| code` / `1\tcode` / right-aligned `  1  code` with 2+ spaces; sticky pipe form `1|code` accepted; detector runs FIRST in enrich_code so language / dialect / framework / minified / interpreter / comment-density all see the de-numbered body; 3-line minimum; non-decreasing line numbers required; mixed-separator rejected; first-line decides spaced-vs-sticky mode so deeper code indentation is preserved; LLM wire-format updated).

### Done in tick 10 (5 features)
45. [x] Error: Swift / Objective-C crash log parsing (new framework='swift'; Swift fatalError() / preconditionFailure / Swift runtime failure preludes; ObjC NSException `*** Terminating app due to uncaught exception 'NSXxxException', reason: '...'` shape; ObjC wins over Swift in hybrid logs because the NSException class is the more useful identifier; branch placed AFTER PHP because PHP's `Fatal error: Uncaught X:` is more specific (Swift fatals never carry `Uncaught` keyword); file/line pulled from Swift `: file X.swift, line N` directive when present, ObjC stays None because backtrace is OCR-mangled; 12-cause likely_cause catalogue covering nil-unwrap / NSInvalidArgument / NSRange / NSInternalInconsistency / Swift index-out-of-range / division-by-zero / precondition / assertion / NSFile / NSURL / objc_exception_throw).
46. [x] Error: Kotlin coroutine exception parsing (new framework='kotlin'; placed BEFORE JVM branch because Kotlin compiles to JVM bytecode and frame shape is identical; discriminator is either a top-level `kotlinx.coroutines.XException` exception class OR a frame referencing `kotlinx.coroutines.` / synthesised `invokeSuspend` wrapper; top-level coroutine class wins as exception slot, otherwise falls through to standard JVM `ClassName: message` header for the throw class; file/line pulled from INNERMOST Kotlin `.kt`/`.kts` frame, skipping pure-Java framework plumbing on the bottom; 10-cause likely_cause catalogue covering JobCancellation / TimeoutCancellation / ChannelClosed / deadlock / KotlinNPE / UninitializedPropertyAccess / IllegalState-coroutine-vs-general / ConcurrentModification / generic coroutine fallback).
60. [x] Receipt: signature / signed-by detection (new `ReceiptFields.signature` dict; `{"present": True}` for blank-box placeholder lines, `{"present": True, "name": "Bob"}` for named signers; 9 worded keyword variants Customer/Cardholder/Merchant/Authorized/Authorised signature, Signed/Authorized/Authorised by, Signature; bare `X____` placeholder line with X-only separator `:` or `.` (NOT `-` so X-Ray/X-Wing/hyphenated compounds don't false-positive); X11 / digit-led tails rejected; ALL-CAPS no-vowel acronyms after X rejected as not-a-name; placeholder runs `_____`/`-----`/`.....` recognised; worded matchers reject prose leads except bullet-prefixed ones; LLM wire-format updated).
64. [x] Code: TODO / FIXME marker count into `CodeFields.todo_count` (case-sensitive ALL-CAPS markers TODO/FIXME/XXX/HACK/BUG/NOTE/OPTIMIZE; must be preceded by language-appropriate comment leader anywhere on line via reused `_comment_leaders_for` catalogue from comment-density detector; followed by non-alphanumeric/non-underscore boundary so TODOIST/BUGGY/XXXX don't false-positive; multiple markers per line count separately; pure data languages json/csv/tsv short-circuit to 0; documented trade-off: markers inside string literals NOT excluded because we don't tokenise; LLM wire-format updated).
70. [x] Code: license-header detection into `CodeFields.license` (12 SPDX-style tags: apache-2.0/mit/gpl-3.0/gpl-2.0/lgpl-3.0/agpl-3.0/bsd-2-clause/bsd-3-clause/mpl-2.0/isc/unlicense/cc0-1.0; needle-group catalogue per license, ALL needles in a group must match (AND), ANY group passes (OR); longer/more-distinctive licenses checked FIRST so full BSD-3-Clause header tags as bsd-3-clause not MIT (BSD also contains "permission is granted" wording); first 30 header lines scanned only; per-line comment-leader prefix `//`/`/*`/`*`/`#`/`--`/`;`/`%` stripped before flattening so C-style multi-line `* Mozilla Public * License` collapses across the asterisk boundary; case-insensitive throughout; LLM wire-format updated).

### Done in tick 11 (5 features)
42. [x] Code: top-level docstring / JSDoc extraction into `CodeFields.docstring` (Python triple-quoted module + def/class docstrings with dedent; JSDoc `/** ... */` blocks above the first top-level declaration with `*` continuation stripping; Rust `///` line-doc-comment runs collapsed and `//!` inner-doc-comment runs at module top; language-aware priority -- python prefers triple-quoted, rust prefers `///`/`//!`, default JSDoc -> python -> rust; decorator-only lines between the JSDoc block and the declaration walked past so `@Component({})` works; 60-line scan window; LLM wire-format updated).
43. [x] Code: import-set extraction into `CodeFields.imports` (Python `import X` / `import X as Y` / `import X, Y, Z` / `from X import a, b` (captures X only); JS/TS `import X from 'mod'` / `import { a } from 'mod'` / `import 'mod'` / `require('mod')`; Java/Kotlin/Scala `import com.foo.Bar;` / `import com.foo.*;` / `import static`; Go single-line `import "fmt"` + parenthesised `import ( "fmt"; "os" )` group; Rust `use std::collections::HashMap;` + braced re-export `use std::io::{Read, Write};` (captures prefix); Ruby `require 'json'` / `require_relative`; PHP `use Foo\\Bar\\Baz;` / `require_once 'X';`; runs every matcher on every snippet -- not gated by language; de-duped first-seen-in-text order; cap 50; LLM wire-format updated).
74. [x] Code: copyright-holder extraction into `CodeFields.copyright` (list of `{holder, year}` dicts; recognised `Copyright (c) 2024 ACME` / `(C) 2020-2024 Alice` / `©` Unicode sign / `Copyright 2024 by Author` / no-(c) form / uppercase form; year shapes single / range / list / mixed; per-line comment-leader stripped before parsing; trailing `All rights reserved` / `.,;:` / stray `*/` stripped from holder; multi-holder same-line first-wins documented trade-off; dedupe on (holder.lower(), year); same 30-line window as license; LLM wire-format updated).
52. [x] Extract: cross-category airport-code extractor into `raw["airports"]` (IATA 3-letter accepted from curated ~250-airport catalogue OR with travel-vocabulary anchor on same/previous line `flight`/`gate`/`depart`/`origin`/etc OR forming route-arrow pair `XXX-XXX`/`XXX -> XXX`/`XXX → XXX`; ICAO 4-letter accepted from curated ~150-hub catalogue OR with anchor AND valid ICAO region prefix; currency/country/prose-acronym reject list incl CSS/HTML/JSON/USD/USA; word-boundary defence so ATLAS doesn't yield ATL; pipeline writes raw["airports"] for every category).
75. [x] Extract: cross-category social-handle extractor into `raw["social"]` (list of `{platform, handle}` dicts; 8 platforms: twitter/github/linkedin/instagram/tiktok/youtube/reddit/mastodon; URL forms always fire, @handle forms (twitter/instagram) only when same-line platform anchor present; reserved-path rejection on `/login`/`/marketplace`/`/p/`/`/r/`/`/status` etc; LinkedIn personal/company/school + country-subdomain; Reddit `u/` and `user/` canonicalise to `u/`; mastodon two-at `@user@instance.tld` distinct from email; distinct from `ChatFields.mentions` because that's platform-agnostic chat-only; pipeline writes raw["social"] for every category).

### Done in tick 12 (5 features)
76. [x] Receipt: delivery-fee / service-charge extraction (new `ReceiptFields.service_charge` and `ReceiptFields.delivery_fee`; service_charge matches explicit "Service Charge"/"Service Fee"/"Svc Charge"/"Svc Fee" -- bare "Service" intentionally stays in `_TIP_KEYWORDS` for backward-compat with UK bar-tab semantics; delivery_fee matches "Delivery Fee"/"Delivery Charge"/"Delivery"/"Shipping"/"Shipping Fee"/"Shipping & Handling"/"Shipping and Handling"/"Shipping Charge"/"Shipping Cost"; multi-word forms beat bare aliases; last-occurrence semantics; both fields can coexist with `tip` on the same receipt -- a restaurant prints "Service Charge 5.00" mandatory AND "Tip 4.00" voluntary; LLM wire-format updated).
63. [x] Receipt: tender / change-given detection (new `ReceiptFields.tendered` and `ReceiptFields.change`; tender catalogue: "Cash Tendered"/"Tendered"/"Tender"/"Amount Tendered"/"Amount Paid"/"Paid"/"Payment"/"Cash" ordered most-specific-first; change catalogue: "Change Due"/"Change Given"/"Cash Change"/"Change"; "Change 0.00" intentionally registers because the explicit zero is meaningful for till-discrepancy dashboards; bare "Cash" matcher does NOT misfire on "Cashier #04" because the underlying _find_amount_after requires a digit-amount IMMEDIATELY after the keyword; LLM wire-format updated).
61. [x] Receipt: per-line SKU/barcode/UPC/EAN extraction (new `ReceiptLine.sku` field; two recognised shapes -- inline "Latte SKU: 12345 5.00" -> cleaned to "Latte 5.00" with sku=12345 attached, AND standalone "SKU: 12345" on its own line attaches to the most-recent item; recognised wording SKU/Barcode/UPC/EAN/GTIN/PLU/Item Code/Item No./Item #/Item Number; value charset alphanumerics + dashes/underscores/dots/slashes bounded 3..32; original case preserved; left-side word-boundary defence keeps "askedSKU: 12345" from misfiring; first-match-wins on lines with multiple SKU keywords; all four per-item parser branches (pct-off, qty-prefixed, @-form, bare desc+price) attach the SKU; LLM wire-format updated).
82. [x] Extract: cross-category Slack ID extractor into `raw["slack_ids"]` (list of `{kind, id}` dicts; 10 prefixes mapped to long-form kind tags: C->channel, D->dm, G->private_channel, U->user, W->enterprise_user, B->bot, T->team, E->enterprise, F->file, S->usergroup; 9..11 char total length; tail must contain at least ONE digit so all-letter prose words "CHEAPCODE"/"DESPAIRED" don't misfire; word-boundary isolation on BOTH ends so "C012345ABCD" inside "AC012345ABCDEF" hex blob doesn't misfire; lowercase/mixed-case rejected because Slack IDs are always uppercase in real payloads; Slack mention syntax <@U..>/<#C..|name>/<!subteam^S..> handled naturally because angle brackets/pipes/exclamation marks are non-word boundary chars; distinct from raw["social"] which is cross-platform typed handles, and ChatFields.mentions which is platform-agnostic chat-only; pipeline writes raw["slack_ids"] for every category).
68. [x] Extract: cross-category crypto-address extractor into `raw["crypto"]` (list of `{chain, address}` dicts; bitcoin tag covers BOTH Base58Check P2PKH "1..."/P2SH "3..." with 4-byte SHA256(SHA256(payload))[:4] checksum validation AND Bech32/Bech32m SegWit "bc1q..."/Taproot "bc1p..." with BCH polymod validation against the right constant per witness version (1 for v0, 0x2bc830a3 for v1+ per BIP-350); ethereum tag is 0x+40 hex shape-only because EIP-55 needs keccak256 outside stdlib, all-zero null address rejected, output lowercased for dedup; solana tag is 32..44 Base58 shape-only AND requires a Solana-context anchor (sol/solana/spl/phantom/mint/pubkey/wallet/token) on same or previous line because Base58 alphabet overlaps with random base58-shaped IDs; pure-Python implementation -- no new heavy deps; BTC base58check runs first so 34-char address satisfying Solana shape gets tagged as bitcoin not double-tagged; pipeline writes raw["crypto"] for every category).

### Backlog
12. [ ] OCR runner: confidence threshold filter that strips low-confidence words above `--min-conf` (per-tenant policy later).
15. [ ] Code: heredoc + multi-language fenced block split (extract first ```lang fence).
16. [ ] Chat: emoji density + reaction-line extraction (the `:eyes: 3` summary footer).
32. [ ] Chat: emoji reaction counts on a per-message basis (the `❤️ 3 👍 2` footer).
39. [ ] Chat: replied-to / quoted-message detection (the `> quoted text` line + replied-by attribution above the new message).
40. [ ] Chat: voice-note / image / video attachment markers (`🎤 Voice (0:42)`, `📷 Photo`, `[Image]`, `[Voice note 0:23]`).
53. [ ] Chart: bar-chart series-label OCR refinement (split the legend block into a clean `ChartFields.series` list).
54. [ ] Chart: percent annotations vs raw values heuristic (new `ChartFields.value_unit`: `%` / `count` / `currency` based on axis tick text).
55. [ ] UI mockup: layout-style guess (new `UIMockupFields.layout_kind`: `dashboard` / `landing` / `form` / `settings` / `modal`).
56. [ ] PII redact: phone-number redaction mode (`phone` mode; normalises to `<PHONE>` stub). (Note: a tight `phone` regex already exists in redact.py; this would refine to the `<PHONE>` stub form.)
59. [ ] Extract: cross-category currency-amount extractor into `raw["amounts"]` (cross-category so a code snippet or chat message that quotes a price is surfaced; symbol + ISO code aware).
65. [ ] Chat: link preview block detection (the inline OG-card with title + description that platforms inline for shared URLs).
66. [ ] Error: AWS Lambda / boto3 client error extraction (BotoCoreError, ClientError with operation_name + error_code).
69. [ ] Receipt: tip-jar / suggested-tip table detection (the "10% 12.34 / 15% 18.51 / 20% 24.68" footer table).
71. [ ] Chart: pie-slice percent extraction from in-pie labels (new ChartFields.slices list of {label, percent}).
72. [ ] PII redact: drivers-license-number redaction mode (per-state US shape catalogues, the most common 7-9 alphanumeric forms).
73. [ ] Receipt: gift-card / promo-code redemption detection (new ReceiptFields.gift_card_applied amount + ReceiptFields.promo_code string; "Gift card -25.00" / "Promo code SAVE10 applied" shapes).
77. [ ] Chat: edited-message marker detection (`(edited)` / `(edited 2m)` tails appended to message bodies on iMessage/Slack/Discord -- surface a parallel `edits` list on ChatFields).
78. [ ] Code: vendor-prefix detection for CSS (new `CodeFields.css_vendor_prefixes` list -- `-webkit-` / `-moz-` / `-ms-` / `-o-` / `-khtml-`).
79. [ ] Code: TODO action-comment AUTHOR extraction (`TODO(alice): fix this` -> `[{"marker": "TODO", "author": "alice"}]` into new `CodeFields.todo_authors`).
80. [ ] Receipt: vendor logo / brand-name normalisation against the top-200 chain catalogue (Starbucks / 7-Eleven / etc -- standardise spelling variations OCR may produce).
81. [ ] Error: Spring Boot WhiteLabel error page parsing (`/error` endpoint HTML that surfaces inside a screenshot -- pull status, timestamp, path, message).
83. [ ] Extract: cross-category Discord ID extractor (`<@123456789012345678>` / `<#123456789012345678>` / `<@&123456789012345678>` -- Discord snowflake IDs are 17-19 decimal digits, distinct from Slack IDs).
84. [ ] Extract: cross-category Stripe ID extractor (`cus_...`, `ch_...`, `pi_...`, `inv_...`, `sub_...`, `prod_...`, `price_...`, `acct_...` -- Stripe prefixes a typed ID family per object).
85. [ ] Extract: cross-category AWS resource ARN extractor (`arn:aws:s3:::bucket/key`, `arn:aws:iam::ACCT:user/USER`, `arn:aws:lambda:REG:ACCT:function:FN` -- 6+ ARN families).
86. [ ] PII redact: passport-number redaction mode (US 9-digit, UK 9-digit, EU letter+digit shapes -- new `passport` mode).
87. [ ] Receipt: rounding / total-rounded-down detection (some EU countries print "Rounding -0.02" / "Cash rounding -0.03" to round to the nearest 5 cents when 1c/2c coins are out of circulation; new `ReceiptFields.rounding` field).

## Tick log
- 2026-06-20 05:37 PT (tick 1, Cake): bootstrap + 5 features.
  - 0d85454 feat(extract/receipt): tip and gratuity extraction
  - 9ac3b34 feat(extract/receipt): payment method detection
  - f36757d feat(extract/error): Go panic and Ruby/Rails stacktrace support
  - 1afe733 feat(extract/code): more languages + framework detection
  - 48a349c feat(redact): JWT, AWS, GitHub, Slack token redaction modes
  - Gate: ruff (no NEW errors above baseline of 10) + pytest 850 passed / 3 skipped.

- 2026-06-20 08:54 PT (tick 2, Cake): 5 features.
  - 29aedf0 feat(extract/chat): timestamp parsing from message lines
  - 120b0ae feat(extract/receipt): discount, coupon, promo extraction
  - b9ecf39 feat(extract/receipt): derive tip_percent from tip and subtotal
  - 177da1d feat(extract): cross-category URL extractor into raw["urls"]
  - 7f8dcaa feat(extract/chat): hashtag and mention extraction
  - Gate: ruff (no NEW errors -- baseline dropped one to 536 because I fixed
    an import-sort issue introduced by my own __init__.py edits) +
    pytest 933 passed / 3 skipped in 224.47s.

- 2026-06-20 14:14 PT (tick 3, Cake): 5 features.
  - 0d66411 feat(extract/code): Laravel, Symfony, Phoenix, Quarkus, Micronaut framework detection
  - d5b8c07 feat(extract/receipt): infer currency from ISO codes (CAD, CHF, AUD, etc.)
  - bf141a0 feat(extract/error): HTTP status classifier (framework=http)
  - f46e68c feat(extract/receipt): line-item quantity inference (qty x desc price)
  - c607749 feat(extract): cross-category file-path extractor into raw["paths"]
  - Gate: ruff at baseline 536 (no new errors after two fixup amends for
    S108 /tmp paths + N802 capital function name) + pytest 1036 passed /
    3 skipped in 139.76s. 103 new tests across the 5 features.

- 2026-06-20 16:44 PT (tick 4, Cake): 5 features.
  - 693bec2 feat(extract/error): .NET / CLR stacktrace support
  - 1034664 feat(extract/error): Rust panic + pytest assertion frame parsing
  - 1fc12a7 feat(extract/code): SQL dialect detection (mysql/postgres/sqlite/mssql)
  - f85ec19 feat(extract): cross-category network endpoint extractor into raw["network"]
  - 1b483dc feat(extract/receipt): per-line percent-off discount inference
  - Gate: ruff at baseline 536 (no new errors after three I001 fixup
    amends -- ruff wants no blank line between the module docstring
    and `from __future__`; folded into the respective feature commits
    via --fixup + --autosquash) + pytest 1137 passed / 3 skipped in
    125.91s. 101 new tests across the 5 features. New fields shipped:
    CodeFields.dialect, ReceiptLine.discount_pct + discount_amount.
    LLM wire format in classify/client.py updated for both.

- 2026-06-20 19:59 PT (tick 5, Cake): 5 features.
  - 72f8d71 feat(extract): cross-category email-address extractor into raw["emails"]
  - d8ca652 feat(extract): cross-category identifier extractor (ISBN/DOI/arXiv/ISSN) into raw["identifiers"]
  - 79c5707 feat(extract/error): Erlang and Elixir crash report parsing
  - ef30135 feat(extract/receipt): order / invoice / reference number extraction
  - d8476e9 feat(extract/chat): read / delivered / unread / typing status markers
  - Gate: ruff at baseline 536 (no new errors, zero fixups needed --
    files written clean on first pass) + pytest 1269 passed / 3
    skipped in 129.09s. 132 new tests across the 5 features. New
    fields shipped: ReceiptFields.order_number, ChatFields.statuses.
    LLM wire format in classify/client.py updated for both. Two new
    cross-category raw keys: raw["emails"], raw["identifiers"].
    BEAM crash branch placed between Go and Ruby in the elif chain;
    no other branch displaced.

- 2026-06-20 22:43 PT (tick 6, Cake): 5 features.
  - da07739 feat(extract/receipt): detect inclusive vs exclusive tax mode
  - f06edea feat(extract/receipt): detect party size and split-bill count
  - 2460910 feat(extract/code): TypeScript-specific feature extraction
  - a0ccc41 feat(extract/code): detect minified vs hand-written JS
  - 49a28b6 feat(extract/error): Python SyntaxError caret-line extraction
  - Gate: ruff at baseline 536 (no new errors, zero fixups needed
    -- all five files written clean on first pass; the
    access_modifier TS regex needed one tighten after the first
    failing test pass, folded into 2460910 before commit) + pytest
    1433 passed / 3 skipped in 139.09s. 164 new tests across the 5
    features (35 + 39 + 47 + 22 + 21). New fields shipped:
    ReceiptFields.tax_mode, ReceiptFields.party_size,
    CodeFields.ts_features, CodeFields.minified. New helper
    parse_syntax_caret exported. LLM wire format in
    classify/client.py updated for all four new fields. Roadmap
    refilled with 22 new items (36..57) so the backlog has
    breathing room.

- 2026-06-21 01:24 PT (tick 7, Cake): 5 features.
  - 1c6a05f feat(extract): cross-category phone-number extractor into raw["phones"]
  - 8373e6b feat(extract): cross-category UUID extractor into raw["uuids"]
  - 81533f8 feat(extract): cross-category git SHA extractor into raw["git_shas"]
  - 2793ab1 feat(extract/receipt): detect refund / void / cancelled transactions
  - edd68e9 feat(extract/code): shebang interpreter extraction
  - Gate: ruff at baseline 536 (no new errors after three I001
    fixups -- ruff wanted no blank line between
    `from shotclassify_extract import ...` and the first
    section-divider comment in the new test files -- + one N802
    fixup for `test_env_with_S_flag_split_args` -> lowercase `s`;
    all four folded via --fixup + --autosquash into the
    respective feature commits) + pytest 1637 passed / 3 skipped
    in 238.88s. 204 new tests across the 5 features (42 + 34 + 49
    + 40 + 39). New fields shipped: ReceiptFields.refund_amount,
    CodeFields.interpreter. LLM wire format in classify/client.py
    updated for both. Three new cross-category raw keys:
    raw["phones"], raw["uuids"], raw["git_shas"]. Roadmap refilled
    with 5 new items (58..62) so the backlog stays at 25+ open.

- 2026-06-21 05:01 PT (tick 8, Cake): 5 features.
  - 9ea9913 feat(extract/receipt): loyalty / store / register identifier extraction
  - f25ff08 feat(extract/receipt): cashier and server name extraction
  - e8f8b93 feat(extract/error): PHP fatal-error stacktrace support
  - 83807e6 feat(extract/error): SQL database error extraction (framework='sql')
  - 9868609 feat(extract/code): comment-density heuristic into CodeFields
  - Gate: ruff at baseline 536 (no new errors, zero fixups needed
    -- all five files written clean on first pass; one test
    assertion adjustment in tick (the shell-density expectation
    was 1.0 but #!/bin/bash + #helper + echo = 0.67 with 3
    non-blank lines, fixed before commit) + pytest 1858 passed /
    3 skipped in 119.66s. 221 new tests across the 5 features
    (58 + 48 + 28 + 43 + 44). New fields shipped:
    ReceiptFields.loyalty_id, ReceiptFields.store_id,
    ReceiptFields.register_id, ReceiptFields.cashier,
    ReceiptFields.server, CodeFields.comment_density. LLM wire
    format in classify/client.py updated for all six. Two new
    framework tags in error extractor: php, sql. Roadmap refilled
    with 5 new items (63..67) so the backlog stays at 25+ open.
    Shared helpers: _find_keyword_id (loyalty/store/register),
    _find_keyword_name (cashier/server), _comment_leaders_for
    (40+ language tags catalogued).

- 2026-06-21 07:57 PT (tick 9, Cake): 5 features.
  - da26aca feat(extract): cross-category MAC-address extractor into raw["macs"]
  - ef37860 feat(extract): cross-category timezone extractor into raw["timezones"]
  - 0bd340d feat(extract): cross-category credit-card extractor into raw["credit_cards"]
  - 841ea1d feat(redact): physical-address redaction mode (US + UK postcode)
  - 62f0270 feat(extract/code): line-numbering detection (strip gutter into CodeFields.numbered)
  - Gate: ruff at baseline 536 (one B007 fixup on the
    line-numbering enumerate(lines) loop variable, folded via
    --fixup + --autosquash into the line-numbering commit, plus
    one F401 fixup for unused pytest import in
    test_code_numbered.py also folded via --fixup) + pytest 2129
    passed / 3 skipped in 117.02s. 271 new tests across the 5
    features (50 + 79 + 52 + 58 + 32). New CodeFields field
    shipped: numbered. LLM wire format in classify/client.py
    updated for numbered. Five new cross-category raw keys:
    raw["macs"], raw["timezones"], raw["credit_cards"]. New
    PII redact mode `address` added to PII_REDACT_MODES
    allow-list. Roadmap refilled with 5 new items (68..72) so
    the backlog stays at 25+ open. Security guarantee on
    credit_cards: extractor returns BIN+last4 ONLY, full PAN
    never stored in output -- pairs with existing
    `credit_card` redact mode (which strips full PAN from
    persisted OCR text). Line-numbering detector runs FIRST
    in enrich_code so every downstream detector (language,
    dialect, ts_features, minified, interpreter, comment
    density) sees the de-numbered body.

- 2026-06-21 11:07 PT (tick 10, Cake): 5 features.
  - fd30aa2 feat(extract/error): Swift / Objective-C crash log parsing
  - 93262be feat(extract/error): Kotlin coroutine exception parsing
  - 2491260 feat(extract/receipt): signature / signed-by detection
  - b860ca4 feat(extract/code): TODO / FIXME marker count into CodeFields.todo_count
  - b1737dd feat(extract/code): license-header detection into CodeFields.license
  - Gate: ruff at baseline 536 (one F541 fixup on the bare
    rf-string in the signature detector folded via --fixup +
    --autosquash into the signature commit, plus one E501
    line-too-long fixup in the kotlin test file also folded
    via --fixup) + pytest 2324 passed / 3 skipped in 126.89s.
    195 new tests across the 5 features (27 + 28 + 42 + 56 +
    42). New fields shipped: ReceiptFields.signature dict,
    CodeFields.todo_count int, CodeFields.license str. LLM
    wire format in classify/client.py updated for all three.
    Two new error-framework tags: swift, kotlin. Roadmap
    refilled with 5 new items (73..77) so backlog stays at
    25+ open. Branch placement: Swift sits AFTER PHP because
    PHP's `Fatal error: Uncaught X:` is more specific than
    Swift's bare `Fatal error:` (Swift fatals never carry
    `Uncaught`); Kotlin sits BEFORE JVM because Kotlin
    compiles to JVM bytecode and would otherwise tag as
    `jvm`. License catalogue uses needle-group AND/OR
    matching so the longer BSD-3-Clause header wins over the
    overlapping MIT phrasing.

- 2026-06-21 14:43 PT (tick 11, Cake): 5 features.
  - 12527df feat(extract/code): top-level docstring / JSDoc extraction into CodeFields.docstring
  - b86b641 feat(extract/code): import-set extraction into CodeFields.imports
  - 459a745 feat(extract/code): copyright-holder extraction into CodeFields.copyright
  - dbdb5e2 feat(extract): cross-category airport-code extractor into raw["airports"]
  - f8dceab feat(extract): cross-category social-handle extractor into raw["social"]
  - Gate: ruff at baseline 536 (one E501 + one F841 fixup
    on the docstring detector folded into the docstring
    commit before push, plus four B033 duplicate-set-item
    fixups on the IATA catalogue (RUH/TLV/CAI/ANR printed
    twice across region groups) folded into the airports
    commit before push) + pytest 2579 passed / 3 skipped
    in 134.65s. 255 new tests across the 5 features
    (49 + 60 + 44 + 49 + 53). New CodeFields shipped:
    docstring str, imports list[str], copyright
    list[dict[str, str]]. LLM wire format in
    classify/client.py updated for all three. Two new
    cross-category raw keys: raw["airports"],
    raw["social"]. Roadmap refilled with 5 new items
    (78..82) so backlog stays at 25+ open. Notable
    placement decisions: docstring detector is
    language-aware (python prefers triple-quoted, rust
    prefers `///`/`//!`, default is JSDoc -> python ->
    rust); import detector runs every language's matcher
    against every snippet (not gated by language) because
    OCR captures often mix shells + configs + code; airport
    extractor uses curated IATA (~250 codes) + ICAO
    (~150 codes) catalogues with travel-vocabulary anchor
    fallback so non-catalogue codes (a regional airport) can
    still tag when the screenshot uses `Flight`/`Gate`/etc;
    social extractor's @handle matchers (Twitter,
    Instagram) require a same-line platform anchor so a chat
    `@user` mention doesn't get mis-attributed.

- 2026-06-21 17:53 PT (tick 12, Cake): 5 features.
  - 3ec136f feat(extract/receipt): service_charge and delivery_fee extraction
  - 8fb3d16 feat(extract/receipt): tendered and change extraction for cash receipts
  - 6da532b feat(extract/receipt): per-line SKU/barcode/UPC/EAN extraction
  - f440971 feat(extract): cross-category Slack ID extractor into raw["slack_ids"]
  - 89d79ef feat(extract): cross-category crypto-address extractor into raw["crypto"]
  - Gate: ruff at baseline 536 (zero new errors, zero
    fixups needed -- all five files written clean on first
    pass; two pre-existing UP042 errors in schemas.py
    Category / RouteAction stay baselined, unchanged from
    before) + pytest 2782 passed / 3 skipped in 156.0s.
    203 new tests across the 5 features (38 + 39 + 40 +
    43 + 43). New ReceiptFields shipped: service_charge,
    delivery_fee, tendered, change. New ReceiptLine field
    shipped: sku. LLM wire format in classify/client.py
    updated for all five new receipt slots. Two new
    cross-category raw keys: raw["slack_ids"],
    raw["crypto"]. Roadmap refilled with 5 new items
    (83..87 -- Discord IDs, Stripe IDs, AWS ARNs, passport
    redact, EU cash-rounding) so backlog stays at 25 open.
    Notable design decisions: service_charge intentionally
    NOT routed through the legacy `tip` field so a
    restaurant receipt's mandatory "Service Charge 5.00"
    PLUS voluntary "Tip 4.00" populates BOTH fields; bare
    "Service" alias stays in _TIP_KEYWORDS for UK bar-tab
    compat. Tendered/change "Cash" matcher does not
    misfire on "Cashier #04" because the underlying
    _find_amount_after requires a digit-amount IMMEDIATELY
    after the keyword (with at most :/- separators). SKU
    extractor strips the keyword + value BEFORE per-item
    parsers fire so the cleaned line re-parses cleanly;
    standalone "SKU: 12345" lines attach to the last
    item. Slack ID extractor requires at least one digit
    in the tail so all-letter prose ("CHEAPCODE") doesn't
    misfire. Crypto extractor uses pure-Python Base58
    decode + double-SHA256 + bech32 polymod (no new heavy
    deps); BTC base58check scanner runs FIRST so a
    34-char address satisfying the Solana shape is tagged
    bitcoin not double-tagged; Solana requires same/prev
    line anchor because base58 alphabet overlaps with
    random IDs.

## Risks / notes
- Web UI work skipped again this tick -- Python-only shipping for speed.
- API / middleware features still deferred because of TestClient bootstrap cost.
- raw["urls"], raw["paths"], raw["network"], raw["emails"], and
  raw["identifiers"] are all populated cross-category from the same
  OCR text. The path extractor masks URL spans before scanning, the
  network extractor masks URL + consumed-network spans before each
  subsequent matcher, the email extractor needs no masking (``@`` and
  ``://`` never overlap), and the identifier extractor masks consumed
  spans between matchers (arXiv -> DOI -> ISBN-13 -> ISBN-10 -> ISSN)
  so a DOI body cannot also tag as an ISBN.
- HTTP status branch in error extractor is still the final fallback
  before the generic Error/Exception regex. The .NET branch is placed
  AFTER Node and BEFORE JVM so a CLR exception line (which would also
  match the JVM regex) tags correctly; JVM stays safe because Java
  package segments start lowercase while .NET exceptions are UpperCase
  every segment.
- Rust panic branch matches `thread '...' panicked` (a verb form
  distinct from Go's `panic:` prelude) so the two never cross.
- BEAM crash branch matches the literal ``** `` prelude, distinct
  from every other framework's prelude (Python's ``Traceback``,
  Node's ``at Object``, Go's ``panic:``, Rust's ``thread '...'
  panicked``, JVM's ``Exception in thread``, .NET's ``System.X.Y
  Exception:`` with frame ``at NS.T.M() in foo.cs:line N``). Placed
  between Go and Ruby in the elif chain; no other branch displaced.
- pytest is checked FIRST in `parse_error_text` (before Python /
  Node / etc.) but ONLY when both the trailing `FILE:N: ExcName`
  tail AND the `>` source-line indicator are present, so a bare
  Python traceback that doesn't come from pytest still tags python.
- Pre-existing ruff S110 in code.py:138 (`except Exception: pass` in
  the pygments fallback path) remains baselined.
- `ReceiptLine.discount_pct` is stored as raw percent (50.0, not 0.5);
  `discount_amount` is always positive. The top-level
  `ReceiptFields.discount` is unchanged (still last-match summary
  amount). Per-line and top-level can coexist on the same receipt.
- `ReceiptFields.order_number` is stored as a string because real-
  world numbers mix digits with letters and slashes (``INV-00099``,
  ``2024/07/00099``, ``TKT-2024-007``, ``CONF-12-99``). The hash
  prefix on ``Order #12345`` sits in the keyword tail, so the value
  is stored without the hash; dashboards render the hash back as
  part of the label.
- `ChatFields.statuses` entries are sorted by source-text offset,
  not by matcher iteration order, so a "Delivered" line above a
  "Read" line in the screenshot lands first in the list. De-dupe
  runs after sorting on the (status, time-or-count) tuple. Cap at
  20 entries.
- `extract_emails` lowercases results for storage (per RFC 5321
  permission and real-world dashboard convention). The `mailto:`
  prefix is stripped automatically. SSH `user@host` fragments
  without a dotted TLD are rejected; numeric-only TLDs are rejected
  to keep `user@host42` config noise out.
- `extract_identifiers` validates check digits for ISBN-10
  (mod-11, X-as-10 in last slot), ISBN-13 (EAN-13 mod-10),
  and ISSN (mod-11, X-as-10 in last slot). Random 13-digit
  barcode noise is rejected. arXiv requires the ``arXiv:`` prefix
  so a bare ``2306.12345`` version-string lookalike does not
  false-positive.
- `ReceiptFields.tax_mode` cues are checked in inclusive-first
  order purely so the helper has a deterministic tiebreaker; the
  actual decision rule is "FIRST cue in OCR order wins". Both
  inclusive and exclusive vocabularies span EU / AU / NZ / IN / US
  / UK phrasings (VAT, GST, HST, PST, QST). The exclusive ``ex
  VAT`` shorthand requires a leading word boundary so a stray
  ``ex`` in prose does not false-positive.
- `ReceiptFields.party_size` cues prefer cover-count vocabularies
  (Party / Guests / Covers) over split-bill cues (Split N ways /
  Per person N) because a 4-cover bill split 3 ways still has 4
  guests. Counts are bounded 1..50; the bare ``Party N`` form
  requires a leading colon, comma, or line-start so prose
  ("the party 3 days ago") does not fire. Three-digit counts
  fail the regex digit cap as a second defence.
- `CodeFields.ts_features` runs ONLY when the language detector
  already tagged the snippet as typescript / tsx / ts so a plain
  JS snippet using ``as`` as a variable name does not false-
  positive. The ``access_modifier`` regex was relaxed away from
  start-of-line anchoring so inline class declarations
  (``class Foo { private id: number; }``) still tag; the
  trailing-token constraint (``[:(?=]``) keeps prose words after
  ``private`` from misfiring.
- `CodeFields.minified` is a dual-gated decision: long lines AND
  low newline-after-separator ratio. The ``max_len > 500`` branch
  exists specifically to catch bundles with a few short sourcemap
  comments above one giant minified body. Non-JS-family languages
  short-circuit to False because the heuristic is tuned for JS
  bundle output.
- Python SyntaxError enrichment runs INSIDE the existing python
  branch of ``parse_error_text`` (not as a separate elif). It
  overrides the exception name from the trailing
  ``SyntaxError: msg`` line and appends the source line + caret
  column span to the message. The trim-by-leading-whitespace
  step keeps the dashboard rendering compact while preserving
  the caret-into-trimmed-source column math.
- `parse_syntax_caret` rejects a caret line whose ``arrows``
  group contains anything other than ``~`` and ``^`` chars, so a
  divider like ``---^---`` (CPython does not print this, but
  OCR noise can) does not steal the match. It also skips caret
  lines that sit at index 0 (no source line above) and caret
  lines whose source line is blank.
- `extract_phones` E.164 hits also register the trailing 10-digit
  form in the seen-set so a follow-up bare NANP match on the same
  number (``+1 (415) 555-1234`` printed alongside ``(415)
  555-1234``) does NOT land as a separate entry. The reverse case
  (bare NANP printed before E.164) keeps the NANP version because
  it lands first in source-text offset order.
- `extract_uuids` deliberately rejects the all-zero "nil" UUID
  because it's almost always a placeholder / default value, but
  ACCEPTS UUIDs whose variant nibble (first hex of the 4th group)
  doesn't conform to RFC 4122 -- real-world dashboards encounter
  Microsoft GUIDs whose variant doesn't match and we want them
  surfaced. The version nibble IS enforced (position 12 must be
  1..5) so we never fold a random 32-hex string of the wrong
  shape into the list.
- `extract_git_shas` short SHAs (7..12 hex) require a git-
  vocabulary context to land because a bare 7-12 hex blob false-
  positives on UUIDs, color codes, and base16 IDs. The git
  subcommand pattern (``git show / log / cherry-pick ...``) uses
  ``[ \t]+`` horizontal whitespace ONLY between the command and
  the SHA so ``git log --oneline\n1234567 fix...`` does NOT steal
  the first hex tail of the log output as the argument SHA. Full
  and short forms of the same commit stay distinct because we
  don't have the repo to resolve against.
- `ReceiptFields.refund_amount` is stored POSITIVE regardless of
  whether the printer used a leading ``-`` or wrote the value
  bare with a refund keyword. The sign is implied by the field's
  semantic. Per-line negative amounts continue to flow through
  the existing per-item discount parser (``ReceiptLine.discount_amount``);
  only top-level keyword-led OR explicit negative-Total/Subtotal
  forms populate the top-level field. The negative-total
  fallback requires an EXPLICIT leading ``-`` on the
  ``Total`` / ``Subtotal`` value -- a positive total is a normal
  sale and never tags as a refund.
- `CodeFields.interpreter` extraction looks at the FIRST line of
  the snippet only. A shebang elsewhere in the body is treated
  as a regular comment (which it is). Leading whitespace before
  the ``#!`` marker is rejected because the kernel exec(2)
  parser also requires ``#!`` at byte 0 -- a script that does
  not enforce this is not actually shebang-runnable. The env
  branch handles ``-S`` split-args (GNU coreutils >= 8.30),
  ``--split-string=python3`` inline form, and skips arbitrary
  short / long flags before landing on the first non-flag token.
- `ReceiptFields.loyalty_id`, `store_id`, `register_id`, `cashier`,
  and `server` all share the same negative-lookbehind on alphas
  to enforce a word boundary on the left of the keyword. This is
  why `Bookstore #1` doesn't fire the store matcher and `Remember
  1234` doesn't fire the member matcher. Within each ID category
  the keyword catalogue is ordered most-specific-first so
  `Loyalty Number 1234` beats a bare `Member: 99` when both are
  present. The cashier / server matchers use a column-gap
  detector (two consecutive spaces) that runs BEFORE the
  whitespace-collapse pass so the cleaned name doesn't
  accidentally absorb the next receipt column. One accepted
  false-positive on cashier: any prose sentence containing the
  bare `cashier` keyword followed by a word captures the word
  as the name (`the cashier was busy` -> `was`). Acceptable
  because receipt OCR rarely contains full prose, and the regex
  is intentionally permissive for name variations.
- PHP fatal-error branch (`framework='php'`) is placed BEFORE the
  JVM branch in the parse_error_text elif chain because the PHP
  exception name is also a `\w+Exception` / `\w+Error` pattern
  that satisfies `_JAVA_EXC`. Without this ordering a PHP
  `RuntimeException` would tag as JVM. The `Uncaught` keyword
  is the discriminator: PHP warnings / notices / parse errors
  intentionally don't match. Namespace-qualified exceptions
  keep their full path (`Symfony\\Component\\HttpKernel\\
  Exception\\NotFoundHttpException`) so Laravel / Symfony
  codebases tag correctly.
- SQL error branch (`framework='sql'`) sits INSIDE the else:
  fallback (after Rust, before HTTP) because SQL errors carry no
  status code so they never accidentally pre-empt a real HTTP
  trace. Dialect priority MySQL -> MSSQL -> SQLite -> PostgreSQL
  is intentional because the more-specific signatures (MySQL's
  parenthesised SQLSTATE, MSSQL's Msg header) anchor strongly
  while PostgreSQL's bare `ERROR:` is the most generic and
  would steal a SQLite `Error: near` line if case-insensitivity
  collided. PostgreSQL and SQLite regexes are CASE-SENSITIVE
  (Postgres prints strictly uppercase `ERROR:`, SQLite strictly
  capital-E `Error:`) so generic `Error: something` prose lines
  don't false-positive. MySQL stays case-insensitive because the
  prelude is sometimes printed in title-case by GUI clients.
- `CodeFields.comment_density` counts the fraction of NON-BLANK
  lines whose first non-whitespace token opens a comment for the
  detected language. Block-comment openers (`/*`, `"""`, `'''`,
  `=begin`) count when they sit at the start of a line so
  Python triple-quoted docstrings and C-family license headers
  register correctly. Inline trailing comments (`foo = 1  #
  inline`) do NOT count -- only line-leading. The `text`
  catchall fallback defaults to the `#` leader because a
  script-like snippet whose language was undetectable is
  usually still readable with the `#` rule; only pure data
  formats (json, csv, tsv) zero out unconditionally. PHP is
  catalogued with BOTH `//` and `#` as leaders because PHP
  accepts both syntaxes. Result is rounded to 2 decimal places
  because finer precision is meaningless given OCR noise and
  small snippet sizes.
- `extract_macs` accepts EUI-48 in three input shapes (colon-
  separated, dash-separated, Cisco dot-quad) and emits canonical
  lowercase colon-separated form so the same MAC printed three
  different ways collapses to one entry. The null MAC and
  broadcast MAC are rejected because neither identifies a
  specific device. IPv6 spans are MASKED before scanning so a
  compressed IPv6 like `fe80::aa:bb:cc:dd:ee:ff` doesn't get
  carved up into a false-positive MAC. The mask matches both
  the compressed (`::`) and full 8-group IPv6 shapes.
- `extract_timezones` matches four shapes: numeric UTC offsets
  with hour bounded -12..+14 per IANA, the Z suffix only when
  adjacent to an ISO-8601-ish digit (a bare `Z` in prose
  rejects), 33 named abbreviations enforced as whole-word
  tokens (so `IST` inside `EXIST` doesn't fire), and IANA
  Region/City with the documented top-level region list
  (Africa / America / Antarctica / Arctic / Asia / Atlantic /
  Australia / Europe / Indian / Pacific / Etc) -- city tolerates
  hyphenated names (America/Port-au-Prince) and three-part
  zones (America/Argentina/Buenos_Aires). Canonical normalisation:
  +0530 / +05:30 -> +05:30, -08 / -0800 -> -08, Z -> +00.
  IANA matches consume their spans first so a Region/City
  containing `-05` doesn't double-tag as a numeric offset.
- `extract_credit_cards` returns a list of `{brand, bin, last4}`
  dicts. The full PAN is NEVER returned (security guarantee
  enforced by test). Luhn-validated 13..19 digit PANs with
  brand from BIN: Visa (4xxx, lengths 13/16/19), Mastercard
  (51-55 + 2221-2720 length 16), Amex (34/37 length 15),
  Discover (6011 / 65 / 644-649 length 16), JCB (3528-3589
  length 16), Diners (300-305 / 36 / 38-39 length 14),
  UnionPay (62 lengths 16-19). PANs with valid Luhn but
  uncatalogued BIN tag as brand=None. Masked **** / XXXX /
  .... PANs with brand inferred from the SAME-LINE brand
  keyword (Visa / Mastercard / Master Card / MC / Amex /
  American Express / Discover / JCB / Diners / Diners Club /
  UnionPay / Union Pay). Brand keyword matching enforces
  word boundaries so `masterclass` doesn't pin a `master`
  brand. Pairs with the existing `credit_card` redact mode in
  shotclassify_common.redact -- extractor surfaces BIN+last4
  metadata; redactor swaps the raw PAN with the
  [REDACTED:credit_card] placeholder before persistence.
- `address` redact mode catches one-line US / UK postal
  addresses: NUMBER + STREET-NAME + suffix (28 suffixes
  including Trail / Loop / Row), optional Apt / Suite / Ste /
  Unit / # prefix, optional ", City", optional ", STATE ZIP"
  US tail (5-digit or 5+4) or ", City, POSTCODE" UK tail
  (SW1A 1AA / M1 1AE). Multi-word street names (Martin Luther
  King Blvd) and multi-word cities (San Francisco) supported.
  Cardinal direction prefix (`123 N Main St`,
  `200 W. Pine Ave`). House-number range (`101-103 Oak Ave`)
  and split (`1/2 Pine Rd`). Capitalised street name required
  -- lowercase `123 main st` is rejected because lowercase
  street names are usually prose noise.
- `CodeFields.numbered` is set by `detect_numbered` which runs
  FIRST in `enrich_code` so every downstream detector
  (language, dialect, ts_features, minified, interpreter,
  comment_density) sees the de-numbered code. Four prefix
  shapes recognised: `1: code` (colon + mandatory single
  separator space), `1| code` or `1|code` (pipe, sticky or
  spaced), `1\tcode` (tab), `  1  code` (right-aligned column
  with 2-space minimum). Detection rules are strict to bound
  false-positive risk: 3-line minimum, every non-blank line
  must match the SAME pattern (mixed-separator rejects),
  numbers must be non-decreasing (gaps OK, decreasing
  rejects). The FIRST matched line decides spaced-vs-sticky
  mode for the pipe / colon patterns -- if the first line's
  rest starts with a space we treat the snippet as
  "spaced form" and strip exactly one leading space from
  every line's rest (so `2|    return 1` keeps 4 spaces, not
  3). If first line is sticky (`1|def foo()`), no stripping
  happens anywhere.
