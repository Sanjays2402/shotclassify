# Security policy

ShotClassify takes vulnerability reports seriously. This document is the
single source of truth for how to reach the security team, what is in
scope, and what response timeline you can expect. It is mirrored at
[`/.well-known/security.txt`](./services/api/app/routes/well_known.py)
(RFC 9116) so enterprise procurement scanners and bug-bounty crawlers
can discover it automatically.

## Reporting a vulnerability

Email **security@shotclassify.dev** with a clear description, steps to
reproduce, and the impact you observed. PGP-encrypted reports are
welcome; the operator-configured `Encryption:` URL in security.txt
points at the active key.

Please do not open a public GitHub issue for security reports. Issues
discovered during legitimate testing on your own deployment of
ShotClassify (self-hosted) are still in scope as long as the disclosure
goes through this channel.

## What is in scope

- The API service (`services/api`) and worker (`services/worker`)
- The web dashboard (`web/`)
- The Python packages under `packages/`
- The container images published from this repository

What is **not** in scope:

- Third-party dependencies (file those upstream and CC us)
- Findings that require physical access or a malicious operator already
  in possession of the database
- Reports that depend on a misconfigured deployment with the documented
  production hardening turned off (CORS wildcard, `AUTH_ENABLED=false`,
  the dev API key still set, sqlite in production, missing
  `APP_SECRET_KEY`). Production-validation already refuses to start in
  these states; see `validate_for_production` in
  `packages/common/src/shotclassify_common/settings.py`.

## Response targets

| Severity | Acknowledgement | Status update | Fix or mitigation |
|----------|-----------------|---------------|-------------------|
| Critical | 1 business day  | 3 business days | 7 days |
| High     | 2 business days | 5 business days | 14 days |
| Medium   | 3 business days | 10 business days | 30 days |
| Low      | 5 business days | best-effort     | best-effort |

Public disclosure happens after a fix is available and customers have
had a reasonable window to upgrade. Confirmed reports are credited in
the `Acknowledgments:` URL with the researcher's permission.

## Signed commits

Maintainer commits to `main` are signed with the maintainer's GPG or
SSH signing key. Verify with `git log --show-signature`. Contributors
are encouraged but not required to sign their commits; signed PRs
shorten review for any change touching authentication, authorization,
audit logging, or outbound network code.

## Hardening defaults that ship with the repo

- Per-tenant IP allowlist (CIDR), enforced in middleware before any
  route handler runs.
- Per-API-key source-IP allowlist with the same enforcement point.
- Per-tenant configurable session TTL plus idle (inactivity) timeout.
- MFA (TOTP) with single-use recovery codes; admin-action step-up for
  destructive endpoints (webhook replay, API-key creation, etc).
- Workspace-enforced MFA enrolment policy and SSO-only sign-in policy.
- Per-tenant OIDC IdP so customers can plug their own Okta / Azure AD /
  Google Workspace without sharing credentials with the SaaS vendor.
- Webhook egress is SSRF-hardened: scheme/port allowlist, A/AAAA
  resolution before connect, pinned-IP HTTP so DNS-rebinding cannot
  escape the check, hard block on cloud-metadata, link-local, CGNAT,
  and operator-extensible private CIDRs.
- HMAC-signed webhook deliveries with rotation overlap so a customer
  can roll the signing key without dropping events.
- Append-only audit log with a per-tenant hash chain that detects out
  of band tampering on replay.
- Prometheus `/metrics`, structured JSON logs, OpenTelemetry tracing,
  `/healthz` (liveness) and `/readyz` (deep dependency probe).
- Production-validation refuses to start when wildcard CORS, sqlite,
  the dev API key, or a missing `APP_SECRET_KEY` would otherwise ship.

## Reaching us out of band

For coordinated disclosure of an actively exploited issue, escalate by
email with subject `URGENT-SEC` and we will reply with a callback
channel. The contact in `/.well-known/security.txt` is monitored
during business hours; for incidents that cannot wait, follow the
escalation steps in `docs/security.md`.
