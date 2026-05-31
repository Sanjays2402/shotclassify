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

## Try it

With the API and web both running, open <http://127.0.0.1:3000/demo>. Click any of the four sample screenshots (receipt, code snippet, stack trace, chat) and the page runs the real OCR plus vision pipeline, then renders the class probability bars, latency, model rationale, and OCR transcript. No upload, no signup.

For your own frames, open <http://127.0.0.1:3000/upload> and drop one or more images. Each file gets its own result card with a thumbnail, the primary call and its confidence, round-trip latency, full per-class confidence bars, the model's rationale, and the OCR transcript. Cards stream in parallel, errors stay scoped to the failing file, and any card opens the full replay at `/shots/{id}`.

One-shot curl against the same endpoint the demo page calls:

```bash
curl -s -X POST http://127.0.0.1:7441/v1/classify \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  -F "file=@samples/fake-receipt.png" | jq '.classification.primary, .classification.confidences[0]'
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

Data lifecycle (`/v1/me`):

- `GET /v1/me/data` export everything tied to the authenticated principal.
- `DELETE /v1/me/data?confirm=erase` permanently erase it.

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

### Production configuration validation

The API and worker run `shotclassify_common.validate_for_production` from
their startup lifespan. When `APP_ENV` is `staging` or `production` the
process refuses to come up if any of the following are still at their dev
default or otherwise unsafe:

- `APP_SECRET_KEY` is the placeholder, empty, or shorter than 32 bytes
- `AUTH_ENABLED` is false
- `AUTH_API_KEY` is the well-known `dev-api-key-change-me` placeholder
- `CORS_ALLOWED_ORIGINS` is empty or contains `*`
- `DATABASE_URL` points at SQLite
- `STORAGE_BACKEND=local` (ephemeral inside a pod) or `s3` with no bucket
- `LLM_API_KEY` is empty or the dev `copilot` placeholder

All failures are reported in a single `InsecureConfigurationError` so an
operator can fix the deploy in one pass instead of crash-looping per
setting. `APP_ENV=development` is exempt so local iteration keeps working.
Verify a candidate environment file before rollout:

```sh
APP_ENV=production env $(grep -v '^#' .env.production | xargs) \
  python -c "from shotclassify_common import validate_for_production; validate_for_production(); print('ok')"
