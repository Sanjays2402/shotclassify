# Architecture

## Overview

ShotClassify is a four-stage pipeline wrapped behind an API, a CLI, and a Next.js UI.

1. **OCR** — Tesseract with light preprocessing (deskew, denoise, Otsu binarisation). Confidence and language detection ride along.
2. **Classify** — A vision LLM (any OpenAI-compatible endpoint) sees the raw image plus the OCR transcript and returns a primary category, calibrated confidences for all nine categories, and structured fields.
3. **Extract** — Category-specific extractors fill gaps the LLM missed. Receipt parsing uses pure regex over the OCR transcript. Code language detection uses Pygments. Error parsing recognises Python tracebacks, Node.js stacks, and JVM exception lines.
4. **Route** — A YAML rules file maps categories (and minimum confidence) to actions. Actions run in dry-run mode by default. Real execution: save to folder, copy to clipboard, post to Slack webhook, open a templated URL (great for filing GitHub issues from stack traces).

History is persisted in SQLAlchemy (SQLite in dev, Postgres in compose/Helm). Blobs sit on disk (local) or S3 (prod) via a `BlobStore` abstraction.

## Process model

```
Client --(multipart)--> FastAPI /v1/classify --inline--> pipeline.process_image
                                          \-> /v1/queue --> Redis RQ --> worker.process_image_job --> pipeline.process_image
```

Inline classification keeps the API responsive for one-shot uploads. Batch and macOS Shortcut hits go through the queue so the API stays snappy.

## Threading / parallelism

- Multi-image upload runs `asyncio.gather` over `asyncio.to_thread(process_image, ...)` so OCR and the LLM call happen in parallel without blocking the event loop.
- The worker scales horizontally by pod count.

## Auth

- Single-user GitHub OAuth (sign in via `/auth/login`, signed cookie via itsdangerous).
- `X-API-Key` header for CLI / macOS Shortcut.

## Telemetry

Structlog JSON logs everywhere. Optional OpenTelemetry: when `OTEL_ENABLED=true` the API auto-instruments FastAPI and ships OTLP gRPC spans.

## Failure modes

- LLM unreachable: a heuristic classifier kicks in based on OCR keywords so the system stays useful offline (and during CI).
- Tesseract missing: OCR returns an empty string, classification still runs from the image.
- Redis missing: `/v1/queue` falls back to FastAPI BackgroundTasks.
