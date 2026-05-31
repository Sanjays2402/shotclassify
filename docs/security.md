# Security

## Threat model

ShotClassify is single-tenant by design. It runs on a developer's laptop or a private cluster behind a VPN. The threat model:

- An attacker on the same network attempts to call the API without credentials.
- A malicious uploaded image attempts to trigger code execution via OCR or the LLM.
- A leaked log file exposes sensitive screenshot text.

## Mitigations

- **Auth required** by default (`AUTH_ENABLED=true`). API key (`X-API-Key`) for CLI/Shortcut, GitHub OAuth + signed cookie for the web UI.
- **Allowlist** the GitHub login via `AUTH_ALLOWED_GITHUB_LOGIN`.
- **No shelling out on user input**: extractors are pure regex / pure Python. The router only invokes whitelisted actions defined in YAML.
- **Action engine defaults to dry-run**. Real side effects require an explicit YAML flip.
- **No secrets in logs**: structlog config strips `Authorization`, `X-API-Key`, and `Cookie` headers (handled by the middleware boundary).
- **Image inputs**: Tesseract runs in a subprocess; we never exec OCR text. Images are saved by hash under the configured storage root.
- **Per-tenant IP allowlist**: each tenant can configure a list of CIDR ranges that gate API and dashboard access. Enforced at the middleware layer before any route handler. Healthcheck and metrics endpoints are exempt so liveness probes never trip. Configure under `/settings/security` or via `PUT /v1/settings/security/ip-allowlist`.
- **Outbound webhook egress allowlist** (`packages/store/src/shotclassify_store/webhook_egress.py`): webhook URLs are tenant-controlled, which makes the dispatcher a textbook SSRF sink. Before every delivery (and again at subscription create time) the URL is parsed, the hostname is resolved, and every A/AAAA record is checked. Loopback, private (RFC1918, ULA), link-local, multicast, CGNAT, cloud-metadata (169.254.0.0/16) and operator-configured CIDR ranges are refused. Plain `http://` is refused unless `WEBHOOK_EGRESS_ALLOW_HTTP=true`. Egress denials skip the retry loop and surface as `egress blocked: <reason>` in the audit-replay UI so the tenant gets an actionable error without leaking internal topology. Set `WEBHOOK_EGRESS_EXTRA_BLOCKED_CIDRS` (comma-separated) to deny additional ranges (e.g. your VPC supernet).

## Reporting

Open a private security advisory on the repo. No bug-bounty programme.