```

The matching test suite lives in `tests/test_secrets_validation.py`.

### Container images

All three services ship as multi-stage Docker images under `infra/docker/`:

| Image     | Dockerfile                  | Base                       | Final user      |
| --------- | --------------------------- | -------------------------- | --------------- |
| API       | `infra/docker/Dockerfile`        | `python:3.11-slim`         | `app` (uid 10001) |
| Worker    | `infra/docker/Dockerfile.worker` | `python:3.11-slim`         | `app` (uid 10001) |
| Web       | `infra/docker/Dockerfile.web`    | `node:20-bookworm-slim`    | `app` (uid 10001) |

Every Dockerfile is multi-stage. The builder stage installs the full compile
toolchain (`build-essential`, `libpq-dev`, `libffi-dev`, `libssl-dev`,
`libtesseract-dev`, etc.) and resolves the Python or Node dependency closure.
The runtime stage starts from a clean slim base, copies only the installed
site-packages or production `node_modules`, ships only the runtime OS
libraries (`tesseract-ocr`, `libgl1`, `libglib2.0-0`, `libpq5`, `tini`,
`ca-certificates`), creates an unprivileged `app` user (uid/gid 10001), and
runs the process under `tini` so SIGTERM is forwarded cleanly to uvicorn /
the RQ worker / `next start`.

The API and web images declare a `HEALTHCHECK` against `/healthz` and `/` so
`docker ps`, swarm, and ECS see container-level liveness without depending
on Kubernetes probes.

Build context is pruned by `.dockerignore` at the repo root, which excludes
`.git`, `.venv`, `node_modules`, `web/.next`, local SQLite databases, the
`storage/` and `samples/` directories, the Helm and Terraform trees, and any
`.env*` file other than `.env.example`. This keeps image layers free of
local state and prevents accidentally baking secrets into a pushed tag.

Build and push from the repo root:

```sh
docker build -f infra/docker/Dockerfile        -t ghcr.io/sanjays2402/shotclassify-api:$(git rev-parse --short HEAD)    .
docker build -f infra/docker/Dockerfile.worker -t ghcr.io/sanjays2402/shotclassify-worker:$(git rev-parse --short HEAD) .
docker build -f infra/docker/Dockerfile.web    -t ghcr.io/sanjays2402/shotclassify-web:$(git rev-parse --short HEAD)    .
```

The Helm `api` Deployment now sets a pod-level `securityContext`
(`runAsNonRoot: true`, uid/gid 10001, `seccompProfile: RuntimeDefault`) and a
container-level `securityContext` that drops all Linux capabilities and
blocks privilege escalation, matching the non-root user baked into the image.

`tests/test_dockerfiles.py` enforces these properties statically (multi-stage,
non-root final `USER`, healthcheck present, no build toolchain leaked into
the runtime stage, `tini` entrypoint, `.dockerignore` excludes secrets) so a
future refactor that regresses them fails CI without needing a Docker daemon.

### Roles and access control

The API enforces a three-tier role model on every authenticated route:

| Role     | Read history | Classify / reclassify | Delete history | Read settings | Write settings | Read audit log |
| -------- | :----------: | :-------------------: | :------------: | :-----------: | :------------: | :------------: |
| viewer   | yes          | no                    | no             | no            | no             | no             |
| operator | yes          | yes                   | yes            | yes           | no             | no             |
| admin    | yes          | yes                   | yes            | yes           | yes            | yes            |

Role assignment lives in environment variables (see `.env.example`):

* `AUTH_API_KEY` is the legacy single key and is always treated as `admin`.
* `AUTH_API_KEYS` is a JSON object `{key: role}` for provisioning additional
  keys with non-admin roles, for example
  `'{"ops-rotating-token": "operator", "dashboard-readonly": "viewer"}'`.
* `AUTH_ROLE_MAP` is a JSON object `{login: role}` mapping authenticated
  GitHub logins to roles.
* Any authenticated principal not matched falls through to
  `AUTH_DEFAULT_ROLE` (default `viewer`).
* Malformed JSON in `AUTH_API_KEYS` or `AUTH_ROLE_MAP` is ignored rather than
  failing startup, so a bad rotation never locks the cluster out.

Unauthenticated requests still return `401`. Authenticated requests that lack
the required role return `403` with a body like
`{"detail": "Role 'viewer' lacks required role 'admin'."}`. The data lifecycle
endpoints under `/v1/me/data` are deliberately open to every authenticated
role because they self-scope to the caller's own rows.

In the Helm chart, set `secret.apiKeys` and `secret.roleMap` (JSON strings)
alongside the existing `secret.apiKey`; the chart wires them through to the
API Deployment as `AUTH_API_KEYS` and `AUTH_ROLE_MAP` secret env vars only
when non-empty.

### Multi-tenancy

Every persisted row (classifications, audit_log, api_keys) carries a
`tenant_id` column and every repository query is scoped to the caller's
tenant. One tenant cannot read, list, mutate, or delete another tenant's
data through the public API, even when they share an endpoint, principal
name, or role.

Tenant resolution runs as `TenantResolutionMiddleware` (in
`services/api/app/middleware/tenant.py`) right after authentication. It
sets `request.state.tenant_id` from this lookup order:

1. `X-Tenant` request header, when the caller's role is `admin`. Admins may
   pass `*` to opt into a cross-tenant view (the repository skips the
   tenant filter entirely) or any specific tenant id to operate inside
   that tenant. Non-admin callers cannot escape their tenant; the header
   is ignored for them.
2. `AUTH_TENANT_MAP`, a JSON object `{principal: tenant_id}` that maps
   API keys and OAuth logins to a tenant. Example:

   ```
   AUTH_TENANT_MAP='{"acme-ops-key":"acme","globex-view-key":"globex","sanjay":"acme"}'
   ```

3. `AUTH_DEFAULT_TENANT` (defaults to `default`), used for any principal
   not present in the map. This keeps single-tenant deployments working
   without any new configuration.

Writes tag rows with the resolved tenant id at insert time. The classify,
batch, reclassify, correct, history, audit, and `/v1/me/data` routes all
thread `request.state.tenant_id` into the repository call so the scoping
is enforced at the SQL layer rather than relying on application-side
filtering.

Rows written before the multi-tenancy migration have `tenant_id IS NULL`.
The repository treats them as belonging to whatever tenant the caller is
scoped to, so the migration is non-destructive for existing solo
deployments; backfill them with an `UPDATE ... SET tenant_id = 'default'`
when you are ready to enforce strict isolation.

Apply the schema change with the bundled Alembic migration:

```sh
cd packages/store && alembic upgrade head
```

The migration (`0004_tenant_id`) adds a nullable `tenant_id String(64)`
column plus an index on each of `classifications`, `api_keys`, and
`audit_log`. It is reversible.

Coverage lives in `tests/test_multitenant.py`: tenant isolation on
history listing, cross-tenant GET returning 404, cross-tenant DELETE
blocked, tenant-scoped stats, admin cross-tenant header behavior, and a
GDPR export that only returns the caller's tenant rows even when the
principal name collides across tenants.

### Data lifecycle (GDPR)

The API exposes a per-principal export and erasure endpoint under `/v1/me/data`.
Scope is the request principal as set by `APIKeyAndSessionAuth`: the GitHub
login for session users, or the literal string `api-key` for API key callers.

Export bundles the caller's identity, every `classifications` row tagged with
that principal (full extracted/route JSON plus OCR text), and every `audit_log`
row recorded against the principal:

```bash
curl -H "X-API-Key: $AUTH_API_KEY" https://host/v1/me/data | jq
```

Response shape:

```json
{
  "principal": "api-key",
  "exported_at": "2026-05-30T18:00:00+00:00",
  "request_id": "...",
  "counts": { "classifications": 12, "audit_log": 47 },
  "classifications": [ /* full ClassificationRecord objects */ ],
  "audit_log": [ /* full audit rows */ ]
}
```

Erasure is hard-delete and irreversible. It removes every matching
`classifications` row, unlinks any blobs that live under `STORAGE_LOCAL_DIR`,
and removes every `audit_log` row owned by the principal. A `confirm=erase`
query parameter is required so accidental DELETEs return `400` instead of
wiping data:

```bash
curl -X DELETE -H "X-API-Key: $AUTH_API_KEY" \
  "https://host/v1/me/data?confirm=erase"
