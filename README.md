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

## Operations

### Audit log

Every authenticated, state-changing request (POST, PUT, PATCH, DELETE) is
persisted to the `audit_log` table by `AuditLogMiddleware`. Each row captures:

- `principal` (GitHub login or `api-key`), `method`, `path`, `status_code`
- `request_id` (matches the `x-request-id` response header and structured logs)
- `client_ip` (honours `X-Forwarded-For` when present), `user_agent`
- `elapsed_ms`, `target_id` (best-effort `/v1/<resource>/<id>` extraction)
- `created_at` (UTC), plus a free-form `extra` JSON column for future fields

Read-only requests, health probes, OAuth callbacks, and static `/blob/*` fetches
are deliberately skipped to keep the table focused on actions worth reviewing.
Audit writes are wrapped in a `try/except` so a logging failure can never break
the user request, but failures are emitted as `audit_log_write_failed` warnings.

Query the trail:

```bash
curl -H "X-API-Key: $AUTH_API_KEY" https://host/v1/audit?limit=50
curl -H "X-API-Key: $AUTH_API_KEY" "https://host/v1/audit?principal=api-key"
curl -H "X-API-Key: $AUTH_API_KEY" "https://host/v1/audit?path_prefix=/v1/history"
curl -H "X-API-Key: $AUTH_API_KEY" https://host/v1/audit/stats
```

The table is created automatically via `init_db()` on boot and is also covered
by Alembic migration `0002_audit_log` for Postgres deployments where you want
to manage schema changes explicitly.

### Rate limiting

`RateLimitMiddleware` enforces a token bucket per client. Requests carrying
`X-API-Key` are scoped by key, the rest by client IP (honouring
`X-Forwarded-For` when present, so put a trusted proxy in front in production).
The bucket runs in-process per pod, so the effective cluster-wide ceiling is
`replicaCount.api * RATE_LIMIT_*_RPM` in the worst case. For a hard global
limit, terminate at an ingress that does its own rate limiting and treat these
values as a safety net.

Defaults (override via env or Helm `rateLimit.*` / `env.RATE_LIMIT_*`):

| Setting | Default | Meaning |
| --- | --- | --- |
| `RATE_LIMIT_ENABLED` | `true` | Master switch. |
| `RATE_LIMIT_PER_IP_RPM` | `120` | Sustained requests per minute per source IP. |
| `RATE_LIMIT_PER_KEY_RPM` | `600` | Sustained rpm per `X-API-Key`. |
| `RATE_LIMIT_BURST` | `20` | Extra tokens above the sustained rate for short bursts. |
| `RATE_LIMIT_EXEMPT_PATHS` | `/healthz,/readyz,/metrics,/blob` | Comma-separated path prefixes the limiter ignores. |

When a bucket is empty the API responds with HTTP 429, a JSON body of
`{"error":"rate_limited"}`, a `Retry-After` seconds header, and
`X-RateLimit-Scope: ip|api_key`. Rejections increment
`shotclassify_rate_limit_rejections_total{scope}` so you can alert on sustained
throttling and distinguish abusive IPs from a noisy API key.

### Metrics

The API exposes Prometheus metrics on `GET /metrics` (public, unauthenticated,
intended for in-cluster scraping). `PrometheusMiddleware` wraps every request
outermost so it observes auth failures and exceptions in addition to handler
latency. The exported series are:

- `shotclassify_http_requests_total{method,route,status}` counter
- `shotclassify_http_request_duration_seconds{method,route}` histogram
  (buckets: 5ms to 10s)
- `shotclassify_http_requests_in_flight{method}` gauge
- `shotclassify_http_exceptions_total{method,route,exception}` counter

The `route` label uses the FastAPI path template (for example `/v1/items/{id}`)
rather than the raw URL, so cardinality stays bounded regardless of client
input. Scrapes of `/metrics` itself are intentionally excluded from these
counters to avoid self-amplification.

The Helm chart adds `prometheus.io/scrape` annotations to the API Service and
Pod template for annotation-based scrapers, and includes an optional
`ServiceMonitor` for the Prometheus Operator. Enable it with:

```yaml
metrics:
  serviceMonitor:
    enabled: true
    interval: 30s
    labels:
      release: kube-prometheus-stack
```

For multi-worker uvicorn/gunicorn deployments, set `PROMETHEUS_MULTIPROC_DIR`
to a writable directory and the endpoint will aggregate across workers via
`prometheus_client.multiprocess`.

### Deploy

Production deployments use the Helm chart in `infra/helm/shotclassify`. The
chart ships a multi-stage Dockerfile (`infra/docker/Dockerfile`), HPA, network
policy, and configurable resource limits. CI runs lint + tests + build on every
push via `.github/workflows/ci.yml`.

### Health and readiness

- `GET /healthz` returns liveness without touching dependencies.
- `GET /readyz` checks DB connectivity and reports queue / LLM endpoints.

Wire these to your Kubernetes liveness/readiness probes (defaults already set in
the Helm chart).

### Backup

The SQLite default is fine for single-node and dev, but production should run
Postgres via `DATABASE_URL`. Back up both the database (classifications and
audit log) and the object/blob store (`STORAGE_LOCAL_DIR` or the configured S3
bucket). The audit log is append-only in practice and is your forensic record
of who did what, so prioritise its restore path.

### On-call

- Structured JSON logs include `request_id`, `path`, and `method`. Search for a
  request by `request_id` to correlate the full request lifecycle across the
  API, worker, and audit log.
- Watch `shotclassify_http_request_duration_seconds` p95/p99 per route and
  `shotclassify_http_requests_total{status=~"5.."}` for error budget burn.
  Suggested first alerts: 5xx rate > 1% over 5 min, and p95 latency on
  `/v1/classify` over 5 seconds.
- If `audit_log_write_failed` warnings appear, the request itself still
  succeeded; investigate DB connectivity to the audit table.
- Spike in `/v1/audit` rows from an unexpected `principal` is a credential
  abuse signal. Rotate `AUTH_API_KEY` and revoke OAuth sessions if needed.
- Sustained `shotclassify_rate_limit_rejections_total{scope="api_key"}` means a
  legitimate caller is hitting their per-key ceiling. Either raise
  `RATE_LIMIT_PER_KEY_RPM` or issue a separate key. Rejections with
  `scope="ip"` from a single address that has no key are usually scanners,
  block at the ingress.

## License

MIT. See `LICENSE`.
