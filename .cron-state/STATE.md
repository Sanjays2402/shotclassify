# shotclassify autoship state

Branch: `feature/autoship` (off `main`)
Owner: Cake (cron) — 20-min batch loop, target 5 features per tick.

## Stack snapshot
- Python 3.11+, uv workspace, FastAPI API, worker, web (Next.js), packages: classify/common/extract/ocr/route/store, cli.
- Pipeline: OCR (tesseract) -> classify (vision LLM with heuristic fallback) -> extract (per-category) -> route (yaml rules) -> store (SQLAlchemy).
- Test runner: `uv run pytest` (~5 min full suite, 753 tests). `uv run ruff check .` for lint.
- DO NOT add heavy deps (no torch / tensorflow). opencv-headless already in.

## Conventions
- One feature == one commit, cron identity (`Cake (cron)` / noreply email).
- No emoji in git. No PRs, no tags, no merge to main.
- Pydantic models in `packages/common/src/shotclassify_common/schemas.py` are stored as JSON columns, so adding optional fields is safe.
- `redact_text` patterns live in `packages/common/src/shotclassify_common/redact.py`; adding a mode requires updating `PII_REDACT_MODES` in `packages/store/src/shotclassify_store/tenant_settings.py`.
- Extractors in `packages/extract/src/shotclassify_extract/*.py` enrich existing fields; tests live next to other extractor tests in `tests/`.
- Existing test patterns use `monkeypatch.setenv(...)` for env, `tmp_path` for sqlite, then `from services.api.app.main import create_app`.

## Roadmap (15 features)

### Done in this tick (5 planned)
1. [x] Receipt: tip/gratuity extraction (extract `tip` from "Tip: 5.00", "Gratuity: ..."; add field).
2. [x] Receipt: payment method detection (cash/visa/mc/amex/discover/apple-pay).
3. [x] Error: Go panic + Ruby/Rails stacktrace support (new frameworks + likely_cause cases).
4. [x] Code: expanded language hints (rust/kotlin/swift/c#/elixir/php/haskell/scala) + framework guesses.
5. [x] PII redaction: new modes for `jwt`, `aws_access_key`, `github_pat`, `slack_token`.

### Backlog
6. [ ] Chat: timestamp parsing from message lines (12:34, 12:34 PM, 2026-01-01T...).
7. [ ] Receipt: discount line extraction (Discount, Coupon, Promo).
8. [ ] Receipt: tip percentage computation (`tip_percent` derived from tip/subtotal).
9. [ ] Code: detect popular framework imports (react, vue, django, rails, spring).
10. [ ] OCR runner: confidence threshold filter that strips low-confidence words above `--min-conf` (per-tenant policy later).
11. [ ] Extract: URL extractor that pulls every `http(s)://` link from OCR text into `ExtractedFields.raw["urls"]`.
12. [ ] Extract: hashtag + mention extractor for chat screenshots (`#tag`, `@user`).
13. [ ] Receipt: currency inference from locale phrases ("Total in CAD", "CHF", "AUD").
14. [ ] Error: HTTP status code classifier (5xx/4xx pattern detection -> framework=http).
15. [ ] Code: heredoc + multi-language fenced block split (extract first ```lang fence).

## Tick log
- 2026-06-20 05:37 PT (tick 1, Cake): bootstrap + 5 features.
  - 0d85454 feat(extract/receipt): tip and gratuity extraction
  - 9ac3b34 feat(extract/receipt): payment method detection
  - f36757d feat(extract/error): Go panic and Ruby/Rails stacktrace support
  - 1afe733 feat(extract/code): more languages + framework detection
  - 48a349c feat(redact): JWT, AWS, GitHub, Slack token redaction modes
  - Gate: ruff (no NEW errors above baseline of 10) + pytest 850 passed / 3 skipped.

## Risks / notes
- Web UI work skipped this tick — Python-only shipping for speed (test suite already costs ~5 min).
- API/middleware features deferred because they cost a full TestClient bootstrap per test; the 20-min budget is tight.