```

Classifications are tagged with their owning principal at write time via the
`principal` column on the `classifications` table (Alembic migration
`0003_classification_principal`). Rows written before the migration have
`principal = NULL` and are therefore not returned by export and not removed by
erasure; operators handling pre-migration data should backfill the column from
the corresponding audit rows before relying on `/v1/me/data` for compliance
reports.

The DELETE call itself is audited by `AuditLogMiddleware` after the response
is sent, so the erasure action remains forensically visible without retaining
any user payload.

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

### CORS and security headers

The API ships a hardened CORS allowlist and a baseline set of HTTP security
response headers, both driven by `Settings` so operators can tune them
without code changes.

CORS is configured via four env vars:

| Variable                  | Default                                                              | Notes                                                                |
| ------------------------- | -------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `CORS_ALLOWED_ORIGINS`    | `*`                                                                  | Comma-separated origin list. Wildcard is only honored in `development`. |
| `CORS_ALLOW_CREDENTIALS`  | `false`                                                              | When `true`, cookies and `Authorization` may cross origins. Ignored when origins contain `*`. |
| `CORS_ALLOWED_METHODS`    | `GET,POST,PUT,PATCH,DELETE,OPTIONS`                                  | Methods echoed in the preflight response.                            |
| `CORS_ALLOWED_HEADERS`    | `Authorization,Content-Type,X-API-Key,X-Request-ID,X-Tenant`         | Request headers allowed on cross-origin calls.                       |

When `APP_ENV` is `staging` or `production`, any `*` entry in
`CORS_ALLOWED_ORIGINS` is silently dropped. If the resulting allowlist is
empty the API fails closed and no cross-origin browser traffic is accepted,
so you must set an explicit list before deploying. `X-Request-ID` is exposed
to browsers so client-side observability can correlate failures with server
logs and traces.

`SecurityHeadersMiddleware` is registered as the outermost middleware so
every response, including 401s from auth and 429s from rate limiting,
carries the baseline header set:

| Header                          | Default value                                                                                                              |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `Content-Security-Policy`       | `default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'` |
| `X-Content-Type-Options`        | `nosniff`                                                                                                                  |
| `X-Frame-Options`               | `DENY`                                                                                                                     |
| `Referrer-Policy`               | `strict-origin-when-cross-origin`                                                                                          |
| `Permissions-Policy`            | `accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()`            |
| `Cross-Origin-Opener-Policy`    | `same-origin`                                                                                                              |
| `Cross-Origin-Resource-Policy`  | `same-origin`                                                                                                              |
| `Strict-Transport-Security`     | `max-age=31536000; includeSubDomains` (production only)                                                                    |

