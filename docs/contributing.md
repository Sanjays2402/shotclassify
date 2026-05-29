# Contributing

ShotClassify is a personal project but PRs are welcome.

## Setup

```
brew install tesseract redis
make install
make samples
pytest -q
```

## Layout reminder

- `packages/common/` — schemas, settings, logging
- `packages/{ocr,classify,extract,route,store}/` — single-responsibility libraries
- `services/{api,worker}/` — process-level entrypoints
- `cli/` — `shotclassify` Typer CLI
- `web/` — Next.js UI
- `infra/` — Docker, Helm, Terraform

## Conventions

- Python: Ruff (`make lint`, `make fmt`), 110 col, type hints encouraged.
- Tests: pytest. Add a test for every parser change.
- Prompts: keep category-specific guidance in `packages/classify/.../templates/`.
- No em-dashes in user-facing strings.

## Adding a category

1. Add the enum member in `packages/common/.../schemas.py::Category`.
2. Add a `Fields` model alongside, plus optional discriminator in `ExtractedFields`.
3. Add a prompt hint in `packages/classify/.../prompts.py::CATEGORY_HINTS` and a template file.
4. Add an extractor in `packages/extract/.../<name>.py` and wire it in `pipeline.enrich`.
5. Add a row in `packages/route/rules.example.yaml`.
6. Add unit tests and a synthetic fixture under `fixtures/synth/<name>/`.
