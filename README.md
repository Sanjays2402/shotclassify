# ShotClassify

![landing](docs/screenshots/landing.png)


Drop a screenshot. Get a classification, extracted content, and a suggested action.

ShotClassify is a local-first screenshot triage system. It combines a vision LLM (any OpenAI-compatible endpoint, default: the GitHub Copilot proxy at `http://127.0.0.1:4141/v1`) with local Tesseract OCR. Each image is sorted into one of nine categories, parsed by a category-specific extractor, and routed to a configurable action (save to folder, copy code to clipboard, file a bug repro, post to Slack).

## Categories

`receipt`, `code_snippet`, `error_stacktrace`, `chat_screenshot`, `meme`, `document`, `ui_mockup`, `chart`, `other`.

## Architecture

```
+----------+      +------------------+      +-------------------+
|  Web /   | ---> |  FastAPI :7441   | ---> |  Redis RQ worker  |
|  CLI /   |      |  multipart api   |      |  parallel classify|
|  macOS   |      +---------+--------+      +---------+---------+
+----------+                |                         |
                            v                         v
                  +---------+----------+    +---------+---------+
                  |  packages/ocr      |    |  packages/classify|
                  |  tesseract+deskew  |    |  vision LLM       |
                  +---------+----------+    +---------+---------+
                            |                         |
                            +------------+------------+
                                         v
                              +----------+----------+
                              |  packages/extract   |
                              |  pydantic schemas   |
                              +----------+----------+
                                         v
                              +----------+----------+
                              |  packages/route     |
                              |  YAML action rules  |
                              +----------+----------+
                                         v
                              +----------+----------+
                              |  packages/store     |
                              |  SQLite or Postgres |
                              +---------------------+
```

## Quick start

```
brew install tesseract redis
uv sync
cp .env.example .env
uv run shotclassify classify samples/fake-receipt.png
```

Spin up the full stack with `docker compose -f infra/docker/docker-compose.dev.yml up`.

## Auth

Single-user OAuth (GitHub) for the web UI. CLI and macOS Shortcut use an API key issued from the settings page and sent as `X-API-Key`.

## Action engine

`packages/route/rules.example.yaml` maps categories to actions. Actions are dry-run by default. Enable execution per category once you trust the calibration.

## Repository layout

| path | role |
| --- | --- |
| services/api | FastAPI on :7441 |
| services/worker | Redis RQ worker |
| packages/classify | Vision LLM client + prompts |
| packages/ocr | Tesseract wrapper + preprocessing |
| packages/extract | Pydantic extractors per category |
| packages/route | Action router |
| packages/store | SQLite or Postgres history |
| packages/common | Settings, logging, telemetry |
| cli | `shotclassify` CLI |
| web | Next.js 15 UI |
| macos/ShortcutInstaller | macOS Quick Action installer |
| infra | Dockerfile, compose, helm, terraform |
| samples | Synthetic test images |

## License

MIT. See LICENSE.
