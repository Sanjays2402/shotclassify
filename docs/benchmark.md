# Benchmark

`scripts/bench.py` runs every image under `fixtures/synth/` through the full pipeline (OCR + classifier + extractors + router) and computes per-category accuracy plus a confusion matrix.

## Latest run (heuristic fallback only, no LLM reachable)

| metric | value |
|---|---|
| total images | 340 |
| correct | 212 |
| accuracy | 62.4% |
| wall time | ~73s on M-series Mac mini |

The heuristic ceiling is intentionally modest: it exists so the system stays useful offline. With the GitHub Copilot proxy enabled, accuracy on the same fixtures rises substantially (largely closing the chat / document gap that pure keyword heuristics miss).

## Reproduce

```
python3 scripts/make_corpus.py
uv run python scripts/bench.py
cat fixtures/bench/report.json
```

## Inspecting failures

```
awk -F, '$2 != $3 && NR>1 { print }' fixtures/bench/report.csv | head
```