HSTS is only emitted when `APP_ENV=production` so dev and staging clusters
running on plain HTTP do not pin browsers onto HTTPS-only behavior. Each
header is set with `setdefault`, so a downstream route or middleware that
needs to override one (for example a relaxed CSP on an embeddable widget)
can still do so. Set `SECURITY_HEADERS_ENABLED=false` to disable the
middleware entirely; tune `SECURITY_CSP`, `SECURITY_HSTS_MAX_AGE`,
`SECURITY_REFERRER_POLICY`, or `SECURITY_PERMISSIONS_POLICY` to override
individual values.

Regression coverage lives in `tests/test_security_headers.py`, which
asserts the baseline headers on `/healthz`, verifies they still ride on 401
responses, exercises the production-only HSTS gate, and confirms the
staging/production CORS allowlist rejects wildcards and unknown origins.

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

### Access logs and trace correlation

Every HTTP request flows through `RequestIdMiddleware`, which:

- Honours an inbound `x-request-id` header or mints a fresh hex uuid, then
  echoes it back as `x-request-id` so clients can quote it in bug reports.
- Binds `request_id`, `path`, and `method` into the structlog contextvars so
  every downstream log line (auth, audit, application, errors) carries the
  same correlation id without any extra plumbing.
- When OpenTelemetry is enabled (`OTEL_ENABLED=true`) and a span is
  recording for the request, also binds `trace_id` and `span_id` into the
  log context and echoes `x-trace-id` on the response. This makes it a
  single click in Grafana, Tempo, Jaeger, Honeycomb, or Sentry to jump
  from a log line to the matching trace and back.
- Emits exactly one `http.access` structured log per request after the
  response is produced, including `status`, `latency_ms`, `principal`
  (authenticated subject when present), and `client` (peer IP). The log
  fires even when the handler raises, so 5xx storms are visible without
  scraping uvicorn's stdout.

Example line in `APP_LOG_FORMAT=json` mode:

```json
{"event": "http.access", "level": "info", "request_id": "7296f9b4...",
 "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "span_id": "00f067aa0ba902b7",
 "path": "/v1/classify", "method": "POST", "status": 200,
 "latency_ms": 412.7, "principal": "apikey:operator", "client": "10.0.3.4"}
```

