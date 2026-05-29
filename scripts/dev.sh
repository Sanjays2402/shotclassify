#!/usr/bin/env bash
# Bootstrap a dev environment.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo "install uv first: https://docs.astral.sh/uv/"; exit 1; }
[ -f .env ] || cp .env.example .env
uv sync || true
uv pip install -e packages/common -e packages/ocr -e packages/classify -e packages/extract \
               -e packages/route -e packages/store -e cli
echo "ready. try: uv run shotclassify classify samples/fake-receipt.png"
