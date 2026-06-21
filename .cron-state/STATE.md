# shotclassify autoship state

Branch: `feature/autoship` (off `main`)
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

## Roadmap (35 features tracked)

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

### Backlog
12. [ ] OCR runner: confidence threshold filter that strips low-confidence words above `--min-conf` (per-tenant policy later).
15. [ ] Code: heredoc + multi-language fenced block split (extract first ```lang fence).
16. [ ] Chat: emoji density + reaction-line extraction (the `:eyes: 3` summary footer).
25. [ ] Code: detect minified vs hand-written JS (heuristic: avg line length, lack of newlines after `;` and `{`).
26. [ ] Receipt: detect tax-inclusive vs exclusive pricing from text cues (`VAT included` / `tax incl.` / `+ tax`).
28. [ ] Code: comment-density heuristic (% of lines that start with `//` or `#`) as a CodeFields.raw signal.
32. [ ] Chat: emoji reaction counts on a per-message basis (the `❤️ 3 👍 2` footer).
33. [ ] Error: Python `SyntaxError` with caret line extraction (`^^^^^^^` indicator).
34. [ ] Receipt: split-bill / parties detection (`Party of 4`, `Split 3 ways`).
35. [ ] Code: TypeScript-specific signals (decorators, `as` casts, generic type params) beyond the current `: type` tags.

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
