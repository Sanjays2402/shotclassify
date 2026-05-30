# shotclassify

Screenshot classifier with vision LLM, OCR, structured extraction, and action routing.

![landing](docs/screenshots/landing.png)

## What it does

Takes a screenshot upload, runs OCR (Tesseract) and a vision LLM in parallel, and assigns one of nine categories with a per-class confidence vector. Saves the image, the OCR transcript, the model rationale, and the full classification record to SQLite (or Postgres) and exposes it via a FastAPI service. A Next.js web UI sits on top for upload, history browsing, per-shot inspection, and a calibration dashboard. Optional Redis/RQ queue handles batch loads; optional rules engine routes high-confidence shots to Slack or other sinks.

## Features

- `POST /v1/classify` single-image upload, returns `ProcessResult` with primary category, confidences, OCR text, rationale.
- `POST /v1/classify/batch` parallel multi-file classification.
- `POST /v1/classify/{id}/reclassify` rerun the pipeline on a stored image.
- `POST /v1/classify/{id}/correct` user-supplied ground truth, persisted for calibration.
- `POST /v1/queue` enqueue via Redis RQ when available, fall back to inline background task.
- `GET /v1/history` paginated history with category filter and full-text search over OCR + filename.
- `GET /v1/history/stats` total count.
- `GET /v1/history/{id}` full record with OCR transcript and confidence distribution.
- Web UI: upload page, shots list, per-shot detail with OCR transcript, calibration page with reliability diagram and ECE/Brier/Log loss.
- API key + GitHub OAuth session auth, request-id middleware, OpenTelemetry FastAPI instrumentation.

## Stack

- Backend: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, Tesseract via pytesseract, OpenCV (headless), Pillow, OpenAI-compatible vision client, RQ + Redis, structlog, Typer CLI, OpenTelemetry.
- Web: Next.js 15, React 19, Tailwind v4, Recharts, SWR, Phosphor Icons, fonts Space Grotesk / Inter / JetBrains Mono via `next/font/google`.
- Storage: local filesystem or S3; SQLite by default, Postgres supported via `DATABASE_URL`.
- Infra: Dockerfiles for api/worker/web, Helm chart, Terraform skeleton under `infra/`.

## Architecture

Upload hits the FastAPI route, the image is persisted to `STORAGE_LOCAL_DIR/uploads`, then `shotclassify_common.pipeline.process_image` runs OCR (`packages/ocr`) and the LLM classifier (`packages/classify`) in a worker thread. Output is normalised into a `ProcessResult`, optionally enriched with structured field extraction (`packages/extract`), persisted by `packages/store`, and run through the rules engine (`packages/route`). The Next.js app reads from `/v1/*` via SWR.

```
              +------------+        +-----------------+
upload ---->  |  FastAPI   | -----> | pipeline thread |
              |  /v1/...   |        |  OCR + vision   |
              +-----+------+        +--------+--------+
                    |                        |
                    |  ProcessResult         v
                    |                +---------------+
                    +--------------> |  Repository   | --> SQLite/Postgres
                                     +-------+-------+        + blob storage
                                             |
                       +---------------------+----------------------+
                       |                                            |
                  rules engine                              Next.js web UI
                  (Slack, dry-run)                          (SWR, Recharts)
```

## Quick start

Requires Python 3.11+, Node 20+, Tesseract, and Redis (optional, only for `/v1/queue`).

```bash
# Backend
cp .env.example .env
uv sync                                   # or: pip install -e . -e packages/*
uv run uvicorn services.api.app.main:app --reload --port 7441

# Worker (optional, for /v1/queue)
uv run python -m services.worker.app.main

# Web
cd web && npm install && npm run dev      # http://localhost:3000

# CLI
uv run shotclassify --help
```

API on `:7441`, web on `:3000`. The web UI talks to the API through Next.js route handlers under `web/app/api`. Point `LLM_BASE_URL` at any OpenAI-compatible endpoint (local Copilot proxy on `:4141` by default).

## Configuration

From `.env.example`:

| Var | Default | Notes |
| --- | --- | --- |
| `APP_ENV` | `development` | |
| `APP_HOST` / `APP_PORT` | `0.0.0.0` / `7441` | uvicorn bind |
| `APP_SECRET_KEY` | `change-me-...` | session signing, 32+ bytes |
| `APP_LOG_LEVEL` / `APP_LOG_FORMAT` | `INFO` / `json` | structlog |
| `STORAGE_BACKEND` | `local` | `local` or `s3` |
| `STORAGE_LOCAL_DIR` | `./storage` | mounted at `/blob` |
| `STORAGE_S3_BUCKET` / `STORAGE_S3_REGION` | `` / `us-west-2` | |
| `DATABASE_URL` | `sqlite:///./shotclassify.db` | Postgres supported |
| `REDIS_URL` / `QUEUE_NAME` | `redis://localhost:6379/0` / `shotclassify` | RQ |
| `LLM_BASE_URL` | `http://127.0.0.1:4141/v1` | OpenAI-compatible |
| `LLM_API_KEY` | `copilot` | |
| `LLM_MODEL` | `gpt-4o-mini` | vision-capable |
| `LLM_TIMEOUT_S` / `LLM_MAX_RETRIES` | `60` / `2` | |
| `OCR_LANG` | `eng` | tesseract lang code |
| `OCR_PSM` | `6` | tesseract page seg mode |
| `OCR_DESKEW` | `true` | OpenCV deskew pass |
| `AUTH_ENABLED` | `true` | |
| `AUTH_OAUTH_PROVIDER` | `github` | |
| `AUTH_OAUTH_CLIENT_ID` / `AUTH_OAUTH_CLIENT_SECRET` | | |
| `AUTH_ALLOWED_GITHUB_LOGIN` | `Sanjays2402` | single-user allowlist |
| `AUTH_API_KEY` | | bearer for programmatic access |
| `ROUTE_RULES_PATH` | `./packages/route/rules.example.yaml` | |
| `ROUTE_DRY_RUN` | `true` | |
| `ROUTE_SLACK_WEBHOOK` | | |
| `OTEL_ENABLED` | `false` | |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | |
| `OTEL_SERVICE_NAME` | `shotclassify-api` | |

## Scripts

Python (`scripts/`):

- `scripts/make_samples.py` generate sample screenshots into `samples/`.
- `scripts/make_corpus.py` generate the synthetic eval corpus under `fixtures/synth/`.
- `scripts/bench.py` run the corpus through the pipeline and write `fixtures/bench/report.{json,csv}`.
- `scripts/dev.sh`, `scripts/dogfood.sh` local helpers.

Make targets: `install`, `dev`, `test`, `fmt`, `lint`, `samples`, `api`, `worker`, `web`, `docker`, `compose-up`, `clean`.

CLI (`shotclassify` entrypoint, Typer): `classify`, `history`, `show`, `correct`, `serve`.

Web (`web/package.json`): `dev`, `build`, `start`, `lint`.

## API

Base: `http://localhost:7441`.

Health:

- `GET /` `GET /healthz` `GET /readyz`

Auth (`/auth`):

- `GET /auth/login`
- `GET /auth/callback`
- `POST /auth/logout`
- `GET /auth/whoami`

Classify (`/v1`):

- `POST /v1/classify` multipart `file`, optional `note`.
- `POST /v1/classify/batch` multipart `files[]`.
- `POST /v1/classify/{item_id}/reclassify`
- `POST /v1/classify/{item_id}/correct` form `category`.
- `POST /v1/queue` background classification via RQ.

History (`/v1/history`):

- `GET /v1/history?limit=&category=&q=`
- `GET /v1/history/stats`
- `GET /v1/history/{item_id}`
- `DELETE /v1/history/{item_id}`

Settings (`/v1/settings`):

- `GET /v1/settings/rules`
- `PUT /v1/settings/rules`
- `GET /v1/settings/env`

Static blobs are served from `/blob/*`.

## Categories

Defined in `packages/common/src/shotclassify_common/schemas.py::Category`:

`receipt`, `code_snippet`, `error_stacktrace`, `chat_screenshot`, `meme`, `document`, `ui_mockup`, `chart`, `other`.

## Calibration

The web `/calibration` page renders a reliability diagram against three metrics:

- **ECE** Expected Calibration Error, weighted gap between confidence and accuracy across bins.
- **Brier** mean squared error between predicted probability and the one-hot outcome.
- **Log loss** cross-entropy over the holdout set.

Generate inputs with `python scripts/make_corpus.py` then `python scripts/bench.py`; the report under `fixtures/bench/` feeds offline calibration analysis. Helpers live in `packages/classify/src/shotclassify_classify/calibration.py`.

## Project structure

```
.
├── cli/                  Typer CLI (shotclassify)
├── packages/
│   ├── common/           Pydantic schemas, settings, pipeline
│   ├── ocr/              Tesseract + OpenCV preprocessing
│   ├── classify/         vision LLM prompts + calibration
│   ├── extract/          structured field extraction
│   ├── route/            rules engine, Slack sink
│   └── store/            SQLAlchemy repository, migrations
├── services/
│   ├── api/              FastAPI app (routes, middleware, models)
│   └── worker/           RQ worker
├── web/                  Next.js 15 app (app router)
├── scripts/              corpus, samples, bench
├── infra/                docker, helm, terraform
├── macos/                Shortcut installer
├── fixtures/             synth corpus + bench reports
├── samples/              generated sample screenshots
├── docs/                 schemas + screenshots
└── tests/                pytest suite
```

## License

MIT. See `LICENSE`.