For on-call: when a user reports a slow or failed request, ask for the
`x-request-id` (and `x-trace-id` if present) from their response headers,
then grep logs by `request_id=` to pull the full per-request slice across
the API, the audit middleware, and any RQ jobs that re-bind the same id.

`tests/test_request_id.py` guards id propagation, the access log shape,
and OTEL trace header emission.

### Deploy

Production deployments use the Helm chart in `infra/helm/shotclassify`. The
chart ships a multi-stage Dockerfile (`infra/docker/Dockerfile`), HPA, network
policy, and configurable resource limits. CI runs lint + tests + build on every
push via `.github/workflows/ci.yml`, plus a dedicated `helm` job that runs
`helm lint` and renders the chart with default and feature-flag value sets so
templating regressions fail before merge.

### Availability and pod security

Every workload in the chart (`api`, `worker`, `web`) is hardened to the same
baseline:

- Pod `securityContext`: `runAsNonRoot: true`, uid/gid 10001, `fsGroup` 10001,
  `seccompProfile.type: RuntimeDefault`.
- Container `securityContext`: `allowPrivilegeEscalation: false`,
  `capabilities.drop: ["ALL"]`.
- CPU and memory `requests` and `limits` set in `values.yaml`
  (`resources.api|worker|web`).
- Liveness probe on every container. The API and web pods use HTTP probes
  (`/healthz`, `/`); the RQ worker pod uses an `exec` probe that pings Redis
  via `python -c "import os,redis;redis.Redis.from_url(os.environ['REDIS_URL']).ping()"`,
  which fails fast if the broker connection is lost (RQ workers do not expose
  HTTP).
- PodDisruptionBudgets in `infra/helm/shotclassify/templates/pdb.yaml` keep at
  least one `api` and one `worker` pod available during voluntary disruptions
  (node drains, cluster upgrades, autoscaler evictions). Tune or disable per
  workload via `pdb.<api|worker|web>.{enabled,minAvailable}` in `values.yaml`.
  The `web` PDB is opt-in because most installs run a single replica.

`tests/test_helm_chart.py` enforces these properties by running `helm lint`
and `helm template`, then asserting that every rendered `Deployment` runs
non-root with `ALL` capabilities dropped, declares resource requests and
limits, has a `livenessProbe`, and that the default render contains the
expected PodDisruptionBudgets. The suite skips cleanly if `helm` is not on
PATH, and the CI `helm` job installs Helm v3 so the same checks run on
every push.

### Health and readiness

Two probes with deliberately different contracts so Kubernetes does the right
thing under partial outages.

- `GET /healthz` is liveness. It returns `200 {"status":"ok"}` as long as the
  process can serve HTTP. It does not touch the database, Redis, or storage,
  so a backing service blip will not cause the kubelet to restart the pod.
- `GET /readyz` is a deep readiness probe. It actively checks each hard
  dependency and returns **HTTP 503** with a per-check breakdown when any of
  them is degraded, so the pod is pulled out of the Service endpoints until
  it recovers. Checks:
  - `db` runs `SELECT 1` against the configured `DATABASE_URL`.
  - `storage` verifies `STORAGE_LOCAL_DIR` exists and is writable.
  - `redis` pings `REDIS_URL` with a 2 second timeout. Required outside
    `APP_ENV=development` so a missing queue fails the probe in staging and
    production; treated as advisory in dev so a local laptop without Redis
    still serves traffic.

Example healthy response:

```json
{
  "status": "ready",
  "checks": {
    "db": {"status": "ok"},
    "storage": {"status": "ok"},
    "redis": {"status": "ok"}
  }
}
```

Example degraded response (HTTP 503), exactly what an operator wants to see in
a probe-failure event:

```json
{
  "status": "degraded",
  "checks": {
    "db": {"status": "error", "detail": "OperationalError: connection refused"},
    "storage": {"status": "ok"},
    "redis": {"status": "ok"}
  }
}
```

