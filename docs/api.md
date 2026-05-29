# API Reference

Base: `http://127.0.0.1:7441`

Auth: `X-API-Key: <token>` for non-browser callers; session cookie for the web UI.

## Health

- `GET /healthz` — liveness
- `GET /readyz` — readiness with DB + LLM url snapshot

## Classify

- `POST /v1/classify` — multipart, field `file=@image.png`, optional `note=...`. Returns `ProcessResult`.
- `POST /v1/classify/batch` — multipart, repeated `files=@a.png` `files=@b.png`. Returns `ProcessResult[]`.
- `POST /v1/classify/{id}/reclassify` — re-runs the pipeline against the original stored image.
- `POST /v1/classify/{id}/correct` — body `category=receipt`. Stores user-supplied label as training data.
- `POST /v1/queue` — enqueues to Redis RQ when available; falls back to FastAPI BackgroundTasks.

## History

- `GET /v1/history?limit=50&category=receipt&q=needle` — list with filters and full-text query.
- `GET /v1/history/{id}` — single record.
- `GET /v1/history/stats` — total count.
- `DELETE /v1/history/{id}` — remove a record.

## Settings

- `GET /v1/settings/rules` — current YAML rules + parsed dict.
- `PUT /v1/settings/rules` — body `{"yaml": "..."}` to update.
- `GET /v1/settings/env` — sanitised effective config (no secrets).

## Models

See `packages/common/src/shotclassify_common/schemas.py` for the canonical Pydantic types.
