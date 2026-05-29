# Calibration

Confidence thresholds live per-category in `packages/route/rules.example.yaml` under `min_confidence`. Tune them before flipping `dry_run: false` in production.

## Procedure

1. Run a corpus through the API in dry-run mode.
2. Use the **History** page to skim results; correct mis-classifications via the Review screen.
3. Export user corrections (planned: `GET /v1/history?correctedOnly=true`).
4. Look at the per-category confusion to pick thresholds that keep precision above your bar.
5. Flip `defaults.dry_run: false` and lower thresholds carefully.

## Targets

| Category | starting threshold | rationale |
|---|---|---|
| receipt | 0.70 | filesystem write |
| code_snippet | 0.60 | clipboard mutation |
| error_stacktrace | 0.65 | opens an issue draft |
| chart, document, ui_mockup, chat, meme | 0.55 | low-risk save |
| other | 0.00 | no-op |