The Helm chart already wires `/healthz` to `livenessProbe` and `/readyz` to
`readinessProbe` on the API deployment, so no extra configuration is needed.

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

### Alerting (PrometheusRule)

The Helm chart ships a `PrometheusRule` covering availability, error rate,
latency, and saturation. It is opt-in so installs without the Prometheus
Operator do not fail to render. Enable it by setting
`metrics.prometheusRule.enabled=true` and labelling it so your Prometheus
instance picks it up:

```yaml
metrics:
  prometheusRule:
    enabled: true
    labels:
      release: kube-prometheus-stack   # matches Prometheus ruleSelector
    downFor: 2m
    errorRateThreshold: 0.05           # 5% 5xx over 10m -> warning
    exceptionRatePerSec: 0.1           # unhandled exceptions per second
    latencyP95Seconds: 2.5             # route p95 over 15m -> warning
    inFlightThreshold: 50              # sustained queue depth
```

Alerts fired by the rule, each carrying a `runbook_url` that points back at
this section:

- `ShotclassifyApiDown` (critical): no successful scrape for `downFor`.
- `ShotclassifyApiHighErrorRate` (warning): 5xx ratio over threshold for 10m.
- `ShotclassifyApiHighExceptionRate` (warning): unhandled exceptions/s over
  threshold for 10m. Cross-check Sentry for stack traces.
- `ShotclassifyApiHighLatencyP95` (warning): per-route p95 above threshold
  for 15m. Check upstream LLM, OCR, DB, and CPU saturation.
- `ShotclassifyApiInFlightSaturation` (warning): in-flight requests above
  threshold for 10m. Scale `replicaCount.api` or investigate slow
  downstreams.

Rule structure is pinned by `tests/test_helm_prometheus_rule.py`, which
renders the chart with the rule on and asserts the alert set, severities,
runbook links, and that the expressions still reference the metric names
emitted by `services/api/app/middleware/metrics.py`. A metric rename will
fail the test before it silently breaks paging.

### Error tracking (Sentry)

The API and worker initialize the Sentry SDK in their startup hooks via
`shotclassify_common.init_sentry`. Initialization is a no-op unless
`SENTRY_DSN` is set, so local development and CI never emit events.

Relevant environment variables (see `.env.example`):

```
SENTRY_DSN=                       # leave empty to disable
SENTRY_RELEASE=                   # e.g. git sha; tags events with a release
SENTRY_SAMPLE_RATE=1.0            # error sampling, 0.0 to 1.0
SENTRY_TRACES_SAMPLE_RATE=0.0     # performance traces, 0.0 to 1.0
SENTRY_PROFILES_SAMPLE_RATE=0.0   # profiles, 0.0 to 1.0
```

The wiring is opinionated for safety:

- `send_default_pii=False` so user identifiers are not auto-attached.
- A `before_send` scrubber strips `Authorization`, `Cookie`, `X-API-Key`,
  and `X-Auth-Token` request headers, clears request cookies, replaces the
  raw `QUERY_STRING` env entry, and filters any `extra` field whose name
  contains `key`, `secret`, or `token`.
- Starlette, FastAPI, and standard-library logging integrations are enabled.
  Log records at `ERROR` and above are forwarded as events; everything from
  `INFO` and above becomes a breadcrumb.

In Kubernetes, enable Sentry by setting both flags in `values.yaml`:

```yaml
sentry:
  enabled: true
  release: "v0.1.0"
secret:
  sentryDsn: "https://<public>@<host>/<project>"
```

The Helm chart injects `SENTRY_DSN` from the chart's existing Opaque secret
(`<release>-shotclassify-secret`, key `sentry-dsn`); the other Sentry knobs
ride along as plain env on the API deployment.

For ad hoc capture inside application code use
`shotclassify_common.capture_exception(exc)`, which returns the Sentry event
id when initialized and `None` otherwise; it never raises.

## License

MIT. See `LICENSE`.
