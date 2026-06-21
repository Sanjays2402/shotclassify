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

## Roadmap (40 features tracked)

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

### Backlog
12. [ ] OCR runner: confidence threshold filter that strips low-confidence words above `--min-conf` (per-tenant policy later).
15. [ ] Code: heredoc + multi-language fenced block split (extract first ```lang fence).
16. [ ] Chat: emoji density + reaction-line extraction (the `:eyes: 3` summary footer).
32. [ ] Chat: emoji reaction counts on a per-message basis (the `❤️ 3 👍 2` footer).
39. [ ] Chat: replied-to / quoted-message detection (the `> quoted text` line + replied-by attribution above the new message).
40. [ ] Chat: voice-note / image / video attachment markers (`🎤 Voice (0:42)`, `📷 Photo`, `[Image]`, `[Voice note 0:23]`).
42. [ ] Code: JSDoc / docstring extraction (top-level docstring captured into `CodeFields.docstring` for Python / JS / Java / Go).
43. [ ] Code: import-set extraction (new `CodeFields.imports` list of imported modules/packages, per language).
45. [ ] Error: Swift / Objective-C crash log parsing (framework=swift; `Fatal error: Unexpectedly found nil`, `*** Terminating app due to uncaught exception`).
46. [ ] Error: Kotlin coroutine exception parsing (framework=kotlin; `kotlinx.coroutines.JobCancellationException`, `at ... CoroutineScopeKt`).
51. [ ] Extract: cross-category credit-card detection (PAN-shaped digit runs that pass Luhn; redact to BIN+last4 in `raw["pii"]`).
52. [ ] Extract: cross-category ICAO / IATA airport-code extractor into `raw["airports"]` for travel screenshots.
53. [ ] Chart: bar-chart series-label OCR refinement (split the legend block into a clean `ChartFields.series` list).
54. [ ] Chart: percent annotations vs raw values heuristic (new `ChartFields.value_unit`: `%` / `count` / `currency` based on axis tick text).
55. [ ] UI mockup: layout-style guess (new `UIMockupFields.layout_kind`: `dashboard` / `landing` / `form` / `settings` / `modal`).
56. [ ] PII redact: phone-number redaction mode (`phone` mode; normalises to `<PHONE>` stub).
57. [ ] PII redact: physical-address redaction mode (`address` mode; one-line US/UK street + city + zip patterns).
58. [ ] Extract: cross-category time-zone offset extractor (UTC offsets like `+05:30`, `-0800`, `Z`; named zones like `PST` / `JST` / `IST`).
59. [ ] Extract: cross-category currency-amount extractor into `raw["amounts"]` (cross-category so a code snippet or chat message that quotes a price is surfaced; symbol + ISO code aware).
60. [ ] Receipt: signature / signed-by detection (`Signature: _____`, `Signed by: Bob`, `X____` line markers).
61. [ ] Receipt: barcode / SKU extraction at the line-item level (`SKU: 1234567`, `Barcode: 0123456789012`).
62. [ ] Code: line-numbering detection (when the snippet starts every line with a number+space, strip the prefix and store `CodeFields.numbered = True`).
63. [ ] Receipt: tender / change-given detection (new ReceiptFields.change; "Tendered 20.00 / Change 7.50" shape).
64. [ ] Code: TODO / FIXME comment count surfaced as CodeFields.todo_count for code-review screenshots.
65. [ ] Chat: link preview block detection (the inline OG-card with title + description that platforms inline for shared URLs).
66. [ ] Error: AWS Lambda / boto3 client error extraction (BotoCoreError, ClientError with operation_name + error_code).
67. [ ] Extract: cross-category MAC-address extractor into raw["macs"] (colon-separated + dash-separated 48-bit forms).

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
