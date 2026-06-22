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

## Roadmap (102 features tracked, 80 complete)

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

### Done in tick 13 (5 features)
84. [x] Extract: cross-category Stripe ID extractor into `raw["stripe_ids"]` (list of `{kind, id}` dicts; 24 typed prefixes mapped to long-form kind tags: cus->customer, ch->charge, pi->payment_intent, inv->invoice, sub->subscription, prod->product, price->price, acct->account, re->refund, pm->payment_method, seti->setup_intent, cs->checkout_session, tr->transfer, po->payout, txn->balance_transaction, file->file, coupon->coupon, promo->promotion_code, ii->invoice_item, cn->credit_note, txr->tax_rate, si->subscription_item, src->source, tok->token; lowercase prefix + underscore + optional test_ infix + 14..40 alphanumeric chars; prefixes tried longest-first so seti_ wins over si_ and promo_ wins over pm_; word-boundary on both ends; test-mode IDs (cus_test_xyz) recognised explicitly; distinct from raw["slack_ids"] which is letter-prefixed alphanumeric).
85. [x] Extract: cross-category AWS resource ARN extractor into `raw["arns"]` (list of `{service, region, account, resource, arn}` dicts; standard 6-segment colon-separated form arn:partition:service:region:account:resource; three partitions accepted: aws/aws-cn/aws-us-gov; region recognises us-east-1 / eu-west-2 / ap-southeast-2 + cn-north-1 + us-gov-west-1 forms or empty; account recognises 12-digit ID OR literal "aws" for AWS-managed IAM policies (arn:aws:iam::aws:policy/...) OR empty for S3 bucket ARNs; resource captured greedily across additional colons and slashes so arn:aws:lambda:us-east-1:123:function:foo:1 preserves version-qualification, CloudWatch log-group multi-colon forms work, DynamoDB table/T/index/I works; trailing punctuation (./,)/]}'") stripped; case-insensitive throughout; pipeline writes raw["arns"] for every category).
83. [x] Extract: cross-category Discord snowflake ID extractor into `raw["discord_ids"]` (list of `{kind, id}` dicts; recognises typed mention forms <@id>/<@!id>/<#id>/<@&id>, jump URLs discord.com/channels/G/C/M with legacy discordapp.com domain, webhook URLs with explicit token-drop security guarantee, bare 17..19 digit snowflakes with Discord-context anchor on same or previous line (anchor catalogue: discord/snowflake/guild/guild_id/channel_id/user_id/role_id/webhook_id/message_id/author_id/server_id/discord.py/discord.js); bare snowflake matcher REQUIRES anchor because 17..19 decimal digit blobs are too common (UNIX nanosecond timestamps, sequence numbers); pass ordering typed-mentions -> URLs -> anchored-bare with first-seen kind winning on dedupe; distinct from raw["slack_ids"] (letter-prefixed alphanumeric) and raw["stripe_ids"] (typed-prefix + underscore)).
79. [x] Code: author-tagged TODO extraction into `CodeFields.todo_authors` (list of `{marker, author}` dicts; mirrors detect_todo_count's 7 ALL-CAPS markers TODO/FIXME/XXX/HACK/BUG/NOTE/OPTIMIZE; recognises canonical `MARKER(author):` and `MARKER(author)` forms across six comment-leader families (// # /* ; -- default-hash); author handle 1..64 chars supports plain/with-@/with-digits/with-hyphen/with-underscore/with-period/with-email/full-name shapes; trailing ,;:- and leading whitespace stripped; empty-paren rejected; substring rejection (TODOIST not a marker); dedupe intentionally NOT done because the same author may own multiple TODOs and the count should be accurate; pure data formats json/csv/tsv short-circuit to []; cap at 50; LLM wire-format updated).
87. [x] Receipt: cash-rounding adjustment into `ReceiptFields.rounding` (signed float; regulatory adjustment for small-coin scarcity in AU/CA/NZ/NO/SE/CH/HU/IE/NL etc.; recognised wording most-specific-first: "Rounding Adjustment"/"Cash Rounding"/"Cash Discrepancy"/"Rounding"/"Round Down"/"Round Up"; new _find_signed_amount_after helper captures sign correctly because existing _find_amount_after's [:\\-]? separator class would eat the minus; sign captured both before AND after currency symbol (-$0.02 OR $-0.02); comma-decimal style (-0,02) supported; explicit 0.00 intentionally registers because printing the line at all is a useful signal; distinct from discount (marketing) and change (physical bills/coins) and refund (reversed transaction); LLM wire-format updated).


### Done in tick 14 (5 features)
88. [x] Extract: cross-category JWT extractor into `raw["jwts"]` (list of dicts summarising JOSE header alg/typ/kid + standard payload claims iss/sub/aud/exp/iat/nbf/jti; raw header_b64 segment preserved for forensic recovery; security guarantee: FULL TOKEN (header.payload.signature) NEVER stored in output and signature segment discarded entirely; custom payload claims like email/preferred_username intentionally NOT surfaced because tokens carry PII in custom claims; shape rules mirror existing redact regex -- three base64url segments separated by dots, header must start with eyJ, each segment >= 8 chars, word-boundary on both ends; corrupted-header tokens skipped entirely; unparseable-payload tokens still yield header-only entry; string claims capped at 256 chars; float exp/iat that are whole numbers collapse to int; list aud collapses to comma-joined string; capped at 20 entries; pairs with `jwt` redact mode for defence-in-depth).
89. [x] Code: markdown fence-language detection into `CodeFields.fence_language` (lowercased language tag from opening fence; recognised CommonMark+GFM shapes ```LANG / ```LANG title="..." / ```LANG hl_lines=... / ~~~LANG / 4+ backticks-tildes; fence MUST sit at start of line optionally indented 0-3 spaces per CommonMark spec, 4-space indent is indented-code-block not fence; lang token is first whitespace-bounded token after fence run matched as [A-Za-z][\w+#.-]* so info-string titles don't bleed in; first tag wins when multiple fences differ; bare fences skipped; we do NOT canonicalise short forms (js stays js, py stays py) because original tag carries author intent; runs FIRST in enrich_code on pre-strip body so fence markers survive line-number stripping; LLM wire-format updated).
92. [x] Code: feature-flag SDK call detection into `CodeFields.feature_flags` (list of `{vendor, key}` dicts; 8 vendors with canonical SDK shapes: launchdarkly (ldClient.variation / boolVariation / stringVariation / numberVariation / jsonVariation / variation_detail), statsig (Statsig.checkGate / check_gate / getExperiment / getConfig / getLayer + bare-import call), unleash (unleash.isEnabled / is_enabled / client.isEnabled / toggleClient.isEnabled), optimizely (isFeatureEnabled / is_feature_enabled / .activate / .getVariation / .getFeatureVariableString plus snake variants), split (client.getTreatment / get_treatment / splitClient.getTreatment / getTreatmentWithConfig), posthog (isFeatureEnabled / is_feature_enabled / getFeatureFlag / get_feature_flag / getFeatureFlagPayload), flagsmith (hasFeature / has_feature / is_feature_enabled / .getValue + flags.is_feature_enabled prefix), configcat (getValue / get_value / getValueAsync / configCatClient.getValue); flag-key charset [A-Za-z][A-Za-z0-9._-]{0,127} so dashed/dotted/snake_case all parse, spaces and special chars rejected; single OR double quotes accepted; patterns are vendor-specific so a given call site only matches one vendor; deduplicates on (vendor, key) pair; first-seen order; cap 50; distinct from `imports` which is library dependency vs this slot is per-call flag-key reference; LLM wire-format updated).
78. [x] Code: CSS vendor-prefix detection into `CodeFields.css_vendor_prefixes` (5 recognised prefixes: -webkit- / -moz- / -ms- / -o- / -khtml-; entries include leading and trailing hyphen so output is directly usable as property-prefix in CSS rendering; detection matches `-(webkit|moz|ms|o|khtml)-` followed by identifier-start letter so property names AND function calls AND @-keyframe at-rules all qualify; language-gated to CSS-family {css, scss, sass, less, stylus} with content fallback that fires when snippet contains BOTH vendor-prefix candidate AND CSS-like property declaration `property: value;` within 200 chars of candidate so pygments mis-tags get covered while a JS comment that mentions -webkit- with no nearby declaration doesn't false-positive; fallback window intentionally LOCAL not global so a faraway random `color: red;` doesn't trigger; first-seen order; no cap because theoretical max is 5; LLM wire-format updated).
86. [x] PII redact: passport-number mode (`passport` mode added; matcher REQUIRES the word `passport` (case-insensitive) immediately before candidate so bare 9-digit runs on receipts don't misfire; recognised label forms: Passport: / Passport No: / Passport No. / Passport Number: / Passport # / Passport ID: with 0-5 separator chars; accepted candidate shapes US/UK 9-digit + Australia 1-letter+7-digit + Germany 1-letter+8-digit + Canada 2-letter+6-digit + Canada 2-letter+7-digit + Germany legacy 1-letter+8-alphanum + mixed 6-9 alphanumerics; redaction strips ONLY the captured `num` group leaving the `Passport: ` label visible to reader so they know field WAS a passport without number leaking; custom `_sub_passport` substitution handler mirrors the credit_card mode's Luhn-gated pattern; 11+ digit runs that fail trailing word-boundary are LEFT UNCHANGED rather than partially redacted as safety property; added to PII_REDACT_MODES allow-list).


### Done in tick 15 (5 features)
59. [x] Extract: cross-category currency-amount extractor into `raw["amounts"]` (list of `{currency, amount}` dicts; ISO 4217 codes USD/EUR/GBP/JPY/CAD/AUD/CHF/CNY/INR/MXN/BRL/ZAR/SGD/HKD/NZD/SEK/NOK/DKK/KRW/RUB/TRY/PLN/CZK/HUF/THB/IDR/ILS/PHP/MYR/TWD/VND/AED/SAR/QAR/EGP/NGN/RON/ARS/CLP/COP/PEN/UYU/BGN/HRK/ISK + RMB alias->CNY; 4 shapes: symbol-prefix `$12.99`/`€10,50`/`A$5.50`/`HK$10`/`NZ$8`/`US$50`/`S$10`/`R$25`/`₹500`/`₽1,200`/`₩50,000`/`₪80`/`₺25`/`₫10000`/`₱100`/`฿350`/`₴25`/`₸150`/`₵80`; symbol-suffix `12.99$`/`10,50€`/`99£`; ISO-prefix `USD 12.99`; ISO-suffix `12.99 USD`; decimal normalisation handles US `1,234.56` AND EU `1.234,56` AND French `1 234,56` via rightmost-separator-is-decimal heuristic with group-size disambiguation; sign captured but stored positive because refund/change/rounding receipt fields carry signed semantics; ISO codes validated against curated 40-code set so stray three-letter prose words don't false-positive; dedupe on (currency, amount) pair; cap 100).
95. [x] Extract: cross-category postal-code extractor into `raw["postal_codes"]` (list of `{country, code}` dicts; 10 countries with ISO 3166-1 alpha-2 country tags; self-anchored shapes UK postcode `SW1A 1AA` (canonicalised to outward+space+inward), Canadian `K1A 0B1` (first-letter-not-D/F/I/O/Q/U), Japanese `100-0001`, Brazilian CEP `01310-100`, Dutch `1011 AB`; anchored shapes require same-line country/state/city anchor: US ZIP 5 or 5+4 needs 2-letter state from curated 56-set (50 states + DC + 5 territories), German PLZ 5-digit + Deutschland/Germany/PLZ label / 25 major cities, French CP 5-digit + France/CP/16 cities (00xxx rejected because dept 0 doesn't exist), Australian 4-digit + state NSW/VIC/QLD/WA/SA/TAS/ACT/NT or Australia anchor, Indian PIN 6-digit + India/IN/PIN/Pincode/16 major cities; anchored shapes need the anchor because bare digit-runs of those lengths false-positive too easily; dedupe on (country, code) pair; cap 50).
97. [x] Code: regex literal extraction into `CodeFields.regexes` (list of `{flavor, pattern, flags}` dicts; 8 flavors: js (slash-delimited /pattern/flags with division-vs-regex disambiguation via left-context lookbehind for line-start / opener / operator / control keyword + flag set gimsuyd), python (re.compile/match/search/fullmatch/findall/finditer/sub/subn/split with raw-string OR plain string), ruby (%r{}/%r()/%r[]/%r<> paired-delimiter literals + %r/.../%r!...!  / %r@...@ same-delimiter; per-pair patterns so inner character class never prematurely terminates), perl (qr/.../ + qr{}/qr()/qr[]/qr<> with imsxoadlu flag set), go (regexp.MustCompile / regexp.Compile with backtick raw-string OR double-quoted), java (Pattern.compile), rust (Regex::new with r"..." OR r#"..."# OR plain string), c# (new Regex / Regex.Match / Regex.IsMatch / Regex.Matches / Regex.Replace / Regex.Split with @"..." verbatim OR plain string); runs every flavor against every snippet not gated by detected language because OCR captures often mix configs+scripts+code; dedupe on (flavor, pattern, flags) tuple; first-seen order; cap 50; LLM wire-format updated).
77. [x] Chat: edited-message marker detection into `ChatFields.edits` (list of `{sender, text, tail}` dicts; recognised markers (case-insensitive): parenthesised `(edited)` generic/WhatsApp, `(edited 2m)`/`(edited 5h)` Discord, `(edited just now)`/`(edited 12 minutes ago)` Slack, `(edited 2024-01-01)` some clients, `(modified)`/`(updated)` bot variants, bracketed `[edited]` Telegram bots, inline trailing `edited at 12:34` Slack web, `edited 2m ago` inline elapsed form; substring defence on unedited/credited/discredited via space-preceded lookbehind on inline form; end-of-line anchor enforced so mid-line `(edited)` doesn't fire; tail normalisation lowercased + whitespace-collapsed; sender extracted from leading `Sender: text` shape when present; dedupe on (sender, text, tail) triple; cap 30; LLM wire-format updated).
32. [x] Chat: per-message emoji reaction counts into `ChatFields.reactions` (list of `{sender, reactions: [{emoji, count}, ...]}` dicts; Slack shortcode form `:eyes: 3` with shortcode regex `[a-z0-9_+-]{1,40}` (+/- preserved for :+1:/:-1:), Discord inline Unicode emoji + count with emoji range U+1F300..U+1FAFF (faces/gestures/hands/objects) + U+2600..U+27BF BMP miscellaneous symbols + U+FE0F variation selector, iMessage reaction-by lines `❤️ by Alice` (speaker = REACTOR not author), WhatsApp `❤️ 3`; per-line _is_reaction_line heuristic: at least one emoji+count match AND matched chars >= 30% of non-whitespace content so regular prose containing trailing emoji+number doesn't fire; sender attribution to nearest preceding `Sender:` line; iMessage reaction-by overrides current_sender with reactor name; dedupe on (sender, tuple-of-(emoji, count)) key; per-message reactions cap 20; total entries cap 30; LLM wire-format updated).


### Done in tick 16 (5 features)
94. [x] Receipt: tax-jurisdiction breakdown into `ReceiptFields.tax_lines` (list of `{jurisdiction, amount}` dicts; 30+ jurisdiction catalogue covering US state/county/city/local/sales/federal/use tax + multi-word specialty taxes hotel/lodging/tourism/restaurant/resort-fee/liquor/tobacco/service, Canadian HST/PST/GST/QST, EU/UK VAT/Import VAT/EU VAT, Indian CGST/SGST/IGST/UTGST/CESS; longest-first ordering so multi-word forms beat short aliases AND overlap-defence skips shorter matches inside already-recorded longer spans VAT-inside-Import-VAT; bare Tax keyword intentionally OUT of catalogue because top-level tax slot owns it; last-occurrence-per-jurisdiction semantics for echoed summary lines; tax_lines empty for 0 or 1 jurisdiction so dashboards rely on len(tax_lines) > 0 meaning real multi-jurisdiction breakdown; output sorted by source-text offset for top-to-bottom rendering; LLM wire-format updated).
73. [x] Receipt: gift-card / promo-code redemption detection (TWO new ReceiptFields: gift_card_applied float + promo_code string; gift-card catalogue: Gift Card Applied / Gift Card Redeemed / Gift Card / GC Redeemed / GC Applied / Store Credit Applied / Store Credit / Voucher Applied / Voucher Redeemed / Voucher (most-specific-first); always emitted POSITIVE regardless of leading minus on the printer because field semantic implies sign; promo-code catalogue: Discount Code / Coupon Code / Voucher Code / Promo Code / Promotion Code / Rebate Code / Offer Code / Referral Code; bare `Code: X` form fires only when same line carries discount/promo/coupon/voucher/rebate vocab so generic Order Code doesn't false-positive; pure-digit codes longer than 3 digits rejected because almost always order numbers; original case preserved (Shopify uses lowercase, legacy uses uppercase); LLM wire-format updated).
72. [x] PII redact: drivers-license-number redaction mode (new `drivers_license` mode; matcher REQUIRES word DL/license/licence/driver's license/drivers license/lic case-insensitive immediately before candidate so bare 7-12 digit runs don't misfire; recognised labels: DL: / DL # / DL No: / Driver's License: / Drivers License: / License No: / License Number: / License #: / Lic: / Lic. No. / D.L.; apostrophe optional; British/Canadian Licence spelling supported; accepted candidate shapes cover 50 US-state formats: 7-12 pure digits TX/NY/OH/MI/IL/NJ AND 1-2 letters + 6-13 alphanumerics CA/NC/FL/MD; custom _sub_drivers_license substitution preserves DL: label while redacting only the captured num group same as passport mode; added to PII_REDACT_MODES allow-list).
96. [x] Error: NestJS exception filter parsing (new framework='nestjs'; _NEST_PRELUDE regex matches [Nest]...ERROR [<context>] message where context is ExceptionsHandler/HttpExceptionFilter/RpcExceptionFilter/WsExceptionFilter/ValidationPipe/AuthGuard/RolesGuard or any bare alphanumeric with Filter/Handler/Pipe/Exception/Guard suffix; _NEST_EXC regex matches 23 standard HttpException subclasses (NotFound/Unauthorized/Forbidden/BadRequest/Conflict/UnprocessableEntity/TooManyRequests/InternalServerError/BadGateway/ServiceUnavailable/GatewayTimeout/PayloadTooLarge/NotImplemented/NotAcceptable/RequestTimeout/MethodNotAllowed/MisdirectedRequest/ImATeapot/PreconditionFailed/UnsupportedMediaType/Http) + Rpc/Ws/Validation Exception variants; placed BEFORE generic Node branch because Nest runs on Node with identical frame shape; typed exception class beats context name when both present because dashboards care about specific status code; 15-cause _nest_likely_cause catalogue).
66. [x] Error: AWS Lambda / boto3 client error extraction (new framework='boto3'; _BOTO_EXC_HEADER regex matches botocore.exceptions.X / botocore.errorfactory.X / botocore.client.X / boto3.exceptions.X module path prefixes with [A-Z][\w]+ exception class; _BOTO_CLIENT_ERROR regex captures canonical `An error occurred (CODE) when calling the OPERATION operation: detail` message format pulling error_code + operation_name out; composed message slot reads `<detail> [code=ErrorCode op=OperationName]` so structured tail survives plain-string message field; runs FIRST inside python branch of parse_error_text overriding to boto3 framework when ANY boto signal present without disturbing vanilla python tracebacks; 23-cause _boto_likely_cause catalogue covering both SDK-level failures NoCredentialsError/EndpointConnectionError/ReadTimeout/ParamValidationError/WaiterError AND AWS service-level codes NoSuchBucket/NoSuchKey/AccessDenied/Throttling/ResourceNotFound/InternalFailure/etc).


### Backlog
12. [ ] OCR runner: confidence threshold filter that strips low-confidence words above `--min-conf` (per-tenant policy later).
15. [ ] Code: heredoc + multi-language fenced block split (extract first ```lang fence).
16. [ ] Chat: emoji density + reaction-line extraction (the `:eyes: 3` summary footer).
39. [ ] Chat: replied-to / quoted-message detection (the `> quoted text` line + replied-by attribution above the new message).
40. [ ] Chat: voice-note / image / video attachment markers (`🎤 Voice (0:42)`, `📷 Photo`, `[Image]`, `[Voice note 0:23]`).
53. [ ] Chart: bar-chart series-label OCR refinement (split the legend block into a clean `ChartFields.series` list).
54. [ ] Chart: percent annotations vs raw values heuristic (new `ChartFields.value_unit`: `%` / `count` / `currency` based on axis tick text).
55. [ ] UI mockup: layout-style guess (new `UIMockupFields.layout_kind`: `dashboard` / `landing` / `form` / `settings` / `modal`).
56. [ ] PII redact: phone-number redaction mode (`phone` mode; normalises to `<PHONE>` stub form). (Note: a tight `phone` regex already exists in redact.py with `[REDACTED:phone]` placeholder; this would refine to the `<PHONE>` stub form.)
65. [ ] Chat: link preview block detection (the inline OG-card with title + description that platforms inline for shared URLs).
69. [ ] Receipt: tip-jar / suggested-tip table detection (the "10% 12.34 / 15% 18.51 / 20% 24.68" footer table).
71. [ ] Chart: pie-slice percent extraction from in-pie labels (new ChartFields.slices list of {label, percent}).
80. [ ] Receipt: vendor logo / brand-name normalisation against the top-200 chain catalogue (Starbucks / 7-Eleven / etc -- standardise spelling variations OCR may produce).
81. [ ] Error: Spring Boot WhiteLabel error page parsing (`/error` endpoint HTML that surfaces inside a screenshot -- pull status, timestamp, path, message).
90. [ ] Receipt: barcode/QR encoding detection in OCR text (vendors print the encoded payload below the barcode -- track which lines look like the encoded payload vs the human-readable text).
91. [ ] Error: Datadog / Sentry error-fingerprint extraction (the `[abc123]` short-hash that Sentry prints + the dd.trace_id / dd.span_id pair Datadog injects).
93. [ ] Chat: typing-indicator detection (the bouncing-dots animation OCR may render as `...` or `Alice is typing...`).
98. [ ] Receipt: line-item modifier / customisation detection (the indented `+ Add bacon` / `- No onions` / `Extra cheese` sublines beneath an item).
99. [ ] Code: secret/key-literal sniffing into `CodeFields.suspected_secrets` (literal strings that look like API keys / DB credentials / OAuth secrets even when not detected by the typed redact modes).
100. [ ] Extract: cross-category emoji-density tally into `raw["emoji_density"]` (a single float fraction of chars that are emoji -- a quick "this capture is meme-heavy" signal).
101. [ ] Error: GraphQL execution error extraction (the `errors` array shape `[{"message", "path", "locations"}]` GraphQL clients print).
102. [ ] Chart: data-table fallback extraction from a chart screenshot's accompanying legend table (the small `x / y` paired columns that often sit beside the chart).
103. [ ] Receipt: itemised loyalty-points-earned line (`Points Earned: 25` / `Stars Awarded: 3` / `Miles: 100`).
104. [ ] Chat: voice-call / video-call duration markers (`Audio call · 1m 23s` / `Missed video call`).
105. [ ] Code: build-tool / package-manager command detection (npm/yarn/pnpm/cargo/go mod/poetry/pip line into `CodeFields.build_commands`).
106. [ ] Error: Apollo Client / Apollo Server GraphQL error parsing (the `ApolloError: ...` shape with `extensions.code`).
107. [ ] PII redact: bank-account / routing-number redaction mode (US 9-digit routing + 8-12 digit account, IBAN already covered).

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

- 2026-06-21 20:56 PT (tick 13, Cake): 5 features.
  - e96daf8 feat(extract): cross-category Stripe ID extractor into raw["stripe_ids"]
  - 59f2fbb feat(extract): cross-category AWS resource ARN extractor into raw["arns"]
  - 047109a feat(extract): cross-category Discord snowflake ID extractor into raw["discord_ids"]
  - 3afa78c feat(extract/code): author-tagged TODO extraction into CodeFields.todo_authors
  - 6b483c8 feat(extract/receipt): cash-rounding adjustment into ReceiptFields.rounding
  - Gate: ruff at baseline 536 (one N802 fixup on the
    `test_same_author_multiple_todos_NOT_deduped` test
    name -- ruff wants lowercase test names, folded via
    --fixup + --autosquash into the todo_authors commit
    before push) + pytest 2988 passed / 3 skipped in
    140.71s. 206 new tests across the 5 features (50 +
    41 + 32 + 49 + 34). New ReceiptFields shipped:
    rounding (signed). New CodeFields shipped:
    todo_authors. Three new cross-category raw keys:
    raw["stripe_ids"], raw["arns"], raw["discord_ids"].
    LLM wire format in classify/client.py updated for
    rounding and todo_authors. Roadmap refilled with 5
    new items (88..92 -- JWT extractor, Markdown fence
    language, barcode/QR encoding, Datadog/Sentry
    fingerprint, feature-flag SDK calls) so backlog
    stays at 24 open. Disk-space note: pytest ran out
    of /var/folders space on first attempt (228GiB
    full at 100%); freed 854MiB by removing old
    pytest-of-sanjay/ tmpdirs before the re-run.
    Notable design decisions: Stripe prefix table is
    tried longest-first so seti_ wins over si_ and
    promo_ wins over pm_ (defence in depth; the
    underscore boundary in the regex already prevents
    short-prefix theft but the alternation order is
    belt-and-braces); ARN account segment accepts
    literal "aws" so AWS-managed IAM policies
    (arn:aws:iam::aws:policy/...) parse cleanly with
    the resource segment starting at "policy/..."
    instead of "aws:policy/..."; Discord webhook URL
    matcher CAPTURES the ID and DROPS the token
    permanently as a tested security guarantee;
    Discord bare-snowflake matcher REQUIRES the
    context anchor because 17..19 digit decimal blobs
    are too easy to confuse with UNIX nanosecond
    timestamps; todo_authors intentionally does NOT
    dedupe because the same author may legitimately
    own multiple TODOs and the count should be
    accurate; rounding needs a NEW _find_signed_amount_after
    helper because the existing _find_amount_after's
    [:\\-]? separator class would eat a leading minus
    and emit unsigned; sign captured both before and
    after currency symbol (-$0.02 OR $-0.02).

- 2026-06-22 00:07 PT (tick 14, Cake): 5 features.
  - 4da8177 feat(extract): cross-category JWT extractor into raw["jwts"]
  - b814505 feat(extract/code): markdown fence-language detection into CodeFields.fence_language
  - 4ea78f5 feat(extract/code): feature-flag SDK call detection into CodeFields.feature_flags
  - f732291 feat(extract/code): CSS vendor-prefix detection into CodeFields.css_vendor_prefixes
  - 552dc5a feat(redact): passport-number redaction mode
  - Gate: ruff at baseline 536 (zero new errors, zero
    fixups needed -- all five files written clean on
    first pass) + pytest 3200 passed / 3 skipped in
    124.49s. 212 new tests across the 5 features
    (30 + 50 + 63 + 39 + 30). New CodeFields shipped:
    fence_language, feature_flags, css_vendor_prefixes.
    One new cross-category raw key: raw["jwts"]. One
    new PII redact mode `passport` added to
    PII_REDACT_MODES allow-list. LLM wire format in
    classify/client.py updated for fence_language,
    feature_flags, and css_vendor_prefixes. Roadmap
    refilled with 5 new items (93..97 -- chat typing
    indicator, receipt tax-jurisdiction breakdown,
    cross-category postal-code extractor, NestJS
    exception filter, code regex literal extraction).
    Backlog stays at 24 open. Notable design
    decisions: JWT extractor's security guarantee --
    the FULL TOKEN is NEVER stored, signature segment
    discarded entirely, ONLY the JOSE registered
    claims (alg/typ/kid + iss/sub/aud/exp/iat/nbf/jti)
    are surfaced; custom payload claims like email /
    preferred_username intentionally NOT exposed
    because tokens carry PII in custom claims; pairs
    with existing `jwt` redact mode for defence-in-
    depth. Fence-language detector runs FIRST in
    enrich_code on the pre-strip body so fence
    markers survive line-number stripping; we do NOT
    canonicalise short forms (js stays js, py stays
    py) because the original tag carries author
    intent. Feature-flag patterns are vendor-specific
    so a given call site only matches one vendor (no
    ambiguity); 8 vendors catalogued -- LaunchDarkly,
    Statsig, Unleash, Optimizely, Split.io, PostHog,
    Flagsmith, ConfigCat; distinct from imports
    (library dep) vs feature_flags (per-call flag-key
    reference). CSS vendor-prefix detector is
    language-gated to css-family with a content
    fallback that fires when both a prefix candidate
    AND a CSS-like declaration sit within 200 chars
    of each other -- catches mis-classified CSS
    bodies (pygments returns gas / text for short
    CSS) without false-positiving on JS comments
    that mention -webkit- as a flag name. Passport
    mode requires the word `passport` before the
    candidate so bare 9-digit runs don't misfire; the
    custom `_sub_passport` substitution preserves the
    `Passport: ` label and replaces only the captured
    `num` span so the reader knows the field WAS a
    passport without the number leaking; 11+ digit
    runs fail the trailing word-boundary and are
    LEFT UNCHANGED as a safety property (better to
    skip than partially redact).

- 2026-06-22 03:53 PT (tick 15, Cake): 5 features.
  - f451683 feat(extract): cross-category currency-amount extractor into raw["amounts"]
  - 04ecfde feat(extract): cross-category postal-code extractor into raw["postal_codes"]
  - 2476f8a feat(extract/code): regex-literal extraction into CodeFields.regexes
  - bb9a7c6 feat(extract/chat): edited-message marker detection into ChatFields.edits
  - 4f71f06 feat(extract/chat): per-message emoji reaction counts into ChatFields.reactions
  - Gate: ruff at baseline 536 (five I001 fixups on the
    new test files -- ruff wants no blank line between
    the module docstring and the first `from __future__`
    import on the next module-level paragraph; all
    five folded via --fixup + --autosquash into the
    respective feature commits before push) + pytest
    3402 passed / 3 skipped in 140.03s. 202 new tests
    across the 5 features (50 + 49 + 47 + 26 + 30).
    New CodeFields shipped: regexes. New ChatFields
    shipped: edits, reactions. Two new cross-category
    raw keys: raw["amounts"], raw["postal_codes"].
    LLM wire format in classify/client.py updated for
    regexes, edits, reactions. Roadmap refilled with
    5 new items (98..102 -- receipt line-item
    modifiers, code secret/key-literal sniffing,
    cross-category emoji-density tally, GraphQL
    execution errors, chart data-table fallback) so
    backlog stays at 23 open. Disk-space note: hit
    "No space left on device" on the initial __init__.py
    write -- /var/folders had 116MiB free after the
    leftover pytest-of-sanjay tmpdirs from previous
    runs filled it; freed 620MiB by removing
    pytest-of-sanjay/ + go-build cache + node-compile-
    cache before continuing. Notable design decisions:
    amounts extractor's decimal normalisation uses the
    rightmost-separator-is-decimal heuristic with
    group-size disambiguation -- both US (1,234.56) and
    EU (1.234,56) conventions land correctly, plus
    French space-separated (1 234,56); the curated
    40-code ISO 4217 set prevents stray three-letter
    prose words (RED / BIG) from registering. Postal-
    codes extractor splits shapes into self-anchored
    (UK / CA / JP / BR / NL) where the format alone is
    unique enough, and anchored (US / DE / FR / AU /
    IN) where a same-line state / country / city anchor
    is required because bare digit-runs of those
    lengths would false-positive; Canadian first-letter
    restriction enforced (no D/F/I/O/Q/U) per Canada
    Post spec; French departement-0 rejected because
    no real CP starts 00xxx. Code regex-literal
    extractor runs every flavor against every snippet
    (not gated by detected language) because OCR
    captures often mix shells+configs+code and a hard
    language gate would lose hits -- the flavor tag
    in the output preserves which syntax was matched;
    JS division-vs-regex disambiguation via
    left-context lookbehind requiring line-start /
    opener / operator / control keyword; Ruby /
    Perl per-delimiter-pair regexes so inner character
    class never prematurely terminates the match
    (%r{[a-z]+} captures [a-z]+ correctly). Chat
    edited-marker detection uses end-of-line $ anchor
    so a mid-line `(edited)` doesn't fire; substring
    defence on `unedited`/`credited` via space-preceded
    lookbehind on inline form. Chat reactions detector
    uses per-line _is_reaction_line heuristic
    requiring matched emoji+count chars >= 30% of
    non-whitespace content so regular prose containing
    a trailing emoji+number doesn't fire as a footer;
    iMessage reaction-by `❤️ by Alice` lines override
    the current_sender with the REACTOR's name (the
    semantics differ from a normal reaction footer).

- 2026-06-22 07:23 PT (tick 16, Cake): 5 features.
  - 19b9169 feat(extract/receipt): tax-jurisdiction breakdown into ReceiptFields.tax_lines
  - 23f8acd feat(extract/receipt): gift-card and promo-code redemption detection
  - 84be9df feat(redact): drivers-license-number redaction mode
  - d00ca90 feat(extract/error): NestJS exception filter parsing (framework='nestjs')
  - d23625f feat(extract/error): AWS Lambda / boto3 client error extraction (framework='boto3')
  - Gate: ruff at baseline 536 (three fixups folded
    via --fixup + --autosquash before push -- one E501
    on the boto NoCredentialsError cause string (split
    across two lines), plus two I001 fixups on the two
    receipt test files (ruff wants a blank line between
    `from __future__ import annotations` and the next
    import paragraph)) + pytest 3660 passed / 3
    skipped in 126.18s. 258 new tests across the 5
    features (48 + 59 + 45 + 52 + 54). New ReceiptFields
    shipped: tax_lines (list of jurisdiction/amount
    dicts), gift_card_applied (positive float),
    promo_code (str). One new PII redact mode
    `drivers_license` added to PII_REDACT_MODES
    allow-list (mirrors passport mode's _sub_drivers_license
    substitution that preserves the label while
    redacting only the captured num group). Two new
    error frameworks: 'nestjs' (placed BEFORE Node
    branch because Nest runs on Node with identical
    frame shape; discriminator is the [Nest] PID
    prefix + ERROR [<context>] tag) and 'boto3'
    (placed FIRST inside the python branch so any
    boto signal overrides framework='python' to
    framework='boto3' without disturbing vanilla
    Python tracebacks). LLM wire format in
    classify/client.py updated for tax_lines /
    gift_card_applied / promo_code. Roadmap refilled
    with 5 new items (103..107 -- receipt loyalty
    points, chat call duration, code build commands,
    Apollo GraphQL errors, bank-account redact)
    so backlog stays at 22 open. Notable design
    decisions:
    * tax_lines bare "Tax" keyword intentionally
      OUT of the catalogue because the top-level
      `tax` field already owns it; tax_lines
      surfaces ONLY when 2+ jurisdictions are
      present so dashboards can rely on
      len(tax_lines) > 0 meaning "real multi-
      jurisdiction breakdown" without per-receipt
      special cases. Longest-first ordering with
      overlap-defence prevents "VAT" stealing the
      suffix of "Import VAT".
    * gift_card_applied always emitted POSITIVE
      regardless of leading `-` because the field
      semantic implies the sign (it's the amount
      knocked off by the gift card; whether the
      printer wrote it as -25 or 25 carries no
      extra information).
    * promo_code rejects pure-digit codes longer
      than 3 digits because a 5-digit run after
      "Promo Code:" is almost always an order
      number misprint. Original case preserved
      so Shopify lowercase / legacy uppercase
      both survive.
    * drivers_license matcher requires the label
      (DL / license / licence / lic / driver's
      license) immediately BEFORE the candidate
      so a bare 7-12 digit run on a receipt
      doesn't misfire as a license. Mirrors the
      passport mode's safety guarantee on every
      axis: label-preserving substitution, custom
      `_sub_drivers_license` handler, both
      apostrophe-and-no-apostrophe `driver's
      license` shapes, British `Licence` spelling,
      50-state US format coverage.
    * NestJS sits BEFORE Node in elif chain;
      typed exception class (NotFoundException)
      beats context name (ExceptionsHandler) when
      both present because dashboards care about
      the specific HTTP status code. Backed by
      15-cause likely_cause catalogue.
    * boto3 runs FIRST inside the python branch
      so the framework override fires whenever
      ANY boto signal is present (the typed
      exception header or the canonical
      "An error occurred ..." message). Composed
      message slot reads `<detail> [code=X op=Y]`
      so the structured AWS error code +
      operation pair survives the schema's
      plain-string `message` field. Backed by
      23-cause _boto_likely_cause catalogue
      covering both SDK-level failures (no
      credentials, endpoint connection, waiter
      timeout) AND service-level codes
      (NoSuchBucket, AccessDenied, Throttling,
      ResourceNotFound, etc).

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
