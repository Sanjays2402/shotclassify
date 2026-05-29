#!/usr/bin/env bash
# Dogfood the CLI end-to-end against the synthetic samples.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/make_samples.py >/dev/null
for f in samples/*.png; do
  echo "==> $f"
  uv run shotclassify classify "$f" --pretty || true
  echo
done
