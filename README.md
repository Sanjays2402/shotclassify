# shotclassify

Shot classification API and dashboard for tagging images and video frames by camera shot type with a multi-tenant, audit-friendly workspace.

## What's new: signed Trust Pack for procurement reviewers

Enterprise procurement asks the same question at the end of every deal: "send us your security policy, sub-processor list, SSO/MFA/IP/retention settings for our workspace, and prove the bundle wasn't edited in transit." ShotClassify now answers in one call. `GET /v1/trust/pack` streams a deterministic ZIP containing this workspace's `SECURITY.md`, full policy snapshot (`policy.json` with SSO, OIDC, MFA, session, IP allowlist, CORS origins, API key TTL/inactivity/max-active policies, audit and history retention, privacy settings), the current sub-processor catalog, and this workspace's acknowledgement state. Every file is hashed (SHA-256) into a `manifest.json` and the manifest itself is signed with HMAC-SHA256 using the deployment's `app_secret_key`. The signature is also returned in the `X-Trust-Pack-Signature` response header so an automated procurement pipeline can verify without unzipping. `GET /v1/trust/pack/manifest` returns the same per-file hashes and signature without the ZIP bytes, so a reviewer can audit the shape first. Both endpoints are admin-role and strictly tenant-scoped: an `acme` admin can never enumerate `globex`'s policies. Coverage in `tests/test_trust_pack.py` proves member denial, unauthenticated denial, that the in-header signature matches the in-zip manifest, that per-file SHA-256s match the bytes actually written, and that two tenants get distinct bundles.

Try it (local):

```bash
make api          # FastAPI on http://127.0.0.1:7441

curl -s -OJ "http://127.0.0.1:7441/v1/trust/pack" \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY"
# -> shotclassify-trust-pack-<workspace>.zip with signed manifest.json

curl -s "http://127.0.0.1:7441/v1/trust/pack/manifest" \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY" | jq
```

## What's new: expiring-credentials report for proactive API key rotation

Enterprise security teams want one number on the admin dashboard: how many credentials will silently die in the next 30 days, and which ones. ShotClassify now answers that question as a first-class report. `GET /v1/api-keys/expiring?within_days=30` returns every active (non-revoked) key whose `expires_at` falls inside a rolling window, soonest-first, so the rotation queue is already sorted. Already-expired but not-yet-revoked keys are always included so an overdue rotation cannot be hidden by a short window. Keys with no `expires_at` (never-expire) are excluded so the dashboard only surfaces actionable work. The report is strictly tenant-scoped (a workspace admin cannot enumerate another workspace's lifecycle) and admin-role + admin-scope gated, matching the rest of the keys surface. The admin console at `/admin` renders an amber banner above the API keys section whenever any active key is expiring inside 30 days, linking straight to `/keys` so an operator can rotate before any production traffic 401s. Coverage in `tests/test_api_key_expiring.py` proves soonest-first ordering, the never-expire and revoked exclusions, cross-tenant isolation between two admin keys, and that an already-overdue key still surfaces.

Try it (local):

```bash
make api          # FastAPI on http://127.0.0.1:7441
make web          # Next.js admin on http://localhost:3000

curl -s "http://127.0.0.1:7441/v1/api-keys/expiring?within_days=30" \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY" | jq

# UI: http://localhost:3000/admin -> amber banner shows expiring count
```

## What's new: per-tenant allowed email domains for invites, SCIM, and SSO auto-join

Every enterprise security questionnaire eventually asks: "can your platform refuse to let one of our admins invite a personal gmail address into our regulated workspace." shotclassify now exposes a per-tenant allowed-email-domains policy that gates every membership entry path. A workspace admin sets the list with `PUT /v1/settings/security/invite-domains` (admin role + fresh MFA step-up), and once it is non-empty the store layer refuses to create an invitation, accept an SSO auto-join, or honour a SCIM `Users` POST whose email domain is not on the list. Entries support both the bare domain (`acme.com`) and the leading-dot wildcard (`.acme.com`) which also matches every sub-domain, so a workspace can permit `acme.com` and `.corp.acme.com` without enumerating every team. The check lives in `tenant_settings.email_matches_allowed_domains` and is wired into `memberships_store.create_invitation` (REST invitations), `services/api/app/routes/sso.py` (SSO callback + test issue), and `services/api/app/routes/scim.py` (IdP provisioning) so a future caller cannot bypass the policy by skipping the route. Out-of-policy invitations return HTTP 422 `invite_domain_not_allowed` with the offending email and the allowed list so the dashboard can point the admin at the exact rule that blocked them; SCIM returns `400 invalidValue`; SSO auto-join silently no-ops to avoid breaking sign-in. The policy is strictly tenant-scoped: a lockdown on `acme` never affects an invitation in `globex`, and the test suite asserts this with two parallel admin keys. Empty list = no policy (legacy behaviour); maximum 64 domains per tenant; every change goes through the audit middleware with actor, IP, request id and tenant. Coverage lives in `tests/test_allowed_invite_domains.py` (read default, normalize + dedupe, invalid domain rejected, REST invite blocked + structured payload, sub-domain wildcard accepted, cross-tenant isolation, SCIM provision blocked, direct store-layer enforcement).

Try it (local):

```bash
# API: http://127.0.0.1:7441
make api  # in another shell

# Read current policy (empty = no enforcement)
curl -s -H "X-API-Key: $ADMIN_KEY" \
  http://127.0.0.1:7441/v1/settings/security/invite-domains

# Lock invitations to the acme.com domain and every acme.com sub-domain
curl -s -X PUT -H "X-API-Key: $ADMIN_KEY" \
  -H "content-type: application/json" \
  -d '{"allowed_domains":["acme.com",".corp.acme.com"]}' \
  http://127.0.0.1:7441/v1/settings/security/invite-domains

# Personal address is refused with a structured error payload
curl -i -X POST -H "X-API-Key: $ADMIN_KEY" \
  -H "content-type: application/json" \
  -d '{"email":"someone@gmail.com","role":"viewer"}' \
  http://127.0.0.1:7441/v1/invitations

# Disable the policy by sending an empty list
curl -s -X PUT -H "X-API-Key: $ADMIN_KEY" \
  -H "content-type: application/json" \
  -d '{"allowed_domains":[]}' \
  http://127.0.0.1:7441/v1/settings/security/invite-domains
```

## What's new: emergency freeze (workspace-wide write lockdown)

Every enterprise security questionnaire eventually asks: "if one of our admins is suspected of compromise at 02:00, can your platform stop accepting writes from that workspace before we finish the incident call." shotclassify now exposes a one-switch tenant-wide freeze that does exactly that. A workspace admin engages it with `POST /v1/settings/security/freeze` (admin role + fresh MFA step-up) with a required `reason`. While engaged, a new `FreezeMiddleware` rejects every `POST`, `PUT`, `PATCH` and `DELETE` request scoped to that tenant with HTTP 423 `tenant_frozen` *before* the route handler runs, so a leaked session cookie or stolen API key cannot create, modify or delete anything in the workspace. Reads stay open on purpose so investigators, auditors, exporters and the audit-log UI keep working. A narrow allowlist of mutation paths is exempt from the lockdown so the owner can lift the freeze, satisfy MFA, and sign out without being trapped: `/v1/settings/security/freeze` itself, `/v1/mfa/...`, `/auth/logout`, `/v1/sessions/...`, and the healthchecks. `DELETE /v1/settings/security/freeze` clears the state. Cross-tenant isolation is enforced at the middleware layer: a freeze on workspace `acme` does not affect workspace `globex` even though both run in the same API process, and the test suite asserts this with two parallel admin keys. The engaged reason, timestamp and engaging principal are persisted on `tenant_settings` so the dashboard banner names who is currently holding the lockdown and when, and both engage/lift go through the existing audit middleware with actor, IP, request id and tenant. Manage it interactively at `Settings -> Security -> Emergency freeze`. Coverage lives in `tests/test_tenant_freeze.py` (RBAC on read, reason validation on engage, blocked-write 423 plus cross-tenant isolation, and the exempt-lift recovery path).

Try it (local):

```bash
# API: http://127.0.0.1:7441
make api  # in another shell

# Read current state (admin)
curl -s -H "X-API-Key: $ADMIN_KEY" \
  http://127.0.0.1:7441/v1/settings/security/freeze

# Engage the freeze with a written reason
curl -s -X POST -H "X-API-Key: $ADMIN_KEY" \
  -H "content-type: application/json" \
  -d '{"reason":"Suspected leaked admin token"}' \
  http://127.0.0.1:7441/v1/settings/security/freeze

# Any write now returns 423 tenant_frozen
curl -i -X POST -H "X-API-Key: $ADMIN_KEY" \
  -H "content-type: application/json" \
  -d '{"name":"blocked","filters":{}}' \
  http://127.0.0.1:7441/v1/saved-views

# Lift the freeze
curl -s -X DELETE -H "X-API-Key: $ADMIN_KEY" \
  http://127.0.0.1:7441/v1/settings/security/freeze
```

UI: open <http://127.0.0.1:3000/settings/security/freeze>.

## What's new: per-tenant webhook circuit breaker

A failing receiver should not pull the rest of the integration down with it. The new per-tenant policy `webhook_autodisable_threshold` is an opt-in circuit breaker on outbound webhooks. When set to a positive integer N, the dispatcher tracks consecutive failed deliveries per subscription and pauses the subscription the moment the count reaches N. A successful delivery resets the counter, so only sustained failure trips the breaker. Pausing (rather than revoking) preserves the signing secret, event filters, and delivery history, and a manual resume clears `auto_disabled_at`, `auto_disabled_reason`, and the consecutive-failure counter so the next trip starts from a clean state. The threshold is bounded 2 to 10000, NULL means no policy and existing behaviour, and the breaker only ever acts within a single tenant: workspace B's failing subscription cannot affect workspace A's, and B cannot read or set A's policy. The `GET` and `PUT` routes live at `/v1/settings/security/webhook-autodisable`, require the `admin` role, and the `PUT` requires MFA step-up; every change is captured by the standard audit middleware. Coverage in `tests/test_webhook_autodisable.py` proves the threshold fires after exactly N consecutive failures, a success between failures resets the counter, resume clears the auto-disable metadata, cross-tenant policy reads return the caller's empty policy (not the other tenant's), and out-of-range thresholds return `422`.

Try it (local):

```bash
# 1. Configure the breaker for this workspace (pause after 5 consecutive failures).
curl -sS -X PUT http://127.0.0.1:7441/v1/settings/security/webhook-autodisable \
  -H "X-API-Key: $API_KEY" -H 'content-type: application/json' \
  -d '{"threshold": 5}'

# 2. Inspect the resolved policy.
curl -sS http://127.0.0.1:7441/v1/settings/security/webhook-autodisable \
  -H "X-API-Key: $API_KEY"

# 3. Read a subscription back; the new fields ride alongside success_count.
curl -sS http://127.0.0.1:7441/v1/webhooks -H "X-API-Key: $API_KEY" \
  | jq '.webhooks[] | {id, status, consecutive_failure_count, auto_disabled_at, auto_disabled_reason}'
```

UI: open <http://127.0.0.1:3000/settings/security/webhook-autodisable>.

## Previously: send a signed test ping to any webhook subscription

Enterprise integrators always ask the same question before they wire shotclassify into their production receiver: "can we fire a synthetic event at our endpoint so we can confirm TLS, signature verification, our IP allowlist, and our handler code before any real classification flows." `POST /v1/webhooks/{id}/test` is that endpoint. It signs and delivers a one-shot `webhook.test` payload to the targeted subscription, regardless of the subscription's event filter, so operators do not have to first add a wildcard subscription just to verify the receiver. The ping carries the standard `X-Shotclassify-Signature`, `X-Shotclassify-Delivery`, and `X-Shotclassify-Subscription` headers plus an `X-Shotclassify-Test: true` marker so receivers can route it to a no-op handler in production. Every gate that protects real dispatch is enforced here too: the subscription must belong to the caller's tenant (cross-tenant requests get `404`, not `403`, so the existence of another tenant's id never leaks), the subscription must be active (paused or revoked returns `409`), the per-tenant webhook egress host allowlist still applies (blocked hosts produce a failed delivery row with the reason), and during a secret rotation overlap the request is dual-signed with `X-Shotclassify-Signature-Next` so receivers can roll the new secret in. The route is `admin` role and scope, requires MFA step-up, accepts `?dry_run=true` for a preview, and is recorded by the standard audit middleware against the targeted subscription id. The dispatch attempt is persisted as a normal `webhook_deliveries` row so the test shows up in the delivery feed, the SIEM export, and the audit trail, and it can be replayed through the existing `/v1/webhooks/deliveries/{id}/replay` path. Coverage in `tests/test_webhooks_api.py` exercises a real signed delivery to a local listener (signature verified with the plaintext secret), cross-tenant isolation, the operator-role denial, the dry-run preview, and the paused-subscription `409`.

Try it (local):

```bash
# API: http://127.0.0.1:7441
make api  # in another shell

# Create a subscription, save id + secret
WID=$(curl -sS -X POST http://127.0.0.1:7441/v1/webhooks \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY" \
  -H "content-type: application/json" \
  -d '{"url":"https://your.receiver.example.com/in","events":["classify.completed"]}' \
  | jq -r .webhook.id)

# Preview the test without sending
curl -sS -X POST "http://127.0.0.1:7441/v1/webhooks/$WID/test?dry_run=true" \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY"

# Fire a real signed test ping
curl -sS -X POST "http://127.0.0.1:7441/v1/webhooks/$WID/test" \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY"
```

## What's new: per-workspace audit log retention

Procurement reviewers ask two opposite questions about audit logs: GDPR-focused buyers want a documented upper bound ("prove you delete this within 365 days"), SOC 2 and HIPAA-focused buyers want a documented lower bound ("prove you keep this for at least three years"). Conflating those two clauses with the existing classifications retention window blocks both deals. shotclassify now exposes audit retention as a separate per-workspace policy. Admins set `audit_retention_days` via `PUT /v1/settings/security/audit-retention` (admin role, MFA step-up), where `null` or `0` keeps audit data indefinitely (the default and the SOC 2 stance) and a positive integer between 1 and 3650 schedules the next purge cutoff. `POST /v1/settings/security/audit-retention/run` triggers an immediate tenant-scoped purge for operators who just lowered the window; the worker's retention scheduler now runs the audit purge in the same pass as the classifications purge so no second cron is needed. The purge intentionally breaks the per-tenant audit hash chain for the deleted window and writes its own audit row recording the cutoff, the row count, and the trigger so the chain verifier reports an attributable, disclosed gap rather than tampering. Tenants on a legal hold are skipped and the response surfaces `held=true`. Cross-tenant isolation is enforced at the query layer: an admin running a purge in their own workspace cannot touch another workspace's audit rows even when those rows are older than their own window. Manage it interactively at `Settings -> Security -> Audit retention`. Coverage in `tests/test_audit_retention_policy.py` exercises RBAC on read and write, input validation, the legal-hold short-circuit, and the cross-tenant isolation property.

Try it (local):

```bash
# Read current policy (admin)
curl -s -H "X-API-Key: $ADMIN_KEY" \
  http://127.0.0.1:7441/v1/settings/security/audit-retention

# Set a 365-day window (admin + MFA step-up)
curl -s -X PUT -H "X-API-Key: $ADMIN_KEY" -H "content-type: application/json" \
  -d '{"audit_retention_days": 365}' \
  http://127.0.0.1:7441/v1/settings/security/audit-retention

# Manually run the purge for this workspace
curl -s -X POST -H "X-API-Key: $ADMIN_KEY" \
  http://127.0.0.1:7441/v1/settings/security/audit-retention/run
```

Web UI: <http://127.0.0.1:3000/settings/security/audit-retention>

## What's new: data subject access requests (DSAR) for GDPR and CCPA

When an EU or California data subject emails a buyer's privacy desk asking "what data does your shot-classifier vendor hold on me, and please delete it," the buyer needs a documented, auditable place to forward that request. shotclassify now ships one. A public `POST /v1/trust/dsar` lets the data subject (or their authorized agent) file a request without an account by naming the target `tenant_id`, picking `access`, `erasure`, or `rectification`, and supplying their email. The endpoint is exempt from auth, the per-tenant IP allowlist, and origin gating, the same way `/v1/trust/incidents` and `/v1/trust/subprocessors` already are, so a stranger on any network can submit. Submitters see only their ticket id, the receipt timestamp, and the statutory deadline (30 days, GDPR Article 12 §3); the full record is visible only to admins of the named tenant so prior requests cannot be enumerated. Admins of the workspace get `GET /v1/dsar` with status filters and per-status counts plus an `overdue` counter, `GET /v1/dsar/{id}` for the full record (state history, IP at intake, fulfillment summary), `PATCH /v1/dsar/{id}` to transition along `received -> verified -> fulfilled -> closed` (with `rejected` as a terminal branch), `GET /v1/dsar/{id}/footprint` to preview how many classifications and audit rows match the subject inside this tenant, and `POST /v1/dsar/{id}/fulfill` to either generate the Article 15 access export or perform the Article 17 erasure. Erasure hard-deletes matching classifications and intentionally retains audit-log rows under Article 17(3)(b) for legal-claims and our own SOC2 CC7.2 obligations; the fulfillment summary records both numbers. Every admin mutation requires the `admin` role and MFA step-up, flows through `AuditLogMiddleware` so the actor, IP, request id, and timestamp land in the tamper-evident audit chain, and supports `?dry_run=true` for preview. The state machine refuses out-of-order transitions (received -> closed returns 409). Cross-tenant isolation is enforced at the query layer: tenant B asking to read, mutate, or fulfill tenant A's ticket gets 404, not 403, so the existence of the id never leaks. Coverage in `tests/test_dsar.py` exercises public intake, cross-tenant 404 on read/patch/fulfill, the state machine guard, the access-fulfillment lifecycle, and input validation (5 tests).

Try it (local):

```bash
# API: http://127.0.0.1:7441
make api  # in another shell

# Public intake (no auth) -- a data subject files a request
curl -sS -X POST http://127.0.0.1:7441/v1/trust/dsar \
  -H "content-type: application/json" \
  -d '{"tenant_id":"acme","request_type":"access","subject_email":"jane@example.com","description":"Article 15 access request"}'

# Admin: list open tickets with per-status counts and overdue counter
curl -sS http://127.0.0.1:7441/v1/dsar \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY"

# Admin: preview the subject's footprint before fulfillment
curl -sS "http://127.0.0.1:7441/v1/dsar/$RID/footprint" \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY"

# Admin: verify identity, then fulfill (access -> export, erasure -> delete)
curl -sS -X PATCH "http://127.0.0.1:7441/v1/dsar/$RID" \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY" \
  -H "content-type: application/json" \
  -d '{"status":"verified","note":"ID confirmed via signed PDF"}'
curl -sS -X POST "http://127.0.0.1:7441/v1/dsar/$RID/fulfill?dry_run=true" \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY"
```

## Previously: pause and resume webhook subscriptions

Webhook subscriptions now have a third lifecycle state between `active` and the terminal `revoked`: `paused`. Operators hit `POST /v1/webhooks/{id}/pause` during a downstream incident to stop deliveries without throwing away the signing secret, event filters, or delivery history; `POST /v1/webhooks/{id}/resume` brings the subscription back online. The dispatcher and the replay path both skip paused subscriptions, so a paused webhook receives nothing even if events keep flowing for other subscribers in the tenant. Revoked subscriptions stay terminal: resume on a revoked id returns `410`, by design, so an operator who really did mean to delete can never get it back by accident. Both routes require the `admin` role and scope, MFA step-up, and accept `?dry_run=true` so a preview shows the `from_status` -> `to_status` transition without mutating anything. Every transition is written through the normal audit middleware with the actor, request id, and target subscription id. Tenant isolation is enforced at the query layer: tenant B asking to pause tenant A's subscription gets `404`, not `403`, so the existence of the id never leaks. Coverage in `tests/test_webhook_pause_resume.py` exercises the round trip, double-pause and double-resume `409`s, the revoked-is-terminal `410`, the dry-run preview, cross-tenant isolation, and the operator-role denial.

Try it (local):

```bash
# API: http://127.0.0.1:7441
make api  # in another shell

# Create a subscription, save the id
curl -sS -X POST http://127.0.0.1:7441/v1/webhooks \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY" \
  -H "content-type: application/json" \
  -d '{"url":"https://hooks.example.com/in","events":["classify.completed"]}'

# Preview a pause without applying
curl -sS -X POST "http://127.0.0.1:7441/v1/webhooks/$WID/pause?dry_run=true" \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY"

# Pause (stops all deliveries; keeps secret + history)
curl -sS -X POST "http://127.0.0.1:7441/v1/webhooks/$WID/pause" \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY"

# Resume
curl -sS -X POST "http://127.0.0.1:7441/v1/webhooks/$WID/resume" \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY"
```

## Previously: periodic access reviews for SOC2 CC6.3

Workspace owners can now run the recurring re-certification of member access that SOC2 CC6.3 and ISO 27001 A.9.2.5 require. Open a review and the system snapshots every active member into one decision row per principal, freezing the role each person held at review time so a later promotion cannot rewrite history. Admins mark each row `keep` or `revoke`, optionally with a note, then apply. Apply removes every `revoke` membership in one transaction through the same `memberships_store.remove_member` path the regular members UI uses (so the same last-admin guard fires), stamps `revoked_at` on the items as proof, and seals the review as `applied` so a second apply returns 409. Apply also supports `?dry_run=true` and surfaces a `blocker` field when a planned revocation would leave the workspace with no admin. Every read and write filters by `tenant_id` at the query layer, so a forged review id from another tenant returns 404, never 200. The full per-member decision list can be exported as CSV for compliance evidence. Tenant isolation, RBAC denial for viewers, last-admin protection, and dry-run preview are covered in `tests/test_access_reviews.py` (4 tests). The UI lives at `/admin/access-reviews`: campaign list, status badges, keep/revoke buttons per row, preview-apply, cancel, and CSV export.

Try it (local):

```bash
# API: http://127.0.0.1:7441   UI: http://localhost:3000/admin/access-reviews

# Open a review (admin role + MFA step-up; API keys skip MFA)
curl -X POST http://127.0.0.1:7441/v1/access-reviews \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  -H "x-tenant: acme" \
  -H "content-type: application/json" \
  -d '{"title": "2026 Q2 access review"}'

# Preview the apply (no mutation)
curl -X POST 'http://127.0.0.1:7441/v1/access-reviews/REVIEW_ID/apply?dry_run=true' \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" -H "x-tenant: acme"

# Export the sealed review as CSV for the auditor
curl http://127.0.0.1:7441/v1/access-reviews/REVIEW_ID/export.csv \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" -H "x-tenant: acme"
```

## What's new: suspend members without losing audit history

Offboard a teammate from a workspace immediately while keeping their membership row so existing audit log entries still resolve to a recognized name. Suspended principals are blocked at the auth middleware with `403 membership_suspended` for every tenant-scoped request. Reinstating clears the suspension.

Try it (local):

```bash
# API: http://127.0.0.1:7441   UI: http://localhost:3000/settings/members

# Suspend a member (admin role + MFA step-up required)
curl -X POST http://127.0.0.1:7441/v1/members/bob@example.com/suspension \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  -H "x-tenant: acme" \
  -H "x-mfa-otp: 123456" \
  -H "content-type: application/json" \
  -d '{"reason": "Left the company"}'

# Preview without mutating
curl -X POST 'http://127.0.0.1:7441/v1/members/bob@example.com/suspension?dry_run=true' \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" -H "x-tenant: acme" -H "x-mfa-otp: 123456" \
  -H "content-type: application/json" -d '{"reason": "rehearsal"}'

# Reinstate
curl -X DELETE http://127.0.0.1:7441/v1/members/bob@example.com/suspension \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" -H "x-tenant: acme" -H "x-mfa-otp: 123456"
```

Guards: tenant-scoped (cross-tenant attempts get `404`), refuses to suspend the last active admin (`409`), refuses self-suspension (`409`), and respects `dry_run=true`.


Video and image shot classifier with per-tenant rules, audit trail, signed webhook deliveries, and an admin dashboard.

## What's new: per-seat usage breakdown for billing-by-seat

Workspace owners on enterprise plans get billed by seat, then asked to justify the renewal: how many seats am I paying for, who actually uses the product, and which seats sat dormant all month. ShotClassify now answers that in one screen. `GET /v1/admin/seats/usage` returns, for the caller's workspace only, every member with their role, member-since date, classification count for the current calendar month UTC, and last activity timestamp, plus a separate `orphans` list for principals that still have rows but were already removed from the workspace (forensic and offboarding signal). The endpoint requires the admin role through the same `require_role("admin")` dependency the rest of the admin console uses, and every read is scoped to `request.state.tenant_id` at the SQL layer via `Repository.count_by_principal_grouped(tenant_id=...)`, which raises if no tenant is supplied so it cannot accidentally be used to enumerate across tenants. The matching UI lives at `/admin/seats`: header tiles for seats in use vs limit, active vs dormant this period, total classifications, and former principals; a sortable table with per-seat usage bars and last-activity timestamps; an amber over-limit banner when in-use exceeds the purchased seat cap; loading skeletons, a denied state for non-admins, and an empty state for fresh workspaces. Cross-tenant isolation is proven by `tests/test_admin_seats_usage.py::test_seats_usage_shape_and_tenant_isolation`, which seeds rows under `tenant-b` directly through the repository and confirms the admin response for tenant A returns zero classifications and never surfaces the leaked principal in either list.

### Try it

Local API at `http://127.0.0.1:7441`, web dashboard at `http://localhost:3000/admin/seats`.

```bash
# Per-seat usage for this workspace (admin role required)
curl -s http://127.0.0.1:7441/v1/admin/seats/usage \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" | jq '.seats, .totals, .members[0:3]'
```

## What's new: mandatory accountable owner on every API key

Procurement reviewers consistently ask the same question about machine credentials: who owns this key, and who do we call when it leaks. ShotClassify now answers that question as a first-class field. Every key minted through `POST /v1/api-keys` requires an `owner_email` (a syntactically valid mailbox, lower-cased domain on write so `Alice@ACME.com` and `alice@acme.com` cannot end up as two different owners). The owner is carried forward across `POST /{key_id}/rotate` so a rotation never silently orphans a credential, and admins can reassign it any time via `PATCH /{key_id}/owner` (MFA step-up required). Rows that existed before the migration land in `GET /v1/api-keys/unowned`, a tenant-scoped feed the admin console renders as an amber banner with the count of active credentials missing an owner, so a workspace owner can drive a quarterly access review from a single screen instead of joining the audit log by hand. Tenant isolation is proven by `tests/test_api_key_owner_email.py::test_tenant_isolation_for_owner_patch_and_unowned_list` (probing another workspace's key id returns 404, never 200 or 403). Field is also surfaced in the `to_dict()` payload everywhere keys are listed, so SCIM exports and the SIEM audit feed pick it up automatically.

### Try it

Local API at `http://127.0.0.1:7441`, web dashboard at `http://localhost:3000`.

```bash
# Mint a new API key with an accountable owner
curl -s -X POST http://127.0.0.1:7441/v1/api-keys \
  -H 'content-type: application/json' \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  -H 'x-mfa-otp: 123456' \
  -d '{
        "label": "prod-ingest",
        "scopes": ["write:classifications"],
        "owner_email": "platform-oncall@acme.com"
      }'

# List keys that still need an owner assigned
curl -s http://127.0.0.1:7441/v1/api-keys/unowned \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY"

# Reassign a key's owner
curl -s -X PATCH http://127.0.0.1:7441/v1/api-keys/$KEY_ID/owner \
  -H 'content-type: application/json' \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  -H 'x-mfa-otp: 123456' \
  -d '{"owner_email": "data-platform@acme.com"}'

# UI: http://localhost:3000/admin -> banner shows unowned-key count and links to /keys
```

## What's new: per-workspace customer-managed encryption key reference

Large enterprise buyers (financial services, healthcare, government) routinely require the vendor to encrypt their data at rest with a key the customer controls in their own KMS so they can revoke access by rotating the key. ShotClassify now records that declaration as a first-class per-workspace setting: provider (AWS KMS, GCP KMS, Azure Key Vault, HashiCorp Vault), fully qualified key URI, and an enforcement mode (`disabled`, `advisory`, `required`). The URI shape is sanity-checked against the provider (`arn:aws:kms:...` for `aws-kms`, `projects/...` for `gcp-kms`, and so on) so a pasted-from-the-wrong-tab value is refused at write time instead of bricking the storage adapter at decrypt time. Mode `required` is the production stance: when set, the operator-side CMEK adapter refuses to write a new object whenever your KMS is unreachable, instead of silently falling back to a deployment-managed key. The control surface lives at `/v1/settings/security/cmek` (admin role and a fresh MFA step-up on `PUT`), the change lands in the workspace's tamper-evident audit log with the actor, IP, request id, and user agent, and the declaration is strictly tenant-scoped (one workspace's CMEK reference is never visible to or shared with another, proven by `tests/test_tenant_cmek_reference.py::test_cmek_is_strictly_tenant_scoped`). Manage it interactively at `Settings -> Security -> Customer-managed encryption key` in the web console.

### Try it

Local API at `http://127.0.0.1:7441`, web dashboard at `http://localhost:3000`.

```bash
# Declare an AWS KMS key as the workspace CMEK in required mode
curl -s -X PUT http://127.0.0.1:7441/v1/settings/security/cmek \
  -H 'content-type: application/json' \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  -H 'x-mfa-otp: 123456' \
  -d '{
        "provider": "aws-kms",
        "key_uri": "arn:aws:kms:us-west-2:111111111111:key/abcd1234-...",
        "mode": "required"
      }'

# Read the current declaration
curl -s http://127.0.0.1:7441/v1/settings/security/cmek \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY"

# UI: http://localhost:3000/settings/security -> Customer-managed encryption key
```

## What's new: streaming audit export for SIEM ingestion

The audit log already records every authenticated mutation with a tamper-evident hash chain, but procurement teams routinely ask for one more thing before signing: "give us a file we can drop into Splunk." ShotClassify now ships a tenant-scoped streaming export at `POST /v1/audit/export` that emits the workspace audit trail as CSV or JSON Lines with a signed manifest. The endpoint supports `since` / `until` / `principal` / `path_prefix` / `status_min` / `status_max` filters, pages through the database in 500-row chunks so multi-million-row exports do not exhaust the worker, and caps a single call at 250k rows so a runaway filter cannot. The response carries an `X-Audit-Manifest` header with the current chain tip plus filters applied, and the body itself ends with a manifest record (a `_manifest` JSONL row or a `# {...}` CSV trailer) containing exported_by, exported_at, request id, row count, truncation flag, and the verified hash-chain tip, so consumers can prove the file is intact without a second round trip. The export is a `POST`, which means the export action itself is captured by `AuditLogMiddleware` and lands in the workspace's own chain. Admin only, `read:audit` scope required, tenant-scoped at the query layer (an acme admin cannot export globex's rows). The audit page (`/settings/audit`) now has a real Export dialog with format toggle and date pickers; downloads happen via the browser and the manifest tip is surfaced in the success toast so a workspace owner can pin it off-platform. Coverage in `tests/test_audit_export.py` proves CSV and JSONL formats round-trip correctly, the manifest is present, viewers are denied, inverted date windows are rejected, and tenant A's export never contains tenant B's rows.

### Try it

Local API at `http://127.0.0.1:7441`, web dashboard at `http://localhost:3000`.

```bash
# JSONL export (default)
curl -s -X POST http://127.0.0.1:7441/v1/audit/export \
  -H 'content-type: application/json' \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  -d '{"format":"jsonl","since":"2025-01-01T00:00:00Z"}' \
  -o audit.jsonl

# CSV export with a path filter
curl -s -X POST http://127.0.0.1:7441/v1/audit/export \
  -H 'content-type: application/json' \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  -d '{"format":"csv","path_prefix":"/v1/history"}' \
  -o audit.csv

# UI: http://localhost:3000/settings/audit -> Export
```

## What's new: per-API-key source-IP allowlist

Security questionnaires from regulated buyers almost always include the question "can you pin a long-lived programmatic credential to a specific egress range so a leaked token alone is not enough to drive the API." ShotClassify now ships that as a first-class control. Every `sk_live_*` key has an `allowed_cidrs` field, an optional list of bare IPs or CIDR ranges (IPv4 and IPv6). An empty list, the default for legacy keys, preserves the existing "accept from any IP" behaviour; once one or more entries are set, the same authentication boundary that validates the key compares the resolved client IP (honouring `X-Forwarded-For` and `X-Real-IP`) and rejects with `403 ip_not_allowed` when the request does not match. Enforcement is wired into both the shared `authenticate()` helper used by `/v1/usage`, `/v1/shots`, and `/v1/webhooks`, and the standalone `/v1/classify` handler, so there is no `/v1/*` route that an out-of-range request can slip through. Workspace admins manage the list per key under `/keys/<id>` with add, remove, save, and clear actions; the panel surfaces the current restriction at a glance and shows a friendly empty state when the key is unrestricted. Inputs are normalized (lower-cased, prefix-validated, deduplicated, capped at 64 entries) and bad entries are rejected with a 422 that names the offending value. Coverage in `web/lib/key-cidr-allowlist.test.mts` proves IPv4 and IPv6 normalization, dedupe, prefix matching, that a verified key from an out-of-range IP is denied at the choke point, and that an invalid input leaves the persisted allowlist untouched.

Try it locally:

```
cd web && npm run dev   # Next.js dashboard on :3000
# In the dashboard: Keys -> pick a key -> Source IP allowlist -> add 203.0.113.0/24 -> Save
# Or via the API:
curl -s -X PATCH http://localhost:3000/api/keys/<key-id> \
  -H 'content-type: application/json' \
  -d '{"allowed_cidrs":["203.0.113.0/24","2001:db8::/32"]}'
# Then a call from outside the range fails closed:
curl -i -H "Authorization: Bearer sk_live_..." \
  -H "X-Forwarded-For: 198.51.100.7" \
  http://localhost:3000/v1/usage
# => HTTP/1.1 403 ... "code":"ip_not_allowed"
```

## What's new: API scope catalog and credential introspection

Enterprise procurement reviewers consistently block deals on a single question: show us, in one place, every permission your API can issue, what each one grants, what it does not, and which built-in roles include it. ShotClassify now exposes that catalog as a first-class endpoint. `GET /v1/scopes` returns the canonical list (id, title, description, mutating flag, default roles) backed by `shotclassify_store.scope_catalog`, which is also the single source of truth that `VALID_SCOPES` validates against at API-key creation time, so a new scope cannot ship without a documented entry. A companion `GET /v1/auth/introspect` returns RFC 7662 style data for the calling credential only: principal, tenant binding, role, raw scopes, scopes hydrated against the catalog (legacy or removed scopes are flagged `unknown: true`), credential type, key id, label, last-used and expiry timestamps, and the propagated request id. Introspection deliberately does not accept a token parameter, so the endpoint cannot be turned into a credential oracle. A new admin UI at `/settings/scopes` renders the catalog and the active credential side by side so reviewers and on-call engineers can answer "what can this key actually do" in one click. Coverage in `tests/test_scope_catalog.py` proves the catalog enumerates every scope the store accepts, requires auth, returns the calling key's tenant and scopes, hydrates unknown scopes for legacy keys, and refuses to leak tenant B when a tenant-A-bound key passes `X-Tenant: B`.

Try it locally:

```
make api      # FastAPI on :7441
make web      # Next.js dashboard on :3000
# Public catalog (auth-gated, stable across tenants):
curl -s http://127.0.0.1:7441/v1/scopes -H 'x-api-key: <any-key>' | jq
# What can my current credential do?
curl -s http://127.0.0.1:7441/v1/auth/introspect -H 'x-api-key: <any-key>' | jq
# UI: http://localhost:3000/settings/scopes
```

## What's new: per-tenant audit log SIEM sinks

Enterprise procurement teams routinely block deals on one question: can we get your audit log into our SIEM. ShotClassify now ships per-workspace audit sinks. A workspace admin registers an HTTPS endpoint at `Settings -> Security -> Audit sinks` (or `POST /v1/audit/sinks`) and every audit row written by `AuditLogMiddleware` (actor, method, path, status, request id, client IP, user agent, target id, tenant) is fanned out to that endpoint with an `HMAC-SHA256(sha256(secret), body)` signature in `X-Shotclassify-Audit-Signature` so receivers can verify authenticity. The plaintext signing secret is returned exactly once at create time; only its SHA-256 hash is persisted, so a DB leak cannot be used to forge events. Dispatch runs on a small background pool with a hard per-attempt timeout, reuses the existing webhook egress allowlist and SSRF guardrails (private/loopback addresses blocked unless explicitly permitted), and never blocks or fails the originating request. Each sink row tracks `success_count`, `failure_count`, `last_status`, and `last_error` so operators can see at a glance whether their collector is healthy, and a `Test` button on the page synchronously fires a probe event and reports the HTTP response. Every CRUD call is admin-only, requires the `admin` scope, runs through MFA step-up, and the existing audit middleware records it. Cross-tenant isolation is enforced at the query layer; coverage in `tests/test_audit_sinks.py` proves tenant B cannot list, fetch, revoke, or test tenant A's sink (404, not 403, to avoid existence leaks) and that a mutation on tenant B never reaches tenant A's collector.

Try it locally:

```
make api      # FastAPI on :7441
make web      # Next.js dashboard on :3000
# Register a sink (returns the signing secret exactly once):
curl -s -X POST http://127.0.0.1:7441/v1/audit/sinks \
  -H 'x-api-key: <admin-scoped-key>' \
  -H 'content-type: application/json' \
  -d '{"url":"https://collector.example.com/audit","description":"splunk prod"}'
# Fire a probe at it:
curl -s -X POST http://127.0.0.1:7441/v1/audit/sinks/<id>/test \
  -H 'x-api-key: <admin-scoped-key>'
# UI: http://localhost:3000/settings/security/audit-sinks
```

## What's new: per-workspace request rate limits with standard headers

Every enterprise security questionnaire asks two related questions: how do you stop a noisy customer from exhausting shared capacity, and how do callers know how much budget they have left without polling a separate API. ShotClassify now answers both with a per-workspace, per-API-key rate limiter that gates every `/v1/*` request. The limiter runs four fixed windows in parallel (workspace per-minute, workspace per-day, key per-minute, key per-day), takes the tightest constraint, and either commits the request to every bucket or commits nothing. Decisions are emitted as the de-facto standard `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `X-RateLimit-Policy`, and `X-RateLimit-Scope` headers on `200` responses, and as `HTTP 429 rate_limited` with `Retry-After` plus the same headers when the cap is reached. Plans (`free`, `pro`, `team`) seed sensible defaults; workspace admins can promote to `custom` and dial each window independently from the new `Settings -> Security -> Rate limits` page, which also surfaces live consumption against each ceiling. Configuration is persisted to a per-workspace JSON store at `storage/rate_limits.json` so a deploy restart inherits the active window instead of resetting a tenant's quota to zero. The admin API (`GET`/`PUT /api/ratelimit`) requires an `admin`-scoped `sk_live_*` key and derives the workspace strictly from the bearer key, so cross-tenant reads or writes are impossible at the query layer. The /v1/usage endpoint returns the calling key's live consumption so customers can build their own meters without a second round trip. Coverage in `web/lib/ratelimit-core.test.mts` proves cross-tenant counter isolation (workspace A exhausting its quota does not affect workspace B), per-key bounding when workspace headroom remains, atomic commit-or-skip behaviour, fixed-window rollover, and persistence of plan and limit changes.

Try it locally:

```
cd web && npm run dev
# in another shell:
curl -s -H "Authorization: Bearer sk_live_..." -X PUT \
  -H 'content-type: application/json' \
  -d '{"plan":"custom","limits":{"workspace_per_minute":10,"workspace_per_day":5000,"key_per_minute":5,"key_per_day":2000}}' \
  http://localhost:3000/api/ratelimit
curl -i -H "Authorization: Bearer sk_live_..." http://localhost:3000/v1/usage
# response carries X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset.
# UI: http://localhost:3000/settings/security/rate-limits
```

## What's new: per-(tenant, source IP) authentication brute-force lockout

Every rejected credential (bad `X-API-Key`, bad session cookie, bad SCIM bearer, bad OAuth callback state) is now bucketed in `auth_failures` keyed by `(tenant_id, source_ip)`. When a single source IP accumulates the per-tenant threshold inside the sliding window, the auth middleware writes an `auth_lockouts` row and refuses every subsequent request from that IP for that workspace with `HTTP 423 Locked` plus a standard `Retry-After` header until the cooldown elapses. Lockouts are strictly per workspace and per IP, so a credential-spray attacker against tenant `acme` cannot also lock the legitimate operators of tenant `globex` out of the shared deployment. The policy lives at `/v1/settings/security/auth-lockout` (admin role plus MFA step-up on `PUT`). Workspace admins can list and clear active lockouts at `/v1/admin/lockouts` (and the corresponding console page at `/admin/lockouts`). Bounds enforce a sane range: threshold 3-1000, window 1 min to 24 h, cooldown 1 min to 7 d. Half-configured policies are refused at write time and treated as disabled at read time so a UI misclick can never silently disable enforcement. Coverage in `tests/test_auth_lockout.py`, including the cross-tenant isolation test that procurement teams ask for by name.

Try it locally:

```bash
make api  # http://127.0.0.1:7441

# Configure the lockout policy for this workspace.
curl -sS -X PUT http://127.0.0.1:7441/v1/settings/security/auth-lockout \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" -H 'content-type: application/json' \
  -d '{"threshold": 5, "window_minutes": 10, "cooldown_minutes": 15}'

# Burn the threshold from a single source IP; the Nth attempt returns 423.
for i in 1 2 3 4 5; do
  curl -sS -o /dev/null -w '%{http_code}\n' \
    -H 'x-api-key: clearly-wrong' -H 'x-forwarded-for: 203.0.113.7' \
    http://127.0.0.1:7441/v1/history
done
# -> 401, 401, 401, 401, 423

# List and clear active lockouts.
curl -sS -H "x-api-key: $SHOTCLASSIFY_API_KEY" http://127.0.0.1:7441/v1/admin/lockouts
```

Web console: <http://127.0.0.1:3000/admin/lockouts>.

## What's new: per-tenant webhook egress host allowlist

Every webhook subscription URL the tenant supplies already runs through an SSRF block that refuses private addresses, loopback, link-local, and cloud metadata endpoints. Procurement teams want the next layer too: a per-workspace control that proves outbound webhook traffic can only reach destinations the customer themselves vetted, even if a compromised admin tries to repoint a subscription at an attacker-controlled URL. `tenant_settings.webhook_egress_allowed_hosts` (alembic `0032`) is that control. Entries are exact hostnames (`hooks.example.com`) or leading-dot suffixes (`.example.com`) that match the apex and any subdomain. Wildcards are rejected so a permissive rule never sneaks in. The store enforces the policy at subscription create time (HTTP 422 with the offending host named) AND at delivery time, so removing a host from the list blocks the very next delivery for every existing subscription with a `failed` record whose error reads `egress blocked: host ... not in tenant allowlist`. The HTTP plane lives at `/v1/settings/security/webhook-egress-hosts` (admin role plus MFA step-up on PUT). The web console exposes it at `/settings/security/webhook-egress`. Coverage in `tests/test_webhook_egress_allowlist.py`, including a cross-tenant isolation test that proves tenant A's policy never affects tenant B and vice versa.

Try it locally:

```bash
make api  # http://127.0.0.1:7441

# Configure the allowlist (admin key; MFA step-up gated in prod).
curl -sS -X PUT http://127.0.0.1:7441/v1/settings/security/webhook-egress-hosts \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" -H 'content-type: application/json' \
  -d '{"hosts": [".hooks.example.com"]}'

# A subscription pointed at an off-list host is refused at create time.
curl -sS -X POST http://127.0.0.1:7441/v1/webhooks \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" -H 'content-type: application/json' \
  -d '{"url":"https://evil.attacker.test/h","events":["classify.completed"]}'
# -> 422 host 'evil.attacker.test' is not in this workspace's webhook egress allowlist
```

Web UI: <http://127.0.0.1:3000/settings/security/webhook-egress>.

## What's new: authenticated, tenant-scoped screenshot downloads

Uploaded screenshots used to be served by a raw `StaticFiles` mount at `GET /blob/<filename>` with no authentication and no tenant scoping. Anyone who could guess or scrape a 16-byte hex id could pull another tenant's screenshot, which is an immediate procurement red flag (SOC 2 CC6.1, CC6.6, and every enterprise security questionnaire). The mount is gone. Screenshots now live behind `GET /v1/blobs/{record_id}`, which runs through the same auth, RBAC, rate-limit, IP allowlist, browser-origin allowlist, and legal-hold gates as every other `/v1` route. The handler resolves the classification record through `Repository.get(item_id, tenant_id=...)`, so a caller from workspace B asking for workspace A's id gets `HTTP 404 blob_not_found` (same status as a missing record, so cross-tenant existence does not leak) and never sees a byte of image data. The response carries `Cache-Control: private, no-store` and `X-Content-Type-Options: nosniff` so downstream proxies and shared caches never retain another tenant's screenshot. The history CSV/JSON export no longer leaks the server-side absolute path either; it now exports a relative `blob_url` that callers must fetch through the same authenticated endpoint. Coverage in `tests/test_blob_tenant_scoping.py`, including the regression that the old `/blob/<filename>` mount is gone.

Try it locally:

```sh
# Owning tenant gets the image
curl -s -o /dev/null -w '%{http_code}\n' \
  -H 'X-API-Key: acme-op-key' \
  http://localhost:7441/v1/blobs/<record_id>
# -> 200

# Different tenant gets 404, never the bytes
curl -s -o /dev/null -w '%{http_code}\n' \
  -H 'X-API-Key: globex-op-key' \
  http://localhost:7441/v1/blobs/<record_id>
# -> 404
```

## What's new: Trust Center for Terms of Service, DPA, and Acceptable Use

Enterprise procurement and security reviews want to see that the vendor publishes the current commercial terms in a stable place, that the customer can prove who accepted which version, and that there is a way to hard-gate writes until Legal signs off. ShotClassify now ships a vendor-owned legal catalog (TOS, Data Processing Addendum, Acceptable Use Policy) at `GET /v1/trust/legal`, an append-only per-tenant acceptance ledger at `GET /v1/trust/legal/ledger`, an `accept` endpoint that records actor, IP, user agent, and request id, and a workspace-wide enforcement gate. Each agreement body is hashed to derive its version, so editing the body in code automatically re-arms the acceptance prompt for every workspace; no operator can silently bump a version string by hand. When an admin flips enforcement on, every mutating `/v1` request from that workspace is rejected with `HTTP 451 Unavailable For Legal Reasons` until all required agreements have been accepted at their current version. The gate fails closed on stale acceptances but refuses to arm itself while required agreements are unaccepted, so a workspace can never lock itself out by accident. Reads and writes are admin only and acceptances require MFA step-up. The admin console lives at `/admin/legal`. Cross-tenant isolation, stale-version rejection, and the 451 gate are covered in `tests/test_trust_legal_agreements.py`.

Try it locally:

```bash
make dev   # API on http://127.0.0.1:7441, dashboard on http://127.0.0.1:3000

# Public catalog (no auth needed; procurement can read before they have credentials).
curl http://127.0.0.1:7441/v1/trust/legal | jq '.agreements[] | {id, title, version, required}'

# Accept the current Terms of Service for this workspace (admin key).
VERSION=$(curl -s http://127.0.0.1:7441/v1/trust/legal | jq -r '.agreements[] | select(.id=="tos") | .version')
curl -X POST http://127.0.0.1:7441/v1/trust/legal/accept \
  -H "X-API-Key: $SHOTCLASSIFY_API_KEY" \
  -H 'content-type: application/json' \
  -d "{\"agreement_id\":\"tos\",\"version\":\"$VERSION\"}"

# View the workspace status (which agreements still need acceptance).
curl http://127.0.0.1:7441/v1/trust/legal/status -H "X-API-Key: $SHOTCLASSIFY_API_KEY" | jq
```

The dashboard view is at <http://127.0.0.1:3000/admin/legal>.

## What's new: per-API-key monthly call quota

Per-minute caps (`rpm_override`) stop bursts; they do not stop a steady 24/7 draw that runs up a five-figure bill before anyone notices. Enterprise procurement asks for the matching control: a hard ceiling on how many calls a single integration credential can make in a billing period, without revoking the key outright. Each DB-backed API key now carries an optional `monthly_quota`. When set, the rate limit middleware atomically charges a per-key `api_key_monthly_usage` counter on every request and refuses the next call with `HTTP 429 monthly_quota_exceeded` once the cap is reached, with `X-RateLimit-Scope: api_key_month`, `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0`, and a `Retry-After` plus `X-RateLimit-Reset` pointing at the start of the next UTC month. The cap is per-key (not per-tenant) so a noisy integration cannot starve a quiet one in the same workspace, rotation inherits the cap so a rotated key cannot quietly escape it, and the admin console can read live usage with `GET /v1/api-keys/{id}/monthly-usage`. NULL preserves the legacy unlimited behaviour. Admin only, MFA step-up required on writes. Coverage in `tests/test_api_key_monthly_quota.py`.

Try it locally:

```bash
# Mint a key capped at 50000 calls / month.
curl -sS -X POST http://127.0.0.1:7441/v1/api-keys \
  -H "X-API-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
  -d '{"label":"partner-batch","scopes":["write:classifications"],"monthly_quota":50000}'

# Inspect this month's usage.
curl -sS http://127.0.0.1:7441/v1/api-keys/<key-id>/monthly-usage \
  -H "X-API-Key: $ADMIN_KEY"

# Raise the cap later, or pass quota:null to clear it entirely.
curl -sS -X PATCH http://127.0.0.1:7441/v1/api-keys/<key-id>/monthly-quota \
  -H "X-API-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
  -d '{"quota":100000}'
```

## What's new: per-tenant cap on active API keys

Unbounded service-credential sprawl is a procurement red flag. SOC 2 CC6.1 and NIST AC-2 both expect a documented, enforced cap on how many active credentials a single workspace can hold. ShotClassify now lets workspace admins set a per-tenant `api_key_max_active` cap from `Settings -> Security -> API key active cap` (or `PUT /v1/settings/security/api-key-max-active`). When the cap is set, `POST /v1/api-keys` (mint) is rejected with `HTTP 422 api_key_max_active_reached` once the workspace already holds that many non-revoked keys, and the rejection is recorded in the audit log alongside the actor and request id. Tightening the cap below the current active count never retroactively revokes existing keys; it only blocks the next mint until an admin frees a slot by revoking a stale one. The cap is tenant-scoped: one workspace's policy never affects another's, and the list response (`GET /v1/api-keys`) surfaces both the cap and the current in-use count so the admin UI can show `N of M`. Enforcement lives in `packages/store/src/shotclassify_store/api_keys.py::create_key`, so adding a new mint path cannot bypass it. Reads and writes are admin only, writes require MFA step-up. Coverage in `tests/test_api_key_max_active_policy.py`.

Try it locally:

```bash
make dev   # API on http://127.0.0.1:7441, dashboard on http://127.0.0.1:3000

# Cap this workspace at 10 active API keys.
curl -X PUT http://127.0.0.1:7441/v1/settings/security/api-key-max-active \
  -H "X-API-Key: $SHOTCLASSIFY_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"max_active": 10}'
```

## What's new: per-tenant API key inactivity (auto-revoke) policy

A stale service credential is a deal-blocker for procurement: CC6.1 of SOC 2 and most enterprise security questionnaires ask, in some form, what happens to API keys that nobody uses any more. "We trust admins to clean them up" is no longer an acceptable answer. ShotClassify now lets workspace admins set a per-tenant `api_key_inactivity_days` cap from `Settings -> Security -> API key inactivity policy` (or `PUT /v1/settings/security/api-key-inactivity`). When a cap is set, any DB-backed API key whose effective last-use (falling back to `created_at` for never-used keys) is older than the cap is auto-revoked on its next presentation and the request is rejected with `HTTP 401 api_key_stale_inactive`. Enforcement lives in `services/api/app/middleware/auth.py`, so adding a new route cannot bypass it, and the auto-revocation lands in the tenant's tamper-evident audit log with the inbound request id, source IP, and key id. Existing keys are not retroactively shortened: a tightened policy only takes effect on the next request a stale key actually makes, so the change never breaks a live integration silently. Policy reads and writes are admin only, writes require MFA step-up, and the cap is tenant-scoped (one workspace's policy never affects another workspace's keys). Coverage in `tests/test_api_key_inactivity_policy.py`.

Try it locally:

```bash
make dev   # API on http://127.0.0.1:7441, dashboard on http://127.0.0.1:3000

# Set a 30 day inactivity cap (admin key + MFA step-up disabled in dev).
curl -X PUT http://127.0.0.1:7441/v1/settings/security/api-key-inactivity \
  -H "X-API-Key: $SHOTCLASSIFY_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"inactivity_days": 30}'
```

## What's new: CSRF protection on cookie-authenticated mutations

The `sc_session` cookie is sent automatically by the browser on every request to the API origin, which means any logged-in user visiting a malicious page on a different origin could be coaxed into issuing a state-changing POST or DELETE that succeeds purely on the basis of the ambient cookie. SameSite=Lax blocks top-level form posts but not cross-origin `fetch` from a same-site subdomain takeover or a relaxed CORS allowlist. ShotClassify now ships a `CSRFMiddleware` that enforces a double-submit token on every cookie-authenticated mutation that looks like it came from a browser (the request carries an `Origin` or `Sec-Fetch-Site` header). The token is an HMAC-SHA256 of the session id signed with `APP_SECRET_KEY`, mirrored into a `sc_csrf` cookie that JS can read, and refreshed on every authenticated response so it rolls forward with session renewal and force-logout-all. API-key callers, SCIM bearer callers, and non-browser tools (curl, CI) are exempt because they do not ride on ambient cookies. SPAs can fetch the current token from `GET /auth/csrf` at boot and attach it to every fetch as `X-CSRF-Token`. Coverage in `tests/test_csrf.py` (browser POST without token blocked, with correct token allowed, cross-session token rejected, API-key exempt, safe verb exempt, non-browser caller exempt, /auth/csrf returns matching token, cookie refresh).

### Try it

With the API on `http://127.0.0.1:7441` and a valid `sc_session` cookie in a browser tab:

```sh
make api

# Fetch the CSRF token for the current cookie session
curl -s http://127.0.0.1:7441/auth/csrf \
  -b 'sc_session=<paste from devtools>'

# A browser-shaped DELETE without the token is rejected
curl -i -X DELETE http://127.0.0.1:7441/v1/sessions/<sid> \
  -b 'sc_session=<paste>' \
  -H 'Origin: https://app.example.com'
# -> HTTP/1.1 403 csrf_token_invalid

# Same call with the token succeeds
curl -i -X DELETE http://127.0.0.1:7441/v1/sessions/<sid> \
  -b 'sc_session=<paste>' \
  -H 'Origin: https://app.example.com' \
  -H 'X-CSRF-Token: <token from /auth/csrf>'
```

API-key flows are unaffected: `curl -H 'X-API-Key: ...'` continues to work for every mutation without a CSRF header.

## What's new: per-tenant browser-origin allowlist

The workspace IP allowlist already gates server-to-server callers, but two tenants behind the same corporate egress IP cannot use it to keep each other's web apps off their data. Enterprise procurement (SOC 2 CC6.6, most security questionnaires) now expects a per-workspace browser-origin allowlist as a separate control. ShotClassify adds one: workspace admins can list the exact `scheme://host[:port]` values that are allowed to call the API from a browser, and `OriginAllowlistMiddleware` rejects any request that carries a non-matching `Origin` header with HTTP 403 `origin_not_allowed` before the route handler runs. Server-to-server callers (SDKs, curl, CI) never send an `Origin` so they are unaffected, which is the same backward-compatible default the IP allowlist uses. Manage at `Settings -> Security -> Browser origin allowlist` or via `GET/PUT /v1/settings/security/cors-origins`. Admin only, MFA step-up on writes, audit-logged by the existing tamper-evident chain. Origins are normalised (lowercased scheme and host, default ports stripped, wildcards rejected) so an admin cannot accidentally weaken the policy with a typo. Coverage in `tests/test_origin_allowlist.py`.

Try it locally:

```sh
make api   # http://localhost:7441
# Configure the allowlist for the caller's tenant
curl -s -X PUT http://localhost:7441/v1/settings/security/cors-origins \
  -H 'content-type: application/json' \
  -H 'X-API-Key: <admin-key>' \
  -d '{"origins":["https://app.acme.example"]}'
# A browser-style request from a non-listed origin is rejected
curl -i http://localhost:7441/v1/history \
  -H 'X-API-Key: <admin-key>' \
  -H 'Origin: https://evil.example'
```

In the UI: `http://localhost:3000/settings/security` (after `make web`).

## What's new: RFC 9116 /.well-known/security.txt

Enterprise procurement and bug-bounty scanners (HackerOne, Intigriti, BugCrowd, OneTrust, Vanta-driven reviews) probe `/.well-known/security.txt` on every target host and flag its absence as a finding. ShotClassify now serves a spec-compliant file directly from the API tier, exempt from auth, the IP allowlist, and the rate limiter, with a rolling `Expires:` value recomputed on every request so operators never ship a build just to refresh the date. Bare-email contacts are widened to `mailto:`, language tags are normalised, and the legacy unprefixed `/security.txt` alias is answered for older scanners. The web tier rewrites the same path through to the API so the file is reachable on whichever host the buyer points their scanner at. A top-level `SECURITY.md` documents the vulnerability disclosure policy, response targets, what is in and out of scope, and signed-commits guidance. `.github/CODEOWNERS` pins owner review on every authentication, authorization, audit, MFA, sessions, API-key, SSO, webhook, and migration surface.

Configure via environment (all optional except `SECURITY_CONTACT`):

```sh
SECURITY_CONTACT=security@example.com
SECURITY_CANONICAL_URL=https://example.com/.well-known/security.txt
SECURITY_POLICY_URL=https://example.com/security
SECURITY_ACKNOWLEDGMENTS_URL=https://example.com/security/thanks
SECURITY_ENCRYPTION_URL=https://example.com/pgp.txt
SECURITY_PREFERRED_LANGUAGES=en, de
SECURITY_EXPIRES_DAYS=365   # clamped to 1..366 per RFC 9116 guidance
```

When `SECURITY_CONTACT` is empty the endpoint returns `404 text/plain`, mirroring the behaviour of a host that does not publish a file. Coverage in `tests/test_security_txt.py` (unconfigured 404, unauthenticated 200, header widening, language normalisation, expires clamping, legacy alias).

### Try it

With the API on `http://127.0.0.1:7441`:

```sh
SECURITY_CONTACT=security@example.com make api

curl -i http://127.0.0.1:7441/.well-known/security.txt
```

Expect `HTTP/1.1 200 OK`, `Content-Type: text/plain; charset=utf-8`, and a body that starts with `Contact: mailto:security@example.com` and contains `Expires: <UTC ISO 8601>Z`.

## What's new: RFC 9116 security.txt at /.well-known/security.txt

Enterprise procurement scans, bug-bounty crawlers (HackerOne, Intigriti, BugCrowd), and questionnaires like SIG, CAIQ, Whistic, and OneTrust all check `/.well-known/security.txt`. A missing file is logged as a finding and delays SOC 2 readiness audits. The API tier now serves a spec-compliant file, unauthenticated, with a rolling `Expires` so operators do not have to ship a build to refresh it. The legacy `/security.txt` alias is served too. Both routes are exempt from the auth middleware, rate limiter, and IP allowlist, and the web tier proxies the same paths so scanners targeting the dashboard host find it without knowing the API origin. Operator-configurable via `SECURITY_CONTACT`, `SECURITY_CANONICAL_URL`, `SECURITY_POLICY_URL`, `SECURITY_ACKNOWLEDGMENTS_URL`, `SECURITY_ENCRYPTION_URL`, `SECURITY_HIRING_URL`, `SECURITY_PREFERRED_LANGUAGES`, and `SECURITY_EXPIRES_DAYS` (clamped to one year per RFC 9116 guidance). When `SECURITY_CONTACT` is empty the route returns 404 instead of a misleading stub. The full disclosure policy lives in [`SECURITY.md`](./SECURITY.md). Coverage in `tests/test_security_txt.py`.

### Try it

```bash
make api  # http://localhost:7441

SECURITY_CONTACT=security@example.com \
SECURITY_POLICY_URL=https://example.com/security \
SECURITY_PREFERRED_LANGUAGES="en, de" \
  make api

curl -s http://localhost:7441/.well-known/security.txt
# Contact: mailto:security@example.com
# Expires: 2027-05-31T20:00:00Z
# Preferred-Languages: en, de
# Policy: https://example.com/security
```

## Previous: webhook signing-secret rotation with overlap

Workspace admins can rotate a webhook's HMAC signing secret without dropping events. Rotation mints a new plaintext secret (shown exactly once) and keeps the previous one valid for an overlap window: every outbound delivery is signed twice, with the old key in `X-Shotclassify-Signature` and the new key in `X-Shotclassify-Signature-Next`. Receivers verify either header, swap their stored secret, and the admin finalises the rotation to drop the old key.

All three endpoints require the `admin` role plus a fresh MFA step-up, are tenant-scoped (cross-tenant calls return 404), honour `?dry_run=true`, and are recorded by the existing audit middleware:

* `POST /v1/webhooks/{id}/rotate-secret` returns `{ webhook, secret, secret_warning }`
* `POST /v1/webhooks/{id}/finalize-secret` drops the previous key
* `POST /v1/webhooks/{id}/cancel-rotation` abandons a pending rotation

Try it locally (replace `WH_ID` with the id from `POST /v1/webhooks`):

```bash
make api  # http://localhost:7441

curl -s -X POST http://localhost:7441/v1/webhooks/$WH_ID/rotate-secret \
  -H 'X-API-Key: <admin-key>' -H 'X-MFA-Token: <step-up>' | jq
```

The `Admin -> API webhooks` page exposes Rotate / Finalise / Cancel actions on each subscription and surfaces a callout while a rotation is in flight. End-to-end coverage in `tests/test_webhook_secret_rotation.py` (rotation, dry-run, operator denial, cross-tenant denial, dual-sign on the wire against a live listener, and single-sign after finalise).

## What's new: MFA recovery (backup) codes

Mandatory MFA closes one risk and opens another: a user who loses their phone is locked out of their workspace until an admin intervenes. SOC 2 CC6.1 and NIST 800-63B both expect a documented self-service recovery path, and procurement teams routinely block deals until they see one. Every confirmed second factor can now mint a batch of 10 single-use recovery codes from `Settings -> Security -> MFA`. Plaintext is shown exactly once at generation time; the server only retains a per-code salted SHA-256 hash, so a database leak cannot reveal a working code. Each code satisfies step-up exactly once (NIST 800-63B 5.1.2), is burned atomically on use, and stamps the session's `mfa_verified_at` so the user immediately regains access to admin mutations. Regenerating a batch invalidates the prior set in a single transaction so users never have two live batches at once, and disabling MFA wipes every recovery row for that principal so a stale code can never re-enable step-up after the second factor is gone. Generation itself requires a fresh TOTP step-up (`require_mfa_step_up`) so a stolen cookie alone cannot mint codes, and API key callers are refused outright because recovery is a human-only flow. Coverage in `tests/test_mfa_recovery_codes.py`.

### Try it

With the API running on `http://127.0.0.1:7441` and a cookie session that has a confirmed TOTP credential and a fresh step-up:

```sh
# Mint a batch. Plaintext is returned once and only once.
curl -s -X POST -b "sc_session=$COOKIE" \
  http://localhost:7441/v1/mfa/recovery-codes | jq

# Redeem one when the authenticator app is unavailable; this stamps the session.
curl -s -X POST -b "sc_session=$COOKIE" -H "content-type: application/json" \
  -d '{"code":"abcd-efgh"}' http://localhost:7441/v1/mfa/recovery | jq
```

The dashboard surface lives at <http://localhost:3000/settings/mfa>.

## Previous: tenant-consented support access grants

The vendor side of any multi-tenant SaaS has the same long-standing back door: an `admin` who runs the deployment can flip `X-Tenant: <other>` and silently read or mutate any customer workspace's data. Procurement reviewers catch this every time and refuse to sign without a control. The tenant resolution middleware now refuses cross-tenant admin scoping unless the target workspace has issued an active, unexpired support access grant, and every cross-tenant request taken under a grant writes the grant id, ticket reason, and target tenant into the immutable hash-chained audit log. Workspaces manage their own grants from `/settings/support-access`: each grant carries a reason (ticket id or short narrative), a hard expiry (5 minutes to 7 days), an optional pin to one specific vendor admin login, and a visible use counter. Revocation is one click and the gate closes on the next request. The legacy single-admin `AUTH_API_KEY` stays exempt because it represents the owner of the deployment, not a multi-tenant SaaS support engineer; DB-backed API keys already carry a hard tenant binding and are unaffected. Coverage in `tests/test_support_access.py`.

### Try it

With the API running on `http://127.0.0.1:7441` and a workspace admin key in `$ACME_ADMIN_KEY`, and a separate vendor admin key in `$VENDOR_ADMIN_KEY`:

```sh
# Without a grant, vendor admin cross-tenant access is refused.
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "X-API-Key: $VENDOR_ADMIN_KEY" -H "X-Tenant: acme" \
  http://localhost:7441/v1/history
# -> 403

# The acme workspace authorizes one hour of vendor access.
curl -s -X POST -H "X-API-Key: $ACME_ADMIN_KEY" \
  -H "content-type: application/json" \
  -d '{"reason":"ZD-9001 investigate failed run","duration_minutes":60}' \
  http://localhost:7441/v1/support-access

# Now the vendor admin can scope in, and the request is audit-tagged.
curl -s -H "X-API-Key: $VENDOR_ADMIN_KEY" -H "X-Tenant: acme" \
  http://localhost:7441/v1/history | head
```

The dashboard view lives at <http://localhost:3000/settings/support-access>.

## Previous: per-API-key source-IP allowlist

The workspace-level IP allowlist already gates the dashboard and the API as a whole, but every API key issued for that workspace inherited the same one allowlist. Enterprise procurement teams routinely ask for the tighter control: a single leaked CI key must not be replayable from a coffee shop even if the workspace allowlist is open, and a vendor integration key should be locked to that vendor's egress IPs without forcing the same constraint on every other key. Each key now carries its own optional `allowed_cidrs` list (IPv4 or IPv6, bare addresses or CIDR ranges). When the list is empty the key works from any IP (default, backward-compatible). When it is set, the auth middleware checks the request's source IP against the list before touching the route and returns `HTTP 403 api_key_ip_not_allowed` on a miss, with the rejected `client_ip` echoed back so an operator can see the actual source. Enforcement lives in `services/api/app/middleware/auth.py` so adding a new route cannot bypass it, rotation copies the allowlist to the successor key, and every change is captured by the existing tamper-evident audit chain. Admin only, MFA step-up required on writes. Coverage in `tests/test_api_key_ip_allowlist.py`.

### Try it

With the API running on `http://127.0.0.1:7441` and an admin key in `$ADMIN_KEY`:

```sh
# Mint a key locked to the office and CI ranges.
curl -s -X POST -H "X-API-Key: $ADMIN_KEY" \
  -H "content-type: application/json" \
  -d '{"label":"ci-runner","scopes":["write:classifications"],"allowed_cidrs":["198.51.100.0/24","203.0.113.7"]}' \
  http://localhost:7441/v1/api-keys

# Replace the allowlist on an existing key (empty list clears the restriction).
curl -s -X PATCH -H "X-API-Key: $ADMIN_KEY" \
  -H "content-type: application/json" \
  -d '{"allowed_cidrs":["10.0.0.0/8"]}' \
  http://localhost:7441/v1/api-keys/<key_id>/allowed-cidrs
```

A call from outside the allowlist returns:

```json
{"error":"api_key_ip_not_allowed","detail":"...","client_ip":"203.0.113.5"}
```

## Earlier: workspace-wide MFA enrolment policy

Per-action MFA step-up already gated destructive admin mutations, but it never forced a viewer or operator who only reads data to enrol a second factor. That fails SOC 2 CC6.6, ISO 27001 A.9.4.2, and HIPAA 164.308(a)(5)(ii)(D), which all expect "every human user authenticates with multiple factors". An admin can now flip `mfa_required_for_members` on the workspace and every cookie-authenticated request from a member without a confirmed TOTP credential gets `HTTP 403 mfa_enrollment_required` until they enrol. A small allowlist (`/v1/mfa/*`, `/v1/me/*`, `/v1/sessions`, `/auth/logout`, healthchecks) stays open so members can complete enrolment without being locked out of the very pages that let them comply. API keys are exempt because they cover machine-to-machine integrations.

The enable path itself is guarded: the API refuses to turn the policy on if the calling admin does not already have a confirmed credential and a fresh step-up, so an admin cannot accidentally lock themselves out from a non-MFA session.

### Try it

With the API running on `http://127.0.0.1:7441` and an admin cookie session that has a confirmed TOTP credential and a recent MFA step-up:

```sh
# Inspect the current policy.
curl -s -b "sc_session=$SC_SESSION" \
  http://127.0.0.1:7441/v1/settings/security/mfa-policy

# Enable the policy for the resolved workspace.
curl -s -b "sc_session=$SC_SESSION" -X PUT \
  -H 'content-type: application/json' \
  -d '{"required": true}' \
  http://127.0.0.1:7441/v1/settings/security/mfa-policy
```

In the UI: Settings -> Security -> Multi-factor authentication. The toggle lives next to Session lifetime and API key TTL.

## Previous: security incident registry and per-tenant notification contacts

Enterprise procurement and DPA reviews always ask the same question: how will you notify us of a security incident, and where can we see your history? Both halves now ship in-product.

`GET /v1/trust/incidents` is a public, append-only registry of security incidents (id, severity, status, title, summary, affected components, published timestamp). It needs no credentials so a procurement reviewer can verify it from a terminal the same way they'd hit a status page. The registry is vendor-owned in `packages/store/src/shotclassify_store/incidents.py` so it ships with the binary and cannot be tampered with through the API.

Workspace admins can wire notification contacts at `Settings -> Security -> Incidents` or via `POST /v1/incident-subscriptions`. Each contact picks a channel (`email` or `webhook`), an endpoint, a minimum severity (`low`, `medium`, `high`, `critical`), and an optional label. All mutating routes require the admin role plus a fresh MFA step-up, and are picked up automatically by the existing `AuditLogMiddleware` so the actor, IP, request id, and timestamp land in the tamper-evident audit chain. Every store call is strictly scoped by `tenant_id`; cross-tenant reads, patches, and deletes return 404. Coverage in `tests/test_incident_subscriptions.py`.

### Try it

```bash
# 1. Boot the API and web tiers.
make dev   # FastAPI on :7441, Next.js on :3000

# 2. Public registry, no auth.
curl -s http://localhost:7441/v1/trust/incidents | jq '.items[0]'

# 3. List this workspace's notification contacts (admin role).
curl -s -H "x-api-key: $SHOTCLASSIFY_ADMIN_KEY" \
     http://localhost:7441/v1/incident-subscriptions | jq

# 4. Add an email contact for high+critical incidents.
curl -s -X POST -H "x-api-key: $SHOTCLASSIFY_ADMIN_KEY" \
     -H "content-type: application/json" \
     -d '{"channel":"email","endpoint":"security@acme.example","severity_min":"high","label":"SecOps"}' \
     http://localhost:7441/v1/incident-subscriptions | jq
```

UI: <http://localhost:3000/settings/security/incidents>.

## What's new: liveness, readiness, and Prometheus metrics on the web tier

Kubernetes-style probes and a Prometheus exposition endpoint are now baked into the Next.js web tier alongside the existing FastAPI ones, so a buyer's SRE team can scrape and rotate pods without bespoke glue. `GET /healthz` returns `{ status: "ok", uptime_seconds }` and is dependency-free, matching the Kubernetes guidance that liveness must not flap on upstream failures. `GET /readyz` runs real dependency checks (upstream FastAPI `/healthz` reachability plus keystore directory writability) and returns 503 when any check fails, which is the correct signal for a load balancer to pull the pod out of rotation without restarting it. `GET /metrics` emits Prometheus text format v0.0.4 with three series populated by the `/v1` API surface (`shotclassify_http_requests_total`, `shotclassify_http_request_duration_seconds`, `shotclassify_http_errors_total`) plus `shotclassify_process_uptime_seconds`. Every `/v1` request is wrapped by `withObservability(route, handler)`, which also resolves or mints a request id (honoring upstream `x-request-id`, `x-correlation-id`, or `traceparent` when safe) and echoes it on every response for end-to-end tracing. Coverage in `web/lib/metrics.test.mts`. Live admin view at `/admin/observability`.

### Try it

```bash
# 1. Boot the web tier.
pnpm --filter shotclassify-web dev   # http://localhost:3000

# 2. Liveness is fast and dependency-free.
curl -i http://localhost:3000/healthz
# HTTP/1.1 200 OK
# x-request-id: <hex>
# {"status":"ok","uptime_seconds":12}

# 3. Readiness checks the upstream classifier and the keystore.
curl -i http://localhost:3000/readyz
# HTTP/1.1 200 OK   (or 503 with per-check detail when degraded)
# {"status":"ready","checks":[{"name":"upstream_api","ok":true},{"name":"keystore","ok":true}]}

# 4. Scrape Prometheus metrics. Hit /v1 first so series exist.
curl -s -H "Authorization: Bearer $SK" http://localhost:3000/v1/usage > /dev/null
curl -s http://localhost:3000/metrics | grep shotclassify_http_requests_total
# shotclassify_http_requests_total{method="GET",route="/v1/usage",status="2xx"} 1

# 5. Request ids propagate end-to-end.
curl -s -D - -H "x-request-id: trace-abc-1" http://localhost:3000/healthz | grep -i x-request-id
# x-request-id: trace-abc-1
```

Dashboard UI: <http://localhost:3000/admin/observability>.

## What's new: enforced API key rotation policy

SOC 2 CC6.1 and most enterprise procurement reviews expect a documented and *enforced* credential rotation window, not just a written policy. Workspace admins can now cap the lifetime of every newly minted or rotated API key from `Settings -> Security -> API key rotation policy` (or `PUT /v1/settings/security/api-key-ttl`). When a cap is set, `POST /v1/api-keys` rejects any `ttl_days` longer than the cap and applies the cap as the default when `ttl_days` is omitted, so a tenant with a policy can never silently mint an unbounded key. `POST /v1/api-keys/{id}/rotate` clamps the successor's expiry to the cap as well, so rotation never extends past the documented window. Existing keys are not retroactively shortened: a tightened policy will not break a live integration. The cap is surfaced on `GET /v1/api-keys` (field `ttl_policy`) so the admin UI can render the active value. Admin-only, MFA step-up required, audit-logged by the existing tamper-evident chain. Coverage in `tests/test_api_key_ttl_policy.py`.

### Try it

```bash
# 1. Set a 30 day rotation cap for the workspace.
curl -s -X PUT -H "X-API-Key: $ADMIN_KEY" -H "X-MFA-OTP: 123456" \
  -H "content-type: application/json" \
  -d '{"max_ttl_days": 30}' \
  http://localhost:7441/v1/settings/security/api-key-ttl
# {"tenant_id": "acme", "max_ttl_days": 30, "min_days": 1, "max_days": 3650}

# 2. A 90 day key is rejected with 422; an in-range key is minted.
curl -s -X POST -H "X-API-Key: $ADMIN_KEY" -H "content-type: application/json" \
  -d '{"label":"ci","scopes":["read:classifications"],"ttl_days":90}' \
  http://localhost:7441/v1/api-keys
# {"detail": "ttl_days 90 exceeds tenant policy max of 30 days"}

# 3. The policy ships with the key list so the dashboard can render it.
curl -s -H "X-API-Key: $ADMIN_KEY" http://localhost:7441/v1/api-keys | jq .ttl_policy
# {"tenant_id": "acme", "max_ttl_days": 30, "min_days": 1, "max_days": 3650}
```

Dashboard UI: <http://localhost:3000/settings/security>.

## What's new: per-tenant OIDC identity provider

Large customers refuse to hand their corporate Okta or Azure AD credentials to a shared vendor SSO client. Each workspace can now register its own OIDC application from `Settings -> Security -> Your own identity provider` (or `PUT /v1/settings/security/oidc`). When a user signs in with an email in the workspace's SSO domain, `/auth/sso/login` resolves the tenant, looks up its issuer + client_id + client_secret, and runs the authorization-code flow against that tenant's IdP instead of the deployment-level shared client. The deployment-level `AUTH_SSO_*` config remains as a fallback for workspaces that have not configured their own IdP. Client secrets are stored opaquely, never returned by any API; only a SHA-256 fingerprint and last-four are surfaced for operator confirmation. Admin-only, MFA step-up required, audit-logged by the existing tamper-evident chain. Coverage in `tests/test_tenant_oidc.py`.

### Try it

```bash
# 1. Bind your email domain to your tenant (one time).
curl -s -X PUT -H "X-API-Key: $ADMIN_KEY" -H "X-MFA-OTP: 123456" \
  -H "content-type: application/json" \
  -d '{"enforced": false, "domain": "acme.com", "provider": "Okta"}' \
  http://localhost:7441/v1/settings/security/sso

# 2. Register your own OIDC application.
curl -s -X PUT -H "X-API-Key: $ADMIN_KEY" -H "X-MFA-OTP: 123456" \
  -H "content-type: application/json" \
  -d '{
        "issuer": "https://your-tenant.okta.com",
        "client_id": "0oab1c2d3e4f5g6h7i",
        "client_secret": "<paste from Okta>",
        "scopes": "openid email profile"
      }' \
  http://localhost:7441/v1/settings/security/oidc

# 3. The sign-in page now offers your IdP for emails in acme.com.
curl -s 'http://localhost:7441/auth/sso/config?email=user@acme.com' | jq
# {"enabled": true, "issuer": "https://your-tenant.okta.com", "source": "tenant", "tenant_id": "acme"}
```

Dashboard UI: <http://localhost:3000/settings/security>.

## What's new: trust center sub-processor registry

Procurement and security reviewers can now pull the live sub-processor catalog without credentials at `GET /v1/trust/subprocessors` (public web page at `/trust`), and workspace admins can record a binding acknowledgement at `/settings/trust`. The catalog version is a deterministic SHA-256 over the canonicalized list so any change to a processor automatically re-arms the unacknowledged banner for every workspace. Acknowledgements capture the actor, IP, user agent, and version, are tenant-scoped at the query layer, and the mutating POST is picked up by the existing tamper-evident audit chain. Coverage in `tests/test_trust_subprocessors.py`.

### Try it

```bash
# Public catalog. No auth.
curl -s http://localhost:7441/v1/trust/subprocessors | jq

# Admin acknowledgement (echo back the current version to bind it).
VERSION=$(curl -s http://localhost:7441/v1/trust/subprocessors | jq -r .version)
curl -s -X POST -H "X-API-Key: $ADMIN_KEY" -H "content-type: application/json" \
  -d "{\"version\":\"$VERSION\"}" \
  http://localhost:7441/v1/trust/subprocessors/ack
```

Public page: <http://localhost:3000/trust>. Admin settings: <http://localhost:3000/settings/trust>.

## What's new: legal hold registry

Workspace admins can place a legal hold from `/admin/legal-holds` or `POST /v1/settings/security/legal-holds` to freeze evidence during litigation, regulator inquiry, or compliance review. While at least one hold is active, every destructive code path in the API refuses with HTTP 423 Locked and the matter names that caused the block: per-shot `DELETE /v1/history/{id}`, bulk `POST /v1/history/bulk` with `action=delete`, `DELETE /v1/me/data`, `DELETE /v1/workspace/data`, and the scheduled retention purge (which returns `held: true` instead of removing rows). Lifting a hold writes `lifted_at` and `lifted_by` instead of deleting the row, so the e-discovery audit trail survives. Holds are tenant-scoped at the query layer; one workspace's hold never blocks another's deletes. Coverage in `tests/test_legal_hold.py`.

### Try it

```bash
# Place a hold (admin role + MFA step-up enforced server-side).
curl -s -X POST -H "X-API-Key: $ADMIN_KEY" -H "X-MFA-OTP: 123456" \
  -H "content-type: application/json" \
  -d '{"matter":"SEC Inquiry 12-345","reason":"preserve all evidence"}' \
  http://localhost:7441/v1/settings/security/legal-holds

# Any subsequent delete now fails with 423 Locked.
curl -i -X DELETE -H "X-API-Key: $ADMIN_KEY" \
  http://localhost:7441/v1/history/some-shot-id
# HTTP/1.1 423 Locked
# {"detail":{"error":"legal_hold_active","matters":["SEC Inquiry 12-345"], ...}}
```

Manage from the admin console at <http://localhost:3000/admin/legal-holds>.

## What's new: per-workspace seat limits

Workspaces now have a configurable seat cap (`seat_limit` on `tenant_settings`). A seat is one active member plus one pending invitation, so the count an admin sees in `/settings/members` matches what billing would charge. Enforcement lives in the store layer (`memberships.upsert_member` and `memberships.create_invitation`) so every path that adds a seat is gated identically: manual invites return HTTP 402 with `{"error":"seat_limit_exceeded", "seat_limit", "seats_in_use"}`, SCIM provisioning returns 507 `tooMany` so Okta/Azure AD retry cleanly, and SSO auto-join silently declines so a sign-in at the cap still succeeds without granting a role. Lowering the cap below current usage is allowed and only blocks new seats. Role changes on existing members never consume a seat. Coverage in `tests/test_seat_limits.py`.

### Try it

```bash
# Read current seat accounting (admin role required).
curl -s -H "X-API-Key: $ADMIN_KEY" http://localhost:7441/v1/workspace/seats
# => {"tenant_id":"acme","seat_limit":null,
#     "seats_in_use":{"members":3,"pending_invitations":1,"total":4},
#     "seats_available":null}

# Cap the workspace at 10 seats. MFA step-up required.
curl -s -X PUT -H "X-API-Key: $ADMIN_KEY" -H "X-MFA-OTP: 123456" \
  -H "content-type: application/json" \
  -d '{"seat_limit":10}' http://localhost:7441/v1/workspace/seats
```

Manage from the dashboard at <http://localhost:3000/settings/members>.

## What's new: automatic retention enforcement

Per-tenant retention windows are now enforced by the worker on a schedule instead of waiting for someone to remember to hit the manual purge route. The worker spawns a small daemon thread on startup that, every `RETENTION_SCHEDULER_INTERVAL_S` seconds (default 3600, floor 60), iterates every tenant with a positive `retention_days` policy and hard-deletes expired classifications and their blobs. Tenants without a policy are skipped. Each non-empty purge writes one audit row scoped to the owning tenant with the `scheduler` trigger, so workspace owners see automatic deletions in the same audit log as manual ones. Cross-tenant isolation is preserved end to end. Set `RETENTION_SCHEDULER_ENABLED=false` to opt out (for example when running an external cron). Coverage in `tests/test_retention_scheduler.py`.

### Try it

```bash
# Set a 30-day retention window for the workspace
curl -s -X PUT http://localhost:7441/v1/settings/security/retention \
  -H "X-API-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
  -d '{"retention_days":30}' | jq

# Start the worker; the scheduler runs automatically in the background
make worker
```

## What's new: per-tenant session idle (inactivity) timeout

Workspace admins can now enforce a session idle timeout from `/settings/security` (UI) or `PUT /v1/settings/security/sessions/idle` (API). When set, the auth middleware revokes any cookie session whose `last_seen_at` is older than the configured number of minutes on the next request, dropping the user back to the login flow. NULL keeps the legacy behaviour (sessions bounded only by absolute TTL). Idle policy is per tenant, so one workspace's tightening cannot kick another workspace's users. Bounds are 5 minutes to 30 days; values outside that range return 422 with a precise message. SOC2 CC6.1 and the standard enterprise security questionnaire treat this as a hard requirement. Coverage in `tests/test_session_idle_timeout.py`.

### Try it

```bash
# Read the policy (admin role required); session_idle_minutes=null means off.
curl -s -H 'X-API-Key: $ADMIN_KEY' http://localhost:7441/v1/settings/security/sessions

# Enforce a 30-minute idle timeout for the tenant.
curl -s -X PUT -H 'X-API-Key: $ADMIN_KEY' -H 'content-type: application/json' \
  -d '{"session_idle_minutes":30}' http://localhost:7441/v1/settings/security/sessions/idle

# Clear it (return to no idle timeout).
curl -s -X PUT -H 'X-API-Key: $ADMIN_KEY' -H 'content-type: application/json' \
  -d '{"session_idle_minutes":null}' http://localhost:7441/v1/settings/security/sessions/idle
```

Manage from the dashboard at <http://localhost:3000/settings/security> under Session lifetime.

## Previous: per-tenant cookie session lifetime

Workspace admins can now set the cookie session TTL per tenant from `/settings/security` (UI) or `PUT /v1/settings/security/sessions` (API). Lowering the policy clips every active session for the tenant whose remaining lifetime exceeds the new ceiling, so a long-lived cookie minted before the change cannot outlive the new rule. Clearing the override (sending `null`) returns the tenant to the global default in `sessions.SESSION_TTL`. Bounds are 5 minutes to 365 days; values outside that range return 422 with a precise message. Coverage in `tests/test_session_policy.py`.

### Try it

```bash
# Read the active policy (admin role required).
curl -s -H 'X-API-Key: $ADMIN_KEY' http://localhost:7441/v1/settings/security/sessions
# => {"tenant_id":"acme","session_ttl_minutes":null,"default_minutes":43200,
#     "effective_minutes":43200,"min_minutes":5,"max_minutes":525600}

# Tighten to 8 hours. "clipped" reports how many active sessions were shortened.
curl -s -X PUT -H 'X-API-Key: $ADMIN_KEY' -H 'content-type: application/json' \
  -d '{"session_ttl_minutes":480}' http://localhost:7441/v1/settings/security/sessions
# => {...,"session_ttl_minutes":480,"effective_minutes":480,"clipped":3}
```

Manage from the dashboard at <http://localhost:3000/settings/security>.

## Previous: zero-downtime API key rotation with grace window

Workspace admins can rotate a `/v1/api-keys` credential with `POST /v1/api-keys/{id}/rotate`. The endpoint mints a successor key that inherits the source key's tenant binding, scopes, and per-key rate limit override, then shortens the old key's `expires_at` to `now + grace_minutes` (default 24 hours, max 7 days, `0` revokes immediately). Both keys authenticate during the grace window so production integrations can swap the secret without dropped requests, then the old key hard-fails 401 on its own.

The call requires the `admin` scope plus an MFA step-up (matching create/revoke), is audited by the global middleware with the source key id as the audit target, and supports `?dry_run=true` to preview without mutating. Cross-tenant rotation attempts return 404 (not 403) so a tenant-scoped admin cannot probe key ids that belong to another workspace. Coverage in `tests/test_api_keys_db.py::test_rotate_key_issues_successor_and_grace_old` and `::test_rotate_cannot_cross_tenants`.

### Try it

```bash
# Rotate an API key with a 1-hour grace window, then prove both keys work.
curl -sS -X POST -H "X-API-Key: $ADMIN_KEY" -H "content-type: application/json" \
  -d '{"grace_minutes": 60}' \
  http://localhost:7441/v1/api-keys/$KEY_ID/rotate
# => {"rotated":true,"old_key":{...,"expires_at":"...+01:00"},
#     "new_key":{...,"token":"sk_live_..."},"grace_minutes":60}
```

## Previous: tamper-evident audit log (SHA-256 hash chain)

Every audit row is now cryptographically linked to the previous row in the same workspace using `entry_hash = sha256(prev_hash || canonical_json(fields))`. Modifying, deleting, or inserting an audit row out of band breaks the chain, and the new `GET /v1/audit/verify` endpoint reports exactly where. The admin audit page surfaces a shield badge plus a one-click Verify button and shows the current tip hash so workspace owners can pin it off-platform (e.g. in a quarterly compliance report) to detect future tampering even by an attacker who controls the API.

Migration `0018_audit_hash_chain` adds `prev_hash` and `entry_hash` to `audit_log`. Legacy rows from before the chain are tolerated as a single reset point so upgrading does not look like tampering. Coverage in `tests/test_audit_chain.py` proves both the happy path and that a direct DB mutation of a historical row is detected at the correct row id.

### Try it

Local dashboard: http://localhost:3000/settings/audit (click **Verify chain**).

```bash
curl -sS -H "X-API-Key: $ADMIN_KEY" http://localhost:7441/v1/audit/verify
# => {"ok":true,"checked":42,"tenant_id":"acme","broken_at":null,"reason":null,"tip_hash":"<64-hex>"}
```

## Previous: per-route scope enforcement on API keys

DB-issued API keys now carry scopes (`read:classifications`, `write:classifications`, `read:audit`, `admin`) and every public `/v1/*` route checks them. A key minted with only `read:classifications` can list and export history but cannot delete, bulk-mutate, or correct records, cannot pull the audit log, cannot manage webhooks, and cannot mint or revoke other keys. The `admin` scope is a superset shorthand; session cookies fall back to the existing role check so dashboard users are unaffected.

Failures return a 403 that names the missing scope, which makes it actionable for integration owners without leaking what *would* have happened. Coverage in `tests/test_api_keys_db.py` proves: a read-only key cannot delete history, a write-only key cannot read `/v1/audit`, and a non-admin key cannot list, mint, revoke, or rate-limit API keys.

### Try it

```bash
# Mint a read-only key from the dashboard at http://localhost:3000/keys.
# Then prove it cannot mutate:
curl -sS -X DELETE -H "X-API-Key: $READ_ONLY_KEY" \
  http://localhost:7441/v1/history/any-id
# => 403 {"detail":"Role 'viewer' lacks required role 'operator'."}

curl -sS -H "X-API-Key: $READ_ONLY_KEY" http://localhost:7441/v1/audit
# => 403 {"detail":"API key is missing required scope 'read:audit'."}
```

## Previous: SSRF-safe outbound webhook egress

Webhook destinations are tenant controlled, which makes the dispatcher the most common SSRF sink in any SaaS. Before every delivery (and at subscription create time) the URL is parsed, the hostname is resolved, and every A/AAAA record is checked. Loopback, private (RFC1918, IPv6 ULA), link-local, multicast, CGNAT, cloud-metadata (169.254.0.0/16), and operator-configured CIDR ranges are refused. Plain `http://` is refused unless explicitly enabled. Egress denials skip the retry loop and surface as `egress blocked: <reason>` in the audit-replay UI so tenants get an actionable error without leaking internal network topology.

Knobs (`shotclassify_common.settings.Settings`):

- `WEBHOOK_EGRESS_ALLOW_HTTP` (default `false`): permit plain `http://` targets.
- `WEBHOOK_EGRESS_ALLOW_PRIVATE` (default `false`): permit loopback/private targets. Dev only.
- `WEBHOOK_EGRESS_EXTRA_BLOCKED_CIDRS` (default empty): comma-separated extra denylist (e.g. your VPC supernet `10.0.0.0/8`).

All three behaviors and the hardcoded blocks (cloud metadata stays blocked even in dev mode) are covered by `tests/test_webhook_egress.py`.

### Try it

```bash
# A loopback target is rejected at create time.
curl -s -X POST http://localhost:7441/v1/webhooks \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"url":"http://127.0.0.1:8080/hook","events":["classify.completed"]}'
# => 422 {"detail":"URL rejected: loopback address"}

# A cloud-metadata target is rejected even with WEBHOOK_EGRESS_ALLOW_PRIVATE=true.
curl -s -X POST http://localhost:7441/v1/webhooks \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"url":"http://169.254.169.254/latest/meta-data/","events":["*"]}'
# => 422 {"detail":"URL rejected: address in blocked range 169.254.0.0/16"}
```

Full threat-model write-up: [`docs/security.md`](docs/security.md).

## Earlier: SCIM 2.0 provisioning for Okta, Azure AD, Google Workspace

The FastAPI service now speaks SCIM 2.0 (RFC 7644) so enterprise IdPs can auto provision and de provision workspace members without API key handouts. Each workspace mints its own bearer token, only the SHA-256 is stored, and lookups go through that hash index so the plaintext never appears in logs or backups. Disabling SCIM in the admin console breaks glass immediately: every subsequent SCIM call returns 401 even before the admin rotates.

The whole `/scim/v2/*` router is tenant scoped at the query layer, not just at the URL. A SCIM token for tenant A cannot list, read, mutate, or delete users in tenant B. The test suite proves that property end to end, plus that SCIM cannot mint workspace admins (privilege escalation through whoever owns the IdP attribute store), cannot demote or delete the last admin, and that rotation atomically invalidates the previous token in the same transaction.

Token rotation, enable / disable, and default-role changes all sit behind workspace admin role plus MFA step up. Provisioned users default to viewer; an admin can switch the per-tenant default to operator. The `admin` role itself is never assignable from SCIM by design.

### Try it

Local dashboard: <http://localhost:3000/settings/security/scim>

```bash
# Mint the bearer (admin + MFA step up; returned exactly once).
curl -sS -X POST http://localhost:7441/v1/scim/token/rotate \
  -H "x-api-key: $ACME_ADMIN_KEY" -H "x-tenant: acme" -H "x-mfa-otp: 123456"

# IdP capability discovery (uses the SCIM bearer, not the API key).
curl -s http://localhost:7441/scim/v2/ServiceProviderConfig \
  -H "Authorization: Bearer $SCIM_TOKEN"

# Provision a user.
curl -sS -X POST http://localhost:7441/scim/v2/Users \
  -H "Authorization: Bearer $SCIM_TOKEN" \
  -H 'content-type: application/scim+json' \
  -d '{"schemas":["urn:ietf:params:scim:schemas:core:2.0:User"],
       "userName":"alice@acme.test","active":true,
       "roles":[{"value":"operator"}]}'

# De-provision (Okta sends this shape on group removal).
curl -sS -X PATCH http://localhost:7441/scim/v2/Users/alice@acme.test \
  -H "Authorization: Bearer $SCIM_TOKEN" \
  -H 'content-type: application/scim+json' \
  -d '{"schemas":["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
       "Operations":[{"op":"replace","path":"active","value":false}]}'
```

Receiver-side signature verification:

```python
import hashlib, hmac
key = hashlib.sha256(stored_secret.encode()).hexdigest().encode()
expected = "sha256=" + hmac.new(key, raw_body, hashlib.sha256).hexdigest()
assert hmac.compare_digest(expected, request.headers["X-Shotclassify-Signature"])
```

Test coverage (`tests/test_webhooks_api.py`): RBAC denial for non-admins, secret returned exactly once, cross-tenant isolation across list/get/delete, dry-run revoke is a no-op, URL/event validation, live HMAC signature verification against a captured POST, and failed-delivery accounting after the full retry budget.

## Previous: unified admin console at /admin

Workspace admins now have a single landing page that aggregates the
state procurement teams ask about before signing: member count by
role, pending invitations, active sessions, API keys with last-used
timestamps, recent audit events, and total classifications. The page
is admin-role gated by the FastAPI backend (`/v1/admin/overview` with
`require_role("admin")`), tenant-scoped to the caller's workspace,
and read-only. Non-admins see a denied state instead of a half-broken
UI; lower-privilege accounts that try the JSON endpoint get a 403.
Deep links from every card go to the existing management surfaces
(Members, Sessions, API keys, Audit, Usage).

### Try it

```bash
# Admin overview as JSON (admin role required).
curl -s 'http://localhost:7441/v1/admin/overview' \
  -H "x-api-key: $ACME_ADMIN_KEY" -H "x-tenant: acme" | jq .

# Same call with a viewer key -> 403.
curl -si 'http://localhost:7441/v1/admin/overview' \
  -H "x-api-key: $ACME_VIEWER_KEY" -H "x-tenant: acme" | head -1
```

UI lives at `/admin` in the web app.

## Previously: sandbox / dry-run mode on every destructive endpoint

Every mutating endpoint that deletes, revokes, or removes state now
accepts `?dry_run=true`. The API returns the counts that would change
without touching the database, sets the `X-Dry-Run: true` response
header, and writes an audit row tagged `extra.dry_run = true` so SIEM
filters can separate previews from real mutations. Enterprise admins
can now answer "what happens if I run this?" before they actually run
it, which is a hard requirement on every procurement checklist we have
seen.

Covered routes: `/v1/workspace/data`, `/v1/me/data`,
`/v1/history/{id}`, `/v1/history/bulk`, `/v1/saved-views/{id}`,
`/v1/sessions/{id}`, `/v1/sessions/revoke-all`,
`/v1/sessions/admin/revoke-principal`, `/v1/api-keys/{id}`,
`/v1/members/{principal}`, `/v1/invitations/{id}`, `/v1/mfa`,
`/v1/incident-subscriptions` (create, update, delete),
`/v1/settings/security/auth-lockout` (policy update),
`/v1/admin/lockouts/{id}` (clear), `/v1/trust/legal/enforcement`.

The browser surface lives at `/settings/sandbox` with a live preview
for bulk history deletes.

### Try it

```bash
# Preview a bulk delete of three shot ids without touching them.
curl -s -X POST 'http://localhost:7441/v1/history/bulk?dry_run=true' \
  -H "x-api-key: $ACME_ADMIN_KEY" -H "content-type: application/json" \
  -d '{"ids":["id-1","id-2","id-3"],"action":"delete"}'
# -> {"ok":true,"dry_run":true,"applied":false,"action":"delete",
#     "requested":3,"would_affect":2,"missing":["id-3"], ...}

# Preview workspace-wide GDPR erasure.
curl -si -X DELETE 'http://localhost:7441/v1/workspace/data?dry_run=true' \
  -H "x-api-key: $ACME_ADMIN_KEY" -H "x-tenant: acme" | grep -i x-dry-run

# Preview an incident-subscription delete; row is preserved.
curl -si -X DELETE 'http://localhost:7441/v1/incident-subscriptions/sub-123?dry_run=true' \
  -H "x-api-key: $ACME_ADMIN_KEY" -H "x-tenant: acme"
```

UI lives at `/settings/sandbox` in the web app.

## Previous: PII redaction and data residency per workspace

Workspace admins can now opt into automatic PII redaction on OCR text
and extracted fields, and pin a data residency label that every API
response echoes back. Redaction runs in the pipeline before persistence
and before any outbound webhook delivery, so neither the audit trail
nor downstream integrations see raw emails, phones, SSNs, credit cards,
IPs, or IBANs. Classification accuracy is untouched because the model
still sees the original image and OCR; only stored and shipped text is
sanitized. Credit cards are checked against Luhn so unrelated 16 digit
runs are not eaten by the redactor.

The data residency label (e.g. `us`, `eu`) ships in an
`X-Data-Residency` response header on every tenant scoped route, which
is what a procurement reviewer wants to curl and screenshot.

### Try it

```bash
# Admin reads current privacy config for their workspace.
curl -s http://localhost:7441/v1/settings/security/privacy \
  -H "x-api-key: $ACME_ADMIN_KEY"

# Admin enables redaction and pins residency. MFA step-up enforced.
curl -s -X PUT http://localhost:7441/v1/settings/security/privacy \
  -H "x-api-key: $ACME_ADMIN_KEY" -H "content-type: application/json" \
  -d '{"redact_modes":["email","phone","ssn","credit_card"],"data_residency":"eu"}'

# Subsequent responses now carry the residency header.
curl -si http://localhost:7441/v1/settings/security/privacy \
  -H "x-api-key: $ACME_ADMIN_KEY" | grep -i x-data-residency
```

UI lives at `/settings/security/privacy` in the web app.

## Previous: audit log UI for workspace admins

The audit trail that the FastAPI middleware has been writing on every
authenticated mutation now has a first-class admin surface at
`/settings/audit`. Workspace admins can filter by principal or path
prefix, expand any row to see the request ID, tenant, target, and the
full `extra` payload, and export the filtered result set to CSV.

The page calls a new Next.js proxy at `/api/audit` that forwards the
browser session cookie (or workspace API key) to FastAPI's `/v1/audit`
endpoint, which is already guarded by `require_role("admin")` and is
tenant scoped by the existing audit middleware. Non-admins get a clear
"admin role required" empty state instead of a raw 403.

A new `Audit` entry in the global nav joins `Security`, `MFA`,
`Sessions`, `Data`, and `Members` so the full enterprise settings set
is reachable from one place.

### Try it

```bash
cd web && npm run dev       # http://localhost:3000/settings/audit

# Or call the proxy directly with a workspace admin API key:
curl -sS "http://localhost:3000/api/audit?limit=50&path_prefix=/v1/history" \
  -H "x-api-key: $SHOTCLASSIFY_KEY"

# CSV export respects the active filters:
curl -sS "http://localhost:3000/api/audit?limit=500&format=csv" \
  -H "x-api-key: $SHOTCLASSIFY_KEY" -o audit.csv
```

## Previous: tenant-scoped webhook subsystem

Webhook subscriptions, deliveries, the per-workspace outbound
allowlist, dispatch fan-out, and redelivery are now strictly
partitioned by `workspace_id`. A caller in `acme` cannot list, fetch,
delete, redeliver, or even discover the existence of a webhook owned
by `globex`, and `dispatchEvent(workspace, ...)` only targets that
workspace's hooks. Legacy rows written before this change are
transparently bound to the default workspace on read so existing
installs keep working without a manual migration.

Every webhook API route (`/api/webhooks*`, `/v1/webhooks*`, allowlist
endpoints) now resolves the caller's tenant from the API key or
session and passes it through to the store layer. Cross-tenant access
is covered by a dedicated test (`lib/webhooks-tenant-isolation.test.mts`)
that verifies list isolation, get/delete refusal, dispatch fan-out
scoping, delivery + redeliver scoping, and allowlist partitioning.

### Try it

```bash
cd web && npm test          # 88 tests, includes 5 cross-tenant cases
npm run dev                 # http://localhost:3000/webhooks

# Create a workspace-bound API key from the dashboard at /keys
# (set the Workspace field to e.g. acme), then:
curl -sS -X POST http://localhost:3000/v1/webhooks \
  -H "Authorization: Bearer $SHOTCLASSIFY_KEY" \
  -H "content-type: application/json" \
  -d '{"url":"https://example.com/hook","events":["classify.completed"]}'
# Response includes the signing secret once. The webhook is bound to the
# workspace_id encoded in the API key and is invisible to other tenants.
```

## Previous: workspace-wide GDPR export and erasure

Workspace owners can now export everything stored for their workspace
as a single ZIP bundle, and permanently erase it. The endpoint is
admin only, requires TOTP step-up MFA, and is scoped strictly to the
caller's tenant: an admin in `tenant-a` cannot read or delete anything
in `tenant-b`, even with the legacy `X-Tenant` override.

The ZIP contains `manifest.json`, `classifications.json`,
`audit_log.json`, `saved_views.json`, `members.json`,
`invitations.json`, `api_keys.json` (metadata only, no token material),
and `settings.json` (IP allowlist, retention policy, SSO config without
the client secret).

Erasure removes every classification, audit row, saved view, and
stored blob in the workspace. Memberships, API keys, SSO, and the IP
allowlist are preserved so the admin can still sign in to confirm.

### Try it

Open the dashboard at `http://127.0.0.1:3000/settings/data`, or hit
the API directly:

```bash
# Export the workspace as a ZIP (admin role + MFA step-up required)
curl -sS -X GET \
  -H "x-api-key: $SHOTCLASSIFY_ADMIN_KEY" \
  -H "x-tenant: acme" \
  -H "x-mfa-otp: 123456" \
  -o workspace-acme.zip \
  http://127.0.0.1:7441/v1/workspace/data

# Preview what an erase would remove, without mutating
curl -sS -X DELETE \
  -H "x-api-key: $SHOTCLASSIFY_ADMIN_KEY" \
  -H "x-tenant: acme" \
  -H "x-mfa-otp: 123456" \
  "http://127.0.0.1:7441/v1/workspace/data?dry_run=true"

# Hard-delete (irreversible)
curl -sS -X DELETE \
  -H "x-api-key: $SHOTCLASSIFY_ADMIN_KEY" \
  -H "x-tenant: acme" \
  -H "x-mfa-otp: 123456" \
  "http://127.0.0.1:7441/v1/workspace/data?confirm=erase"
```

## Previous: workspace members + email invitations with one-shot tokens

Workspace admins can now manage who has access to a tenant from the
product, not from a YAML file. Roles assigned to a member in the
`memberships` table override the legacy `AUTH_ROLE_MAP` env var on every
request, so promoting a teammate to admin no longer requires a redeploy.

What ships:

- `memberships` and `invitations` tables (Alembic `0013_memberships`),
  both strictly scoped by `tenant_id`. Invitation tokens are stored as
  SHA-256 hashes; the plaintext is shown exactly once.
- `GET/PUT/DELETE /v1/members` and `GET/POST/DELETE /v1/invitations` plus
  `POST /v1/invitations/accept` for the invitee. All admin mutations
  require the admin role and MFA step-up.
- Last-admin guard: the API refuses to demote or remove the last admin
  of a workspace (409), so a misclick can't lock the workspace out of
  role management.
- Auth middleware now prefers the member's role over the env-var map and
  the audit middleware records every mutation with actor, tenant, IP,
  and target id.
- Settings UI at `/settings/members` for invite, role change, revoke,
  and remove. Built with shadcn/ui patterns and Phosphor duotone icons.
- Six tests in `tests/test_memberships.py` proving cross-tenant
  isolation, last-admin protection, and single-use invite tokens.

### Try it

```bash
make api                 # serves on :7441
pnpm --dir web dev       # /settings/members

# Invite a teammate (admin key on tenant acme):
curl -s -X POST http://127.0.0.1:7441/v1/invitations \
  -H 'x-api-key: admin-key' \
  -H 'content-type: application/json' \
  -d '{"email":"alice@company.com","role":"operator","ttl_days":7}'
```

## What's new: DB-backed API keys with scopes, expiry, and revocation

The FastAPI service now treats the `api_keys` table as the source of truth
for `X-API-Key` authentication instead of reading keys from environment
variables only. Each key carries:

* **Scopes** (`read:classifications`, `write:classifications`, `read:audit`,
  `admin`) checked by a new `require_scope(...)` dependency on every
  mutating route. Issue a read-only key to a partner without giving them
  write or admin access.
* **Hard tenant binding**: the resolved tenant for a key is whatever was
  set when it was minted. `X-Tenant` overrides are ignored for DB-backed
  keys, so a leaked credential cannot read another workspace even if the
  attacker has the admin scope.
* **Lifecycle**: optional `ttl_days`, soft `revoked_at`, and `last_used_at`
  bumped on every successful request so the admin console can show live
  key activity.
* **Audit trail**: create and revoke are gated by MFA step-up and recorded
  by the audit middleware with the new key id as `target_id`.

Plaintext tokens (`sk_live_...`) are returned exactly once at creation and
never persisted. Lookups are by SHA-256 hash so a stolen database snapshot
yields no usable credentials. The legacy `AUTH_API_KEY` / `AUTH_API_KEYS`
environment variables still work as a fallback for bootstrap and CI.

### Try it

```bash
make api  # FastAPI on http://localhost:8000

# 1. Mint a read-only key as the bootstrap admin.
curl -sS -X POST http://localhost:8000/v1/api-keys \
  -H "X-API-Key: dev-api-key-change-me" \
  -H "content-type: application/json" \
  -d '{"label":"partner-readonly","scopes":["read:classifications"],"ttl_days":90}'
# -> {"id":"...","token":"sk_live_...","token_display_once":true,...}

# 2. The new key can read history...
curl -sS http://localhost:8000/v1/history -H "X-API-Key: sk_live_..."

# 3. ...but classify writes are rejected with 403 for missing scope.
curl -sS -X POST http://localhost:8000/v1/classify \
  -H "X-API-Key: sk_live_..." -F file=@samples/cricket.jpg

# 4. List and revoke from the same admin context.
curl -sS http://localhost:8000/v1/api-keys -H "X-API-Key: dev-api-key-change-me"
curl -sS -X DELETE http://localhost:8000/v1/api-keys/<key_id> \
  -H "X-API-Key: dev-api-key-change-me"
```

Migration: `alembic upgrade head` (or rely on `init_db()` in dev). Covered
by `tests/test_api_keys_db.py` (scope denial, revoke 401, hard tenant
binding, cross-tenant revoke-by-id rejection).

## Previous: SSRF protection for outbound webhooks

Webhook deliveries now refuse to POST to loopback, link-local, private,
multicast, broadcast, or cloud metadata addresses. The check runs at both
save time (so the dashboard rejects a bad URL immediately) and at every
delivery attempt (so DNS rebinding cannot redirect a previously-approved
hostname to an internal IP). Cloud metadata endpoints like
`169.254.169.254` are blocked unconditionally and cannot be allowlisted.

Workspace owners who do need to deliver to private destinations can add
explicit hostname exceptions on the Webhooks page under "Outbound
delivery safety". Blocked attempts are recorded in the delivery log with
an `ssrf_blocked:<reason>` error so incident response still has an
audit trail.

### Try it

```bash
cd web && npm run dev
open http://localhost:3000/webhooks

# Attempt a metadata-service URL via the API; this MUST 400.
curl -sS -X POST http://localhost:3000/v1/webhooks \
  -H "Authorization: Bearer sk_live_xxx" \
  -H "content-type: application/json" \
  -d '{"url":"http://169.254.169.254/latest/meta-data"}'

# Read or update the workspace allowlist.
curl -s http://localhost:3000/api/webhooks/allowlist
curl -sS -X PUT http://localhost:3000/api/webhooks/allowlist \
  -H "content-type: application/json" \
  -d '{"hostnames":["internal-hook.corp.lan"]}'
```

Covered by `web/lib/url-safety.test.mts` and the SSRF assertions in
`web/lib/webhooks.test.mts` (`npm test`).

## What's new: TOTP step-up MFA for admin mutations

Destructive admin actions now require a recent second factor on top of the role check. The `require_mfa_step_up()` dependency is wired onto every mutating admin route (IP allowlist PUT, retention PUT, retention run, SSO config PUT, routing-rules PUT, admin force-logout-principal) so a stolen browser session alone cannot reconfigure tenant security. API-key callers (machine-to-machine) bypass MFA because the key itself is a possession factor.

Enroll an authenticator at http://localhost:3000/settings/mfa, or via the API:

```sh
# 1. Start enrollment (returns secret + otpauth URI for any TOTP app)
curl -s -X POST http://127.0.0.1:7441/v1/mfa/setup -b cookies.txt | jq

# 2. Confirm with a current 6-digit code from the authenticator
curl -s -X POST http://127.0.0.1:7441/v1/mfa/verify \
  -H 'content-type: application/json' \
  -d '{"code":"123456"}' -b cookies.txt | jq

# 3. Subsequent admin mutations work for the next MFA_STEP_UP_WINDOW_SECONDS (default 900).
#    Re-stamp the session with POST /v1/mfa/challenge {code} when the window lapses.
```

Without an enrolled credential, mutating admin endpoints return `401 {"error":"mfa_enrollment_required"}`. With one enrolled but the window lapsed, they return `401 {"error":"mfa_required","window_seconds":900}` so the UI can prompt for a fresh code. Coverage in `tests/test_mfa_step_up.py` proves enrollment unlocks the action, an expired stamp blocks it, and a re-challenge restores access.

## What's new: SSO domain auto-join for zero-touch onboarding

Enterprise buyers expect "everyone at acme.com lands in the Acme workspace" without an admin clicking invite for every hire. Each workspace can now set an `auto_join_role` alongside its SSO `domain`. The first time someone from that domain completes the OIDC sign-in, a membership is created automatically with that role. Existing memberships are never downgraded, users from other domains never auto-join, and `admin` is rejected as an auto-join role so DNS control alone cannot promote anyone to admin.

Try it:

```
curl -s -X PUT http://127.0.0.1:7441/v1/settings/security/sso \
  -H 'x-api-key: ADMIN_KEY' -H 'content-type: application/json' \
  -d '{"enforced": false, "domain": "acme.com", "provider": "Okta", "auto_join_role": "viewer"}'
```

The same control lives in the dashboard at http://localhost:3000/settings/security under the SSO card ("Domain auto-join").

## What's new: enterprise SSO (OIDC) with per-workspace enforcement

Wire one OIDC identity provider (Google Workspace, Okta, Azure AD, Auth0, Keycloak) for the deployment, then opt each tenant in by claiming its email domain and turning on enforcement. When `enforced=true`, the auth middleware refuses any session for that tenant that was not minted via `/auth/sso/callback`. API-key (machine-to-machine) callers are unaffected.

Configure the IdP via env on the API:

```
AUTH_SSO_ENABLED=true
AUTH_SSO_ISSUER=https://accounts.google.com
AUTH_SSO_CLIENT_ID=...
AUTH_SSO_CLIENT_SECRET=...
# optional: AUTH_SSO_REDIRECT_URI=https://app.example.com/auth/sso/callback
```

Admins manage per-workspace SSO at http://localhost:3000/settings/security ("Single sign-on (OIDC)" card), or via the API:

```
curl -s -X PUT http://127.0.0.1:7441/v1/settings/security/sso \
  -H 'x-api-key: ADMIN_KEY' -H 'content-type: application/json' \
  -d '{"enforced": true, "domain": "acme.com", "provider": "Okta"}'
```

Domain claims are unique across tenants so a second workspace cannot hijack another tenant's email routing. Sign-in begins at `GET /auth/sso/login?email=alice@acme.com`.


ShotClassify is a real-time screenshot classifier with confidence scores, OCR, history, share links, and a programmatic /v1 API.

## What's new: revocable browser sessions

Browser sessions are now tracked server-side. Every cookie carries an opaque session id that maps to a row in the `sessions` table, so the app can show every device a user is signed in on, revoke any one of them, and force-logout every other device with one click. The signed-cookie-only approach we used to ship could not actually invalidate a stolen cookie before its 30-day TTL, which is a deal-blocker for SOC2 CC6.1 and for most enterprise security reviews. It can now.

Manage your sessions in the dashboard at `/settings/sessions`, or via the API:

```sh
# List your active sessions (uses the sc_session cookie)
curl -s http://localhost:7441/v1/sessions -b cookies.txt | jq

# Revoke a single session by id
curl -s -X DELETE http://localhost:7441/v1/sessions/$SID -b cookies.txt | jq

# Force-logout every other device but keep this one signed in
curl -s -X POST 'http://localhost:7441/v1/sessions/revoke-all?keep_current=true' \
  -b cookies.txt | jq
```

`POST /auth/logout` also revokes the underlying session row so a copied cookie cannot be replayed. Admins get `GET /v1/sessions/admin` and `POST /v1/sessions/admin/revoke-principal?principal=<login>` to kick any user out of every device. Cross-principal isolation, force-logout-keep-current, and the logout-revokes-row contract are covered by `tests/test_sessions.py`.

### Try it

```sh
make dev        # API on :7441, web on :3000
open http://localhost:3000/settings/sessions
```

## What's new: per-tenant data retention policy

Admins can now set a per-tenant retention window in days. Classifications older than the window are hard-deleted by the retention job. The audit log is preserved for compliance, blob files are unlinked, and the policy is enforced strictly per tenant so one workspace's policy can never touch another workspace's data. Set it to 0 or leave it empty to keep data forever, which matches the prior behavior so existing deployments are unaffected.

Manage it in the dashboard at `/settings/security`, or via the admin API:

```sh
# Inspect the current policy for your tenant
curl -s http://localhost:7441/v1/settings/security/retention \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY" | jq

# Set a 30-day retention window
curl -s -X PUT http://localhost:7441/v1/settings/security/retention \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY" \
  -H 'content-type: application/json' \
  -d '{"retention_days":30}' | jq

# Trigger an immediate purge for your tenant
curl -s -X POST http://localhost:7441/v1/settings/security/retention/run \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY" | jq
```

For scheduled enforcement, wire `shotclassify retention-purge` into cron or a systemd timer to sweep every tenant with a policy. Covered by `tests/test_retention_policy.py`.

## What's new: per-tenant IP allowlist

Workspace admins can now restrict API and dashboard access to a set of CIDR ranges. The check runs as middleware before any route handler, is enforced per tenant (one tenant's allowlist cannot leak across to another), and skips healthcheck and metrics endpoints so kubelet probes never trip. Changes are written through the audit log.

Manage it in the dashboard at `/settings/security`, or via the admin API:

```sh
# Read the current allowlist for your tenant
curl -s http://localhost:7441/v1/settings/security/ip-allowlist \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY" | jq

# Replace it with a fixed corporate range plus one bastion IP
curl -s -X PUT http://localhost:7441/v1/settings/security/ip-allowlist \
  -H "X-API-Key: $SHOTCLASSIFY_ADMIN_KEY" \
  -H 'content-type: application/json' \
  -d '{"cidrs":["10.0.0.0/24","203.0.113.42"]}' | jq
```

An empty list disables the allowlist for that tenant, so existing deployments keep working until an admin opts in. Covered by `tests/test_ip_allowlist.py`.

## What's new: pinned shots

Every row on `/shots` now has a star. Click it to pin the shot, click again to unpin. The history toolbar has a "Pinned only" toggle, the detail page has a Pin button, and the bulk action bar gained Pin and Unpin so you can star a whole filtered set in one click. Pinned state is real database state, scoped to your tenant, and surfaces through `/v1/history`.

Try it:

```sh
cd web && pnpm dev
open http://localhost:3000/shots
# Star a row, then flip the "Pinned" toggle in the filter bar.

# Pin a shot programmatically:
curl -s -X PATCH http://localhost:3000/api/shots/<id> \
  -H 'content-type: application/json' \
  -d '{"pinned":true}' | jq

# Only pinned shots in history:
curl -s 'http://localhost:3000/api/history?pinned=true' | jq '.[].id'
```

Covered by `tests/test_history_pinned.py`.

## What's new: programmatic webhook management via /v1/webhooks

The `/v1/webhooks` endpoint lets API users register, list, fetch, and delete webhook subscriptions without opening the dashboard. Same `Authorization: Bearer sk_...` header the rest of /v1 uses. The signing secret is returned exactly once at creation time.

Try it locally (after `cd web && pnpm dev`, then create a key at http://localhost:3000/keys):

```bash
export SHOTCLASSIFY_KEY=sk_live_...

# Register a subscription
curl -X POST http://localhost:3000/v1/webhooks \
  -H "Authorization: Bearer $SHOTCLASSIFY_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/incoming","events":["classify.completed"]}'

# List them
curl http://localhost:3000/v1/webhooks \
  -H "Authorization: Bearer $SHOTCLASSIFY_KEY"

# Delete one
curl -X DELETE http://localhost:3000/v1/webhooks/<id> \
  -H "Authorization: Bearer $SHOTCLASSIFY_KEY"
```

Full reference is rendered at http://localhost:3000/api-docs.

> Real-time screenshot classifier with confidence scoring, OCR, history, sharing, API keys, webhooks, and a Cmd+K command palette.

## What's new: admin scope for API keys

API keys now support three scope tiers: `read`, `write`, and `admin`. Admin
implies write implies read, enforced server-side via `normalizeScopes`.
Registering or deleting a webhook through `/v1/webhooks` now requires the
`admin` scope so an integration token cannot quietly pipe workspace data
to a third party with a routine write key. Read and classify behavior is
unchanged. Pick the tier on the keys page or toggle it inline on the key
detail page.

Try it:

```bash
open http://localhost:3000/keys
# create a read+write key, then try registering a webhook
curl -sS -X POST http://localhost:3000/v1/webhooks \
  -H "Authorization: Bearer sk_live_..." \
  -H "content-type: application/json" \
  -d '{"url":"https://example.com/hook"}'
# -> {"error":{"code":"insufficient_scope","message":"This API key is missing the 'admin' scope."}}
```

## What's new: per-key usage detail page

Every API key now has its own page at `/keys/<id>` with a 30-day request
sparkline, inline rename, scope toggle, one-click rotate, revoke, and a
copy-paste curl that prefills the key prefix. `verifyAndTouch` now records
a per-UTC-day counter (kept for 90 days) on top of the existing lifetime
total, so the chart reflects real traffic.

Try it:

```sh
cd web && npm run dev
open http://localhost:3000/keys
# Then click a key row to land on /keys/<id>.

# Detail JSON, including the dense 30-day series:
curl -s 'http://localhost:3000/api/keys/<id>?days=30' | jq '.usage'

# Rename or scope-edit:
curl -s -X PATCH http://localhost:3000/api/keys/<id> \
  -H 'content-type: application/json' \
  -d '{"name":"ci-bot","scopes":["read"]}' | jq
```

Covered by `web/lib/keystore.test.mts` (`npm test`).

## What's new: webhook delivery filters and pagination

The per-webhook delivery log at `/webhooks/<id>` now supports filtering by
status (success, failed, pending) and by event name, plus a load-more pager
so receivers with thousands of deliveries are actually browsable. The page
has an empty-state for filtered-no-match, a counter showing
`shown / total`, and the filters reset pagination when changed. The API
route accepts `status`, `event`, `offset`, and `limit` query params and
returns `{ deliveries, total, offset, limit, has_more, events }`.

Try it:

```sh
cd web && npm run dev
open http://localhost:3000/webhooks

# Filtered, paginated delivery log JSON
curl -s 'http://localhost:3000/api/webhooks/<id>?status=failed&limit=10&offset=0' | jq
```

Covered by `web/lib/webhooks.test.mts` (`npm test`).

## What's new: activity digest

A real activity recap lives at `/digest`. Pick a 7, 14, or 30 day window and
you get total shots, average confidence, a daily sparkline, a breakdown by
category, and your top-confidence results. "Send to inbox" writes a real
RFC 5322 multipart message to `storage/digest_outbox/` that you can pipe to
an SMTP relay or inspect directly. Set `DIGEST_TO` and `DIGEST_FROM` in the
environment to control headers; wire `sendmail` against the outbox file to
actually deliver.

Try it:

```sh
cd web && npm run dev
# UI
open http://localhost:3000/digest

# JSON preview (includes rendered text + html)
curl -s 'http://localhost:3000/api/me/digest?days=7' | jq '.summary | {total_shots, avg_confidence, by_category}'

# Plaintext or HTML rendering
curl -s 'http://localhost:3000/api/me/digest?days=7&format=text'
curl -s 'http://localhost:3000/api/me/digest?days=7&format=html'

# Generate an .eml in storage/digest_outbox
curl -s -XPOST http://localhost:3000/api/me/digest \
  -H 'content-type: application/json' \
  -d '{"days":7,"to":"you@example.com"}' | jq
```

Pure aggregation lives in `web/lib/digest.ts` and is covered by
`web/lib/digest.test.mts` (`npm test`).

## What's new: global command palette (Cmd/Ctrl+K)

Hit `⌘K` (or `Ctrl+K`, or `/` outside an input) from any page to open the
command palette. It jumps you to any major page and live-searches your
classification history (filename, OCR, label, tags) through the existing
`/api/history?q=...` endpoint. Arrow keys navigate, Enter selects, Esc
closes.

Try it locally:

```sh
# Start the web app (Next.js 15)
cd web && npm run dev
# Open http://localhost:3000 and press Cmd+K

# The palette uses the same history search endpoint:
curl -s 'http://localhost:3000/api/history?q=invoice&limit=8' | jq '.items[0]'
```

Pure ranking helpers live in `web/lib/command-palette.ts` and are covered by
`web/lib/command-palette.test.mts` (`npm test`).

Screenshot classifier with vision LLM, OCR, structured extraction, and action routing. Drop in an image, get back a category with confidence and a saved record you can browse, share, or pull back via API.

## What's new: notifications search, kind filter, and pagination

The `/notifications` inbox is now usable past the first 25 entries.
There is a real search box (matches title, body, and kind), a kind
selector (Classifications / Webhook failures / System), an "unread
only" toggle, and a `Load more` cursor at the bottom. Filters are
applied server-side via the same `/api/notifications` route, which
now accepts `q`, `kind`, `unread_only`, `cursor`, and `limit`. The
bell and any caller that doesn't pass query params keeps the
original `{items, unread}` response shape so existing integrations
don't break.

### Try it

```bash
open http://localhost:3000/notifications

# Or drive the paged endpoint directly:
curl 'http://localhost:3000/api/notifications?paged=1&limit=25'
curl 'http://localhost:3000/api/notifications?q=webhook&kind=webhook.failed&unread_only=1'
```

Covered by `web/lib/notif-query.test.mts` (7 tests).

## What's new: notification preferences

The `/notifications` page now has a Preferences card that lets you mute
any notification kind (`classify.completed`, `webhook.failed`,
`system`). Muted kinds are dropped at the source by `notify()`, so they
never show up in the bell or the inbox until you re-enable them. Prefs
are persisted to `storage/notification_prefs.json` and exposed as a
first-class API at `/api/notifications/prefs`. Defaults stay backwards
compatible: every kind is enabled until you change it.

### Try it

```bash
# Open the inbox and flip a switch under "Preferences":
open http://localhost:3000/notifications

# Or drive it from the API:
curl http://localhost:3000/api/notifications/prefs

curl -X PUT http://localhost:3000/api/notifications/prefs \
  -H 'content-type: application/json' \
  -d '{"enabled":{"classify.completed":false}}'
```

Covered by `web/lib/notification-prefs.test.mts`.

## What's new: scoped API keys (read vs. read+write)

When you generate a key at `/keys` you now pick its scope. Read-only
keys can list and fetch shots and report their own usage, but cannot
call `POST /v1/classify` (the classifier returns `403
insufficient_scope` with a clear message). Read+write keys behave like
before. The scope is shown as a badge in the keys table, returned on
`GET /v1/usage`, and surfaced as `x-api-key-scopes` on every
`/v1/*` response so dashboards can show the calling key's permissions.
Legacy keys with no stored scope keep working with full access and get
backfilled on next use.

### Try it

```bash
# 1. Open the keys page and create a read-only key.
open http://localhost:3000/keys   # pick "Read only" in the Scope dropdown

# 2. List your shots (works with read-only).
curl -H "Authorization: Bearer sk_live_YOUR_READ_KEY" \
  http://localhost:3000/v1/shots?limit=5

# 3. Try to classify (read-only key gets blocked).
curl -i -X POST \
  -H "Authorization: Bearer sk_live_YOUR_READ_KEY" \
  -F "file=@samples/example.png" \
  http://localhost:3000/v1/classify
# -> HTTP/1.1 403 Forbidden
# -> {"error":{"code":"insufficient_scope",...}}
```

## What's new: per-webhook delivery log with one-click replay

Every webhook subscription now has its own detail page at
`/webhooks/<id>` that lists every recorded delivery attempt with HTTP
status, latency, attempt counter, error text, and the first 240 bytes of
the signed payload. Failed deliveries can be replayed against the
current target URL with a single click, which fires a fresh signed POST
that references the original delivery id (`replay_of`) so receivers can
dedupe. The signing secret prefix is shown for quick HMAC verification.

New route: `PATCH /api/webhooks/{id}` now accepts
`{ "action": "redeliver", "delivery_id": "..." }` in addition to the
existing `test` and `active` actions. The replay is a single attempt and
returns the new `Delivery` record. Covered by `web/lib/webhooks.test.mts`.

### Try it

```bash
make dev   # or: pnpm --dir web dev  +  uvicorn services.api.main:app --port 7441

open http://localhost:3000/webhooks            # create a subscription
open http://localhost:3000/webhooks/<id>       # detail page + delivery log

# Replay a failed delivery from the shell
curl -sS -X PATCH http://localhost:3000/api/webhooks/<webhook-id> \
  -H "content-type: application/json" \
  -d '{"action":"redeliver","delivery_id":"<delivery-id>"}' | jq
```

## What's new: public /v1 REST API + docs page

The programmatic surface now goes beyond `POST /v1/classify`. Customers
with a `sk_live_` API key can also list and fetch their saved shots, and
inspect their key's usage counters, without scraping the internal
`/api/*` routes. A new `/api-docs` page renders copy-paste curl for every
endpoint against the visitor's current origin, so the snippets run
as-is. The header navigation links straight to it.

New endpoints, all authenticated with `Authorization: Bearer sk_live_...`:

- `GET /v1/shots` — list shots (filters: `limit`, `offset`, `category`, `since`, `until`, `min_confidence`, `q`, `tag`, `sort`; limit capped at 200)
- `GET /v1/shots/{id}` — fetch one shot
- `GET /v1/usage` — return the calling key's identity and usage count

Query filtering, limit caps, and id validation live in pure helpers in
`web/lib/v1-core.ts` and are covered by `web/lib/v1-core.test.mts`.

### Try it

```bash
# Boot both services
make dev   # or: pnpm --dir web dev  +  uvicorn services.api.main:app --port 7441

# Create an API key in the UI
open http://localhost:3000/keys
open http://localhost:3000/api-docs

# Then drive the API from the shell
export SHOTCLASSIFY_KEY=sk_live_...

curl -sS http://localhost:3000/v1/shots?limit=5 \
  -H "Authorization: Bearer $SHOTCLASSIFY_KEY" | jq

curl -sS http://localhost:3000/v1/usage \
  -H "Authorization: Bearer $SHOTCLASSIFY_KEY" | jq
```

## Previously shipped: in-app notifications inbox

A bell in the header lights up every time a classification finishes or a
webhook delivery exhausts its retries. Click through to `/notifications`
for the full inbox: filter by unread, mark read individually or in bulk,
open straight into the shot or webhook that triggered it, and clear the
log when you are done. New notifications also pop a small toast in the
corner so a long-running batch tells you the moment it lands. Backed by
an atomic file-backed store, capped at 200 entries, with unit tests in
`web/lib/notifications.test.mts`.

### Try it

```bash
# Boot both services
make dev   # or: pnpm --dir web dev  +  uvicorn services.api.main:app --port 7441

# Drop a classification through and watch the bell update:
curl -sS -X POST http://localhost:3000/api/classify \
  -F file=@samples/menu.png

# Read the inbox via the same API the UI uses:
curl -sS http://localhost:3000/api/notifications | jq

# Mark everything read:
curl -sS -X POST http://localhost:3000/api/notifications \
  -H 'content-type: application/json' \
  -d '{"action":"mark_all_read"}'
```

Open <http://localhost:3000/notifications> to see the page.

## Previously shipped: saved views on your history

The `/shots` page now ships **saved views**: name any combination of
filters (class, search, date range, min confidence, tag, sort) and snap
back to it in one click on your next visit. Views are scoped per user
via the same auth used everywhere else (session login or API key), so a
teammate's saved "low-confidence yesterday" never leaks into your bar.

### Try it

```bash
# Open the web UI
open http://localhost:3000/shots

# Or drive it from the API:
curl -sS -X POST http://localhost:7441/v1/saved-views \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  -H "content-type: application/json" \
  -d '{"name":"Low conf receipts","filters":{"category":"receipt","min_conf":0.4,"sort":"conf_asc"}}'

curl -sS http://localhost:7441/v1/saved-views -H "x-api-key: $SHOTCLASSIFY_API_KEY"
```

Filter payloads are whitelist-coerced server-side, capped at 50 views
per user, and migrated in by `alembic upgrade head` (or auto-created on
first SQLite boot).

## What's new: rotate API keys without downtime

The `/keys` page now ships a one-click **Rotate** action next to every
key. Rotating issues a fresh `sk_live_...` secret, invalidates the prior
one immediately, and keeps the key's name, created date, and lifetime
usage count so dashboards and audit trails stay coherent. The new secret
is shown exactly once in the same reveal banner used at creation, so the
copy flow is muscle memory.

### Try it

```bash
# Open the web UI
open http://localhost:3000/keys

# Or rotate from the API: returns the new plaintext exactly once.
curl -sS -X POST http://localhost:3000/api/keys/$KEY_ID/rotate
```

Response shape: `{key: {id, name, prefix, created_at, last_used_at, usage_count, rotated_at}, plaintext}`.
Run `npm test` inside `web/` to exercise the rotation unit tests.

## What's new: bulk actions on your history

ShotClassify classifies a screenshot into a typed record with confidence, OCR text, and extracted fields.

The `/shots` page now ships real bulk actions over your saved history. Tick the new left-most checkbox on any row (or the page-header checkbox to grab the whole page), then add tags, remove tags, or delete the lot in one call. Scoped to your tenant, hard-capped at 500 ids per request, validated server-side.

### Try it

```bash
# Add two tags to a batch of shots
curl -sS -X POST http://localhost:7441/v1/history/bulk \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  -H "content-type: application/json" \
  -d '{"ids":["abc123","def456"],"action":"tag_add","tags":["finance","reviewed"]}'

# Bulk delete
curl -sS -X POST http://localhost:7441/v1/history/bulk \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  -H "content-type: application/json" \
  -d '{"ids":["abc123","def456"],"action":"delete"}'
```

Response shape: `{ok, action, requested, affected, missing, tags}`. The web UI lives at `http://localhost:3000/shots`.

## What's new: rename and tag your shots

Every saved classification can now be renamed and tagged from the shot
detail page. Labels and tags are scoped to the caller's tenant and the
`/shots` history page filters by tag. Click any tag chip in the table to
filter the list to that tag in one click.

```bash
# Rename and tag a saved shot. `label: null` clears the rename.
curl -s -X PATCH http://127.0.0.1:7441/v1/history/$SHOT_ID \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  -H "content-type: application/json" \
  -d '{"label": "Q3 receipts", "tags": ["finance", "reviewed"]}'

# List only shots carrying a tag.
curl -s "http://127.0.0.1:7441/v1/history?tag=finance&limit=20" \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY"
```

Open `http://127.0.0.1:3000/shots/<id>` in the web app to use the editor.
Tags are normalized to lowercase, deduped, and capped at 16 per shot.

## What's new: web sign-in

The web UI now has a real GitHub sign-in flow. Hit `/signin` (or the avatar in
the header) to start a GitHub OAuth round-trip; the resulting `sc_session`
cookie is what every authenticated page already uses for per-user history,
keys, webhooks, and quota.

### Try it

```bash
# Backend
make api          # FastAPI on http://127.0.0.1:7441

# Web
cd web && pnpm dev   # http://localhost:3000/signin

# Check session from the CLI
curl -s http://127.0.0.1:7441/auth/whoami -H "X-API-Key: $SHOTCLASSIFY_API_KEY"
# => {"principal": "api-key:..."}
```

Set `AUTH_OAUTH_CLIENT_ID` / `AUTH_OAUTH_CLIENT_SECRET` on the API to enable
the GitHub button; without them `/signin` still works and shows an actionable
empty state.

![landing](docs/screenshots/landing.png)

## What it does

Takes a screenshot upload, runs OCR (Tesseract) and a vision LLM in parallel, and assigns one of nine categories with a per-class confidence vector. Saves the image, the OCR transcript, the model rationale, and the full classification record to SQLite (or Postgres) and exposes it via a FastAPI service. A Next.js web UI sits on top for upload, history browsing, per-shot inspection, and a calibration dashboard. Optional Redis/RQ queue handles batch loads; optional rules engine routes high-confidence shots to Slack or other sinks.

## Features

- `POST /v1/classify` single-image upload, returns `ProcessResult` with primary category, confidences, OCR text, rationale.
- `POST /v1/classify/batch` parallel multi-file classification.
- `POST /v1/classify/{id}/reclassify` rerun the pipeline on a stored image.
- `POST /v1/classify/{id}/correct` user-supplied ground truth, persisted for calibration.
- `POST /v1/queue` enqueue via Redis RQ when available, fall back to inline background task.
- `GET /v1/history` paginated history with category filter, full-text search over OCR + filename, date range (`since`/`until`), confidence range (`min_conf`/`max_conf`), `offset`, and `sort` (`new`, `old`, `conf_desc`, `conf_asc`). Returns `X-Total-Count`, `X-Offset`, and `X-Limit` headers so the UI can render a real pager.
- `GET /v1/history/stats` total count.
- `GET /v1/history/aggregate?hours=24` rich rollups for the analytics dashboard: per-class counts and mean confidence, latency p50/p95/p99, hourly ingest tempo, and a 10-bin confidence histogram. Powers the `/stats` page.
- `GET /v1/history/export?format=csv|json` streaming download of the classification history (honors `category`, `q`, and `limit` filters; up to 5000 rows). The shots page exposes an Export menu that hits the same endpoint.
- `GET /v1/history/{id}` full record with OCR transcript and confidence distribution.
- Web UI: upload page, shots list, per-shot detail with OCR transcript, `/stats` analytics dashboard with class mix, calibration histogram, ingest tempo, and latency percentiles, plus a calibration page with reliability diagram and ECE/Brier/Log loss.
- Side-by-side compare view at `/compare?a=<id>&b=<id>`: pick any two shots from history (or pass IDs via URL), see class chips, full probability distributions, OCR text, and a delta summary (same-class, confidence delta, latency delta). Multi-select two rows on `/shots` and hit Compare to jump in.
- User-generated API keys at `/keys`: generate, copy once, list with prefix/created/last-used/call-count, revoke. Keys are hashed at rest. A new `POST /v1/classify` Next.js route accepts `Authorization: Bearer sk_live_...` and forwards to the FastAPI classifier, returning the same JSON the in-app uploader sees. Per-key usage counters tick on every call.
- Public share links at `/r/<shot-id>`: server-rendered, no-auth result pages with confidence distribution, OCR transcript, and a dynamic 1200x630 OpenGraph image for link previews on Slack, Twitter, iMessage, and LinkedIn. Each shot detail page has a one-click Copy share link button.
- Embeddable result cards at `/embed/<shot-id>`: a chrome-less HTML card (no app shell, no JavaScript, no cookies, framable from any origin via `Content-Security-Policy: frame-ancestors *`) that drops into Notion, Medium, Discourse, or any blog as an iframe. A `Copy embed` button on every share page and shot detail page hands users the snippet, and the share page advertises an oEmbed alternate so platforms with oEmbed auto-discovery (WordPress, Discourse, micro.blog) unfurl the card on paste. Try it: `curl -sS "http://localhost:3000/api/oembed?url=http://localhost:3000/r/<shot-id>" | jq` returns the JSON oEmbed document, and `curl -sS http://localhost:3000/embed/<shot-id>` returns the iframe-ready HTML.
- Outbound webhooks at `/webhooks`: register HTTPS endpoints that receive a signed JSON POST every time a classification completes. Each subscription gets a one-time `whsec_...` secret; deliveries are signed with `X-Shotclassify-Signature: sha256=<hmac>` over the raw body. Failed deliveries retry up to 4 times with backoff and every attempt is recorded in a live delivery log. Pause, resume, or send a test event from the dashboard.
- Bulk classify at `/batch`: drop a `.zip` (or a folder of stills) and the page extracts in the browser, fans the images out to the live classifier with bounded concurrency, tracks per-row status, surfaces shot IDs (each one persists to history and fires webhooks), and offers a one-click CSV export with id, filename, class, confidence, latency, and any error per row.
- Account & GDPR controls at `/account`: shows the signed-in principal (GitHub OAuth session or API key), counts of stored classifications and audit rows, one-click JSON export of everything under your principal, and a type-to-confirm "erase everything" button wired to `DELETE /v1/me/data?confirm=erase`. Sign in/out lives in the same panel.
- Usage & free-tier quota at `/usage`: per-principal monthly meter (read from `GET /v1/me/usage`) with progress bar, remaining count, plan comparison, and an upgrade CTA. The header carries a compact live meter on every page. Classify endpoints return `402 quota_exceeded` once the per-principal `SHOTCLASSIFY_FREE_MONTHLY_LIMIT` (default 200) is hit for the calendar month so customers see the wall before they hit it in code.

- First run onboarding at `/welcome`: a three step tour (classify a screenshot, browse history, get an API key) auto-opens once per browser via a dismissable overlay, and can be replayed from the Account page or the `/welcome` deep link.
- Pricing & upgrade-intent capture at `/pricing`: three-tier plan grid (Free / Pro / Team) with monthly classification ceilings, feature lists, and a modal that records an upgrade intent (plan, optional email, company, note) via `POST /api/billing/intent`. Intents persist to `storage/billing_intents.json` so operators have a real list of who clicked Upgrade before Stripe checkout is wired. The `/usage` page CTA and the over-limit nudge in the header `QuotaMeter` now both deep-link here, and a `/pricing/thanks?id=...&plan=...` confirmation page closes the loop. Try it: `curl -sS -X POST http://localhost:3000/api/billing/intent -H 'content-type: application/json' -d '{"plan":"pro","email":"you@example.com"}'`.
- Installable PWA with offline shell: `web/public/manifest.webmanifest` plus a service worker at `web/public/sw.js` precache the app shell and serve a friendly `/offline` page when the network drops. The header carries a one-time install prompt (Android/desktop Chromium) and an iOS Add-to-Home-Screen hint that respects a 14 day dismiss. API and `/v1` requests are never intercepted, so live classifier traffic always hits the backend. Try it: load `http://localhost:3000`, open DevTools > Application > Manifest to confirm install, then toggle the Network panel to Offline and reload to land on `/offline`.

## Try paginated history

```sh
# Page 2 of 25 rows, only high-confidence receipts from the last week:
curl -sS \
  -H "X-API-Key: $SHOTCLASSIFY_API_KEY" \
  -D - \
  "http://127.0.0.1:7441/v1/history?limit=25&offset=25&category=receipt&min_conf=0.8&sort=conf_desc&since=2025-01-01T00:00:00Z" \
  | head -30
```

The `/shots` page (http://127.0.0.1:3000/shots) wires the same parameters into a date range picker, a confidence slider, a sort dropdown, and First / Prev / Next / Last controls with `X-Total-Count` driven page counts.

## Try the onboarding tour

1. `cd web && pnpm install && pnpm dev`
2. Open http://127.0.0.1:3000 in a fresh incognito window. The three step tour appears over the live feed; arrow keys, mouse, or `Esc` all work.
3. Visit http://127.0.0.1:3000/welcome any time for the full page version, or `/account` to replay the tour from a returning session.

## Try the usage meter

```bash
make api  # starts FastAPI on :7441
make web  # starts Next.js on :3000

# Hit the meter directly:
curl -s -H "X-API-Key: $AUTH_API_KEY" http://127.0.0.1:7441/v1/me/usage | jq

# Or open it in the browser:
open http://localhost:3000/usage
```


## Try the account page

1. `cd web && pnpm dev` (or `npm run dev`), open http://localhost:3000/account.
2. You will see the principal the web app authenticates as (the configured `SHOTCLASSIFY_API_KEY`, or your GitHub login if you signed in via the API host).
3. Download a JSON bundle of every classification and audit row stored under that principal:

```bash
curl -sS -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  http://127.0.0.1:7441/v1/me/data > my-shotclassify-data.json
```

4. To permanently erase the same rows (used by the danger zone button):

```bash
curl -sS -X DELETE -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  "http://127.0.0.1:7441/v1/me/data?confirm=erase"
```

## Try batch

1. `cd web && pnpm dev` (or `npm run dev`), open http://localhost:3000/batch.
2. Drag a `.zip` of screenshots onto the drop zone. Hidden files and `__MACOSX/` entries are ignored.
3. Click `Run N` to classify. Concurrency is capped at 3 to keep your local model service happy.
4. When the run finishes, click `Download CSV` to grab the consolidated result file. Each row also links into `/shots/<id>` for full inspection.

Or drive the same path from the CLI with the existing batch endpoint:

```
curl -X POST http://127.0.0.1:7441/v1/classify/batch \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  -F "files=@shot1.png" -F "files=@shot2.png" -F "files=@shot3.png"
```

## Try webhooks

1. `cd web && pnpm dev` (or `npm run dev`) and open http://localhost:3000/webhooks.
2. Grab a free URL from https://webhook.site, paste it in the Add endpoint form, click Create.
3. Save the `whsec_...` secret from the reveal banner, then click Test to send a `ping` event. The delivery log updates within seconds with status, latency, and HTTP code.
4. Run any classification (drag-drop on `/upload`, or the curl below). A `classify.completed` payload fires automatically.

Verify the signature in your handler:

```
import hmac, hashlib
expected = 'sha256=' + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
assert hmac.compare_digest(expected, request.headers['x-shotclassify-signature'])
```

A quick end-to-end via the keyed API:

```
curl -X POST http://localhost:3000/v1/classify \
  -H "Authorization: Bearer sk_live_YOUR_KEY" \
  -F "file=@screenshot.png"
```

## Try the API keys

1. `cd web && pnpm dev` (or `npm run dev`) and open http://localhost:3000/keys.
2. Generate a key, copy it from the one-time reveal banner.
3. Call the classifier from anywhere:

```
curl -X POST http://localhost:3000/v1/classify \
  -H "Authorization: Bearer sk_live_YOUR_KEY" \
  -F "file=@screenshot.png"
```

The response is the standard `ProcessResult` JSON. Revoke the key from `/keys` and the next call will return `401 invalid_key`.

## Try the share feature

1. `pnpm --filter web dev` (or `cd web && npm run dev`) and open http://localhost:3000.
2. Upload a screenshot at http://localhost:3000/upload, open it from `/shots`, click Copy share link.
3. Paste the link in an incognito window. The public page renders without auth. Paste it in Slack or Twitter to see the dynamic 1200x630 OG card.

The preview image is rendered on demand by `web/app/r/[id]/opengraph-image.tsx` (Next 15 file convention, no extra dependency). It shows the primary label, confidence bar with tier color, top 3 categories, filename, and any user correction. Inspect it directly:

```
curl -I http://localhost:3000/r/<shot-id>/opengraph-image
curl -o card.png http://localhost:3000/r/<shot-id>/opengraph-image
```

Direct curl against the FastAPI service that backs the share page:

```
curl -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  http://127.0.0.1:7441/v1/history/<shot-id>
```
- API key + GitHub OAuth session auth, request-id middleware, OpenTelemetry FastAPI instrumentation.

## Stack

- Backend: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, Tesseract via pytesseract, OpenCV (headless), Pillow, OpenAI-compatible vision client, RQ + Redis, structlog, Typer CLI, OpenTelemetry.
- Web: Next.js 15, React 19, Tailwind v4, Recharts, SWR, Phosphor Icons, fonts Space Grotesk / Inter / JetBrains Mono via `next/font/google`.
- Storage: local filesystem or S3; SQLite by default, Postgres supported via `DATABASE_URL`.
- Infra: Dockerfiles for api/worker/web, Helm chart, Terraform skeleton under `infra/`.

## Architecture

Upload hits the FastAPI route, the image is persisted to `STORAGE_LOCAL_DIR/uploads`, then `shotclassify_common.pipeline.process_image` runs OCR (`packages/ocr`) and the LLM classifier (`packages/classify`) in a worker thread. Output is normalised into a `ProcessResult`, optionally enriched with structured field extraction (`packages/extract`), persisted by `packages/store`, and run through the rules engine (`packages/route`). The Next.js app reads from `/v1/*` via SWR.

```
              +------------+        +-----------------+
upload ---->  |  FastAPI   | -----> | pipeline thread |
              |  /v1/...   |        |  OCR + vision   |
              +-----+------+        +--------+--------+
                    |                        |
                    |  ProcessResult         v
                    |                +---------------+
                    +--------------> |  Repository   | --> SQLite/Postgres
                                     +-------+-------+        + blob storage
                                             |
                       +---------------------+----------------------+
                       |                                            |
                  rules engine                              Next.js web UI
                  (Slack, dry-run)                          (SWR, Recharts)
```

## Try it

With the API and web both running, open <http://127.0.0.1:3000>. The landing page now ships a live one-click sample strip directly under the hero. Pick a receipt, code snippet, stack trace, or chat and the homepage POSTs the real bytes to `/v1/classify` and renders the top-five class probabilities and latency in place, so a first-time visitor sees a real prediction in under a second after the page settles.

For the full inspection view (model rationale, OCR transcript, expected-vs-actual sanity check) open <http://127.0.0.1:3000/demo>. Same four samples, same real OCR plus vision pipeline, more surface area for the result. No upload, no signup.

For your own frames, open <http://127.0.0.1:3000/upload> and drop one or more images. Each file gets its own result card with a thumbnail, the primary call and its confidence, round-trip latency, full per-class confidence bars, the model's rationale, and the OCR transcript. Cards stream in parallel, errors stay scoped to the failing file, and any card opens the full replay at `/shots/{id}`.

Every shot detail page at `/shots/{id}` now ships an Umpire room panel. Pick the true class from a chip grid and hit "Make the call" to persist a human correction through `POST /v1/classify/{id}/correct`, which feeds the calibration dashboard. Or hit "Rerun the pitch" to fire `POST /v1/classify/{id}/reclassify` against the saved frame and see the new primary class without re-uploading. The page revalidates in place, so the chip, confidence, and rationale all update without a reload.

For a live operational view of the classifier, open <http://127.0.0.1:3000/stats>. The page reads `/v1/history/aggregate` and renders the class mix, mean confidence per class, a 24-bin ingest tempo chart, the confidence calibration histogram, and p50/p95/p99 latency, all from real rows in the store. Switch the window between 24h, 7d, and 30d. With an empty database the page shows a clearly labelled seeded preview so the layout is never blank.

One-shot curl against the same endpoint the demo page calls:

```bash
curl -s -X POST http://127.0.0.1:7441/v1/classify \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  -F "file=@samples/fake-receipt.png" | jq '.classification.primary, .classification.confidences[0]'
```

Logging a human correction (the action behind the Umpire room button):

```bash
curl -s -X POST http://127.0.0.1:7441/v1/classify/$SHOT_ID/correct \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" \
  -F category=chart | jq
```

And the analytics rollup that powers `/stats`:

```bash
curl -s "http://127.0.0.1:7441/v1/history/aggregate?hours=24" \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY" | jq '.total, .latency_ms, .per_class[0]'
```

Download the full classification history as CSV (or JSON) from the shots page Export menu, or directly:

```bash
curl -s -OJ "http://127.0.0.1:7441/v1/history/export?format=csv&limit=1000" \
  -H "x-api-key: $SHOTCLASSIFY_API_KEY"
# add &category=signup or &q=stripe to narrow it down
```

## Quick start

Requires Python 3.11+, Node 20+, Tesseract, and Redis (optional, only for `/v1/queue`).

```bash
# Backend
cp .env.example .env
uv sync                                   # or: pip install -e . -e packages/*
uv run uvicorn services.api.app.main:app --reload --port 7441

# Worker (optional, for /v1/queue)
uv run python -m services.worker.app.main

# Web
cd web && npm install && npm run dev      # http://localhost:3000

# CLI
uv run shotclassify --help
```

API on `:7441`, web on `:3000`. The web UI talks to the API through Next.js route handlers under `web/app/api`. Point `LLM_BASE_URL` at any OpenAI-compatible endpoint (local Copilot proxy on `:4141` by default).

## Configuration

From `.env.example`:

| Var | Default | Notes |
| --- | --- | --- |
| `APP_ENV` | `development` | |
| `APP_HOST` / `APP_PORT` | `0.0.0.0` / `7441` | uvicorn bind |
| `APP_SECRET_KEY` | `change-me-...` | session signing, 32+ bytes |
| `APP_LOG_LEVEL` / `APP_LOG_FORMAT` | `INFO` / `json` | structlog |
| `STORAGE_BACKEND` | `local` | `local` or `s3` |
| `STORAGE_LOCAL_DIR` | `./storage` | mounted at `/blob` |
| `STORAGE_S3_BUCKET` / `STORAGE_S3_REGION` | `` / `us-west-2` | |
| `DATABASE_URL` | `sqlite:///./shotclassify.db` | Postgres supported |
| `REDIS_URL` / `QUEUE_NAME` | `redis://localhost:6379/0` / `shotclassify` | RQ |
| `LLM_BASE_URL` | `http://127.0.0.1:4141/v1` | OpenAI-compatible |
| `LLM_API_KEY` | `copilot` | |
| `LLM_MODEL` | `gpt-4o-mini` | vision-capable |
| `LLM_TIMEOUT_S` / `LLM_MAX_RETRIES` | `60` / `2` | |
| `OCR_LANG` | `eng` | tesseract lang code |
| `OCR_PSM` | `6` | tesseract page seg mode |
| `OCR_DESKEW` | `true` | OpenCV deskew pass |
| `AUTH_ENABLED` | `true` | |
| `AUTH_OAUTH_PROVIDER` | `github` | |
| `AUTH_OAUTH_CLIENT_ID` / `AUTH_OAUTH_CLIENT_SECRET` | | |
| `AUTH_ALLOWED_GITHUB_LOGIN` | `Sanjays2402` | single-user allowlist |
| `AUTH_API_KEY` | | bearer for programmatic access |
| `ROUTE_RULES_PATH` | `./packages/route/rules.example.yaml` | |
| `ROUTE_DRY_RUN` | `true` | |
| `ROUTE_SLACK_WEBHOOK` | | |
| `OTEL_ENABLED` | `false` | |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | |
| `OTEL_SERVICE_NAME` | `shotclassify-api` | |

## Scripts

Python (`scripts/`):

- `scripts/make_samples.py` generate sample screenshots into `samples/`.
- `scripts/make_corpus.py` generate the synthetic eval corpus under `fixtures/synth/`.
- `scripts/bench.py` run the corpus through the pipeline and write `fixtures/bench/report.{json,csv}`.
- `scripts/dev.sh`, `scripts/dogfood.sh` local helpers.

Make targets: `install`, `dev`, `test`, `fmt`, `lint`, `samples`, `api`, `worker`, `web`, `docker`, `compose-up`, `clean`.

CLI (`shotclassify` entrypoint, Typer): `classify`, `history`, `show`, `correct`, `serve`.

Web (`web/package.json`): `dev`, `build`, `start`, `lint`.

## API

Base: `http://localhost:7441`.

Health:

- `GET /` `GET /healthz` `GET /readyz`

Auth (`/auth`):

- `GET /auth/login`
- `GET /auth/callback`
- `POST /auth/logout`
- `GET /auth/whoami`

Classify (`/v1`):

- `POST /v1/classify` multipart `file`, optional `note`.
- `POST /v1/classify/batch` multipart `files[]`.
- `POST /v1/classify/{item_id}/reclassify`
- `POST /v1/classify/{item_id}/correct` form `category`.
- `POST /v1/queue` background classification via RQ.

History (`/v1/history`):

- `GET /v1/history?limit=&category=&q=`
- `GET /v1/history/stats`
- `GET /v1/history/{item_id}`
- `DELETE /v1/history/{item_id}`

Settings (`/v1/settings`):

- `GET /v1/settings/rules`
- `PUT /v1/settings/rules`
- `GET /v1/settings/env`

Data lifecycle (`/v1/me`):

- `GET /v1/me/data` export everything tied to the authenticated principal.
- `DELETE /v1/me/data?confirm=erase` permanently erase it.

Static blobs are served from `/blob/*`.

## Categories

Defined in `packages/common/src/shotclassify_common/schemas.py::Category`:

`receipt`, `code_snippet`, `error_stacktrace`, `chat_screenshot`, `meme`, `document`, `ui_mockup`, `chart`, `other`.

## Calibration

The web `/calibration` page renders a reliability diagram against three metrics:

- **ECE** Expected Calibration Error, weighted gap between confidence and accuracy across bins.
- **Brier** mean squared error between predicted probability and the one-hot outcome.
- **Log loss** cross-entropy over the holdout set.

Generate inputs with `python scripts/make_corpus.py` then `python scripts/bench.py`; the report under `fixtures/bench/` feeds offline calibration analysis. Helpers live in `packages/classify/src/shotclassify_classify/calibration.py`.

## Project structure

```
.
├── cli/                  Typer CLI (shotclassify)
├── packages/
│   ├── common/           Pydantic schemas, settings, pipeline
│   ├── ocr/              Tesseract + OpenCV preprocessing
│   ├── classify/         vision LLM prompts + calibration
│   ├── extract/          structured field extraction
│   ├── route/            rules engine, Slack sink
│   └── store/            SQLAlchemy repository, migrations
├── services/
│   ├── api/              FastAPI app (routes, middleware, models)
│   └── worker/           RQ worker
├── web/                  Next.js 15 app (app router)
├── scripts/              corpus, samples, bench
├── infra/                docker, helm, terraform
├── macos/                Shortcut installer
├── fixtures/             synth corpus + bench reports
├── samples/              generated sample screenshots
├── docs/                 schemas + screenshots
└── tests/                pytest suite
```

## Operations

### Production configuration validation

The API and worker run `shotclassify_common.validate_for_production` from
their startup lifespan. When `APP_ENV` is `staging` or `production` the
process refuses to come up if any of the following are still at their dev
default or otherwise unsafe:

- `APP_SECRET_KEY` is the placeholder, empty, or shorter than 32 bytes
- `AUTH_ENABLED` is false
- `AUTH_API_KEY` is the well-known `dev-api-key-change-me` placeholder
- `CORS_ALLOWED_ORIGINS` is empty or contains `*`
- `DATABASE_URL` points at SQLite
- `STORAGE_BACKEND=local` (ephemeral inside a pod) or `s3` with no bucket
- `LLM_API_KEY` is empty or the dev `copilot` placeholder

All failures are reported in a single `InsecureConfigurationError` so an
operator can fix the deploy in one pass instead of crash-looping per
setting. `APP_ENV=development` is exempt so local iteration keeps working.
Verify a candidate environment file before rollout:

```sh
APP_ENV=production env $(grep -v '^#' .env.production | xargs) \
  python -c "from shotclassify_common import validate_for_production; validate_for_production(); print('ok')"
```

The matching test suite lives in `tests/test_secrets_validation.py`.

### Container images

All three services ship as multi-stage Docker images under `infra/docker/`:

| Image     | Dockerfile                  | Base                       | Final user      |
| --------- | --------------------------- | -------------------------- | --------------- |
| API       | `infra/docker/Dockerfile`        | `python:3.11-slim`         | `app` (uid 10001) |
| Worker    | `infra/docker/Dockerfile.worker` | `python:3.11-slim`         | `app` (uid 10001) |
| Web       | `infra/docker/Dockerfile.web`    | `node:20-bookworm-slim`    | `app` (uid 10001) |

Every Dockerfile is multi-stage. The builder stage installs the full compile
toolchain (`build-essential`, `libpq-dev`, `libffi-dev`, `libssl-dev`,
`libtesseract-dev`, etc.) and resolves the Python or Node dependency closure.
The runtime stage starts from a clean slim base, copies only the installed
site-packages or production `node_modules`, ships only the runtime OS
libraries (`tesseract-ocr`, `libgl1`, `libglib2.0-0`, `libpq5`, `tini`,
`ca-certificates`), creates an unprivileged `app` user (uid/gid 10001), and
runs the process under `tini` so SIGTERM is forwarded cleanly to uvicorn /
the RQ worker / `next start`.

The API and web images declare a `HEALTHCHECK` against `/healthz` and `/` so
`docker ps`, swarm, and ECS see container-level liveness without depending
on Kubernetes probes.

Build context is pruned by `.dockerignore` at the repo root, which excludes
`.git`, `.venv`, `node_modules`, `web/.next`, local SQLite databases, the
`storage/` and `samples/` directories, the Helm and Terraform trees, and any
`.env*` file other than `.env.example`. This keeps image layers free of
local state and prevents accidentally baking secrets into a pushed tag.

Build and push from the repo root:

```sh
docker build -f infra/docker/Dockerfile        -t ghcr.io/sanjays2402/shotclassify-api:$(git rev-parse --short HEAD)    .
docker build -f infra/docker/Dockerfile.worker -t ghcr.io/sanjays2402/shotclassify-worker:$(git rev-parse --short HEAD) .
docker build -f infra/docker/Dockerfile.web    -t ghcr.io/sanjays2402/shotclassify-web:$(git rev-parse --short HEAD)    .
```

The Helm `api` Deployment now sets a pod-level `securityContext`
(`runAsNonRoot: true`, uid/gid 10001, `seccompProfile: RuntimeDefault`) and a
container-level `securityContext` that drops all Linux capabilities and
blocks privilege escalation, matching the non-root user baked into the image.

`tests/test_dockerfiles.py` enforces these properties statically (multi-stage,
non-root final `USER`, healthcheck present, no build toolchain leaked into
the runtime stage, `tini` entrypoint, `.dockerignore` excludes secrets) so a
future refactor that regresses them fails CI without needing a Docker daemon.

### Roles and access control

The API enforces a three-tier role model on every authenticated route:

| Role     | Read history | Classify / reclassify | Delete history | Read settings | Write settings | Read audit log |
| -------- | :----------: | :-------------------: | :------------: | :-----------: | :------------: | :------------: |
| viewer   | yes          | no                    | no             | no            | no             | no             |
| operator | yes          | yes                   | yes            | yes           | no             | no             |
| admin    | yes          | yes                   | yes            | yes           | yes            | yes            |

Role assignment lives in environment variables (see `.env.example`):

* `AUTH_API_KEY` is the legacy single key and is always treated as `admin`.
* `AUTH_API_KEYS` is a JSON object `{key: role}` for provisioning additional
  keys with non-admin roles, for example
  `'{"ops-rotating-token": "operator", "dashboard-readonly": "viewer"}'`.
* `AUTH_ROLE_MAP` is a JSON object `{login: role}` mapping authenticated
  GitHub logins to roles.
* Any authenticated principal not matched falls through to
  `AUTH_DEFAULT_ROLE` (default `viewer`).
* Malformed JSON in `AUTH_API_KEYS` or `AUTH_ROLE_MAP` is ignored rather than
  failing startup, so a bad rotation never locks the cluster out.

Unauthenticated requests still return `401`. Authenticated requests that lack
the required role return `403` with a body like
`{"detail": "Role 'viewer' lacks required role 'admin'."}`. The data lifecycle
endpoints under `/v1/me/data` are deliberately open to every authenticated
role because they self-scope to the caller's own rows.

In the Helm chart, set `secret.apiKeys` and `secret.roleMap` (JSON strings)
alongside the existing `secret.apiKey`; the chart wires them through to the
API Deployment as `AUTH_API_KEYS` and `AUTH_ROLE_MAP` secret env vars only
when non-empty.

### Multi-tenancy

Every persisted row (classifications, audit_log, api_keys) carries a
`tenant_id` column and every repository query is scoped to the caller's
tenant. One tenant cannot read, list, mutate, or delete another tenant's
data through the public API, even when they share an endpoint, principal
name, or role.

Tenant resolution runs as `TenantResolutionMiddleware` (in
`services/api/app/middleware/tenant.py`) right after authentication. It
sets `request.state.tenant_id` from this lookup order:

1. `X-Tenant` request header, when the caller's role is `admin`. Admins may
   pass `*` to opt into a cross-tenant view (the repository skips the
   tenant filter entirely) or any specific tenant id to operate inside
   that tenant. Non-admin callers cannot escape their tenant; the header
   is ignored for them.
2. `AUTH_TENANT_MAP`, a JSON object `{principal: tenant_id}` that maps
   API keys and OAuth logins to a tenant. Example:

   ```
   AUTH_TENANT_MAP='{"acme-ops-key":"acme","globex-view-key":"globex","sanjay":"acme"}'
   ```

3. `AUTH_DEFAULT_TENANT` (defaults to `default`), used for any principal
   not present in the map. This keeps single-tenant deployments working
   without any new configuration.

Writes tag rows with the resolved tenant id at insert time. The classify,
batch, reclassify, correct, history, audit, and `/v1/me/data` routes all
thread `request.state.tenant_id` into the repository call so the scoping
is enforced at the SQL layer rather than relying on application-side
filtering.

Rows written before the multi-tenancy migration have `tenant_id IS NULL`.
The repository treats them as belonging to whatever tenant the caller is
scoped to, so the migration is non-destructive for existing solo
deployments; backfill them with an `UPDATE ... SET tenant_id = 'default'`
when you are ready to enforce strict isolation.

Apply the schema change with the bundled Alembic migration:

```sh
cd packages/store && alembic upgrade head
```

The migration (`0004_tenant_id`) adds a nullable `tenant_id String(64)`
column plus an index on each of `classifications`, `api_keys`, and
`audit_log`. It is reversible.

Coverage lives in `tests/test_multitenant.py`: tenant isolation on
history listing, cross-tenant GET returning 404, cross-tenant DELETE
blocked, tenant-scoped stats, admin cross-tenant header behavior, and a
GDPR export that only returns the caller's tenant rows even when the
principal name collides across tenants.

### Data lifecycle (GDPR)

The API exposes a per-principal export and erasure endpoint under `/v1/me/data`.
Scope is the request principal as set by `APIKeyAndSessionAuth`: the GitHub
login for session users, or the literal string `api-key` for API key callers.

Export bundles the caller's identity, every `classifications` row tagged with
that principal (full extracted/route JSON plus OCR text), and every `audit_log`
row recorded against the principal:

```bash
curl -H "X-API-Key: $AUTH_API_KEY" https://host/v1/me/data | jq
```

Response shape:

```json
{
  "principal": "api-key",
  "exported_at": "2026-05-30T18:00:00+00:00",
  "request_id": "...",
  "counts": { "classifications": 12, "audit_log": 47 },
  "classifications": [ /* full ClassificationRecord objects */ ],
  "audit_log": [ /* full audit rows */ ]
}
```

Erasure is hard-delete and irreversible. It removes every matching
`classifications` row, unlinks any blobs that live under `STORAGE_LOCAL_DIR`,
and removes every `audit_log` row owned by the principal. A `confirm=erase`
query parameter is required so accidental DELETEs return `400` instead of
wiping data:

```bash
curl -X DELETE -H "X-API-Key: $AUTH_API_KEY" \
  "https://host/v1/me/data?confirm=erase"
```

Classifications are tagged with their owning principal at write time via the
`principal` column on the `classifications` table (Alembic migration
`0003_classification_principal`). Rows written before the migration have
`principal = NULL` and are therefore not returned by export and not removed by
erasure; operators handling pre-migration data should backfill the column from
the corresponding audit rows before relying on `/v1/me/data` for compliance
reports.

The DELETE call itself is audited by `AuditLogMiddleware` after the response
is sent, so the erasure action remains forensically visible without retaining
any user payload.

### Audit log

Every authenticated, state-changing request (POST, PUT, PATCH, DELETE) is
persisted to the `audit_log` table by `AuditLogMiddleware`. Each row captures:

- `principal` (GitHub login or `api-key`), `method`, `path`, `status_code`
- `request_id` (matches the `x-request-id` response header and structured logs)
- `client_ip` (honours `X-Forwarded-For` when present), `user_agent`
- `elapsed_ms`, `target_id` (best-effort `/v1/<resource>/<id>` extraction)
- `created_at` (UTC), plus a free-form `extra` JSON column for future fields

Read-only requests, health probes, OAuth callbacks, and static `/blob/*` fetches
are deliberately skipped to keep the table focused on actions worth reviewing.
Audit writes are wrapped in a `try/except` so a logging failure can never break
the user request, but failures are emitted as `audit_log_write_failed` warnings.

Query the trail:

```bash
curl -H "X-API-Key: $AUTH_API_KEY" https://host/v1/audit?limit=50
curl -H "X-API-Key: $AUTH_API_KEY" "https://host/v1/audit?principal=api-key"
curl -H "X-API-Key: $AUTH_API_KEY" "https://host/v1/audit?path_prefix=/v1/history"
curl -H "X-API-Key: $AUTH_API_KEY" https://host/v1/audit/stats
```

The table is created automatically via `init_db()` on boot and is also covered
by Alembic migration `0002_audit_log` for Postgres deployments where you want
to manage schema changes explicitly.

### Rate limiting

`RateLimitMiddleware` enforces a token bucket per client. Requests carrying
`X-API-Key` are scoped by key, the rest by client IP (honouring
`X-Forwarded-For` when present, so put a trusted proxy in front in production).
The bucket runs in-process per pod, so the effective cluster-wide ceiling is
`replicaCount.api * RATE_LIMIT_*_RPM` in the worst case. For a hard global
limit, terminate at an ingress that does its own rate limiting and treat these
values as a safety net.

Defaults (override via env or Helm `rateLimit.*` / `env.RATE_LIMIT_*`):

| Setting | Default | Meaning |
| --- | --- | --- |
| `RATE_LIMIT_ENABLED` | `true` | Master switch. |
| `RATE_LIMIT_PER_IP_RPM` | `120` | Sustained requests per minute per source IP. |
| `RATE_LIMIT_PER_KEY_RPM` | `600` | Sustained rpm per `X-API-Key`. Overridable per key (see below). |
| `RATE_LIMIT_PER_WORKSPACE_RPM` | `2400` | Aggregate sustained rpm across all keys in a workspace. |
| `RATE_LIMIT_BURST` | `20` | Extra tokens above the sustained rate for short bursts. |
| `RATE_LIMIT_EXEMPT_PATHS` | `/healthz,/readyz,/metrics,/blob` | Comma-separated path prefixes the limiter ignores. |

Every response, success or rejection, carries the standard rate-limit
headers so well-behaved clients can back off proactively:
`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` (seconds
until the next token), and `X-RateLimit-Scope: ip|api_key|workspace`. When
a bucket is empty the API responds with HTTP 429, a JSON body of
`{"error":"rate_limited"}`, and a `Retry-After` header. Rejections
increment `shotclassify_rate_limit_rejections_total{scope}` so you can
alert on sustained throttling and distinguish abusive IPs from a noisy API
key from a workspace nearing its plan ceiling.

Workspace admins can lift or tighten the sustained rpm for an individual
API key without rolling the global default, which is the common ask when
onboarding a high-throughput enterprise integration:

```bash
# Grant key kr_abc... a 5000 rpm ceiling. MFA step-up required.
curl -X PATCH http://localhost:8000/v1/api-keys/kr_abc.../rate-limit \
  -H "X-API-Key: $ADMIN_KEY" -H "X-MFA-Token: $MFA" \
  -H "content-type: application/json" \
  -d '{"rpm": 5000}'

# Clear the override and fall back to RATE_LIMIT_PER_KEY_RPM.
curl -X PATCH http://localhost:8000/v1/api-keys/kr_abc.../rate-limit \
  -H "X-API-Key: $ADMIN_KEY" -H "X-MFA-Token: $MFA" \
  -H "content-type: application/json" \
  -d '{"rpm": null}'
```

The endpoint is RBAC-gated to workspace admins, scoped to the caller's
tenant (cross-tenant id probes return 404), supports `?dry_run=true`, and
lands in the audit log. The override lives on `api_keys.rpm_override`
(nullable integer, added by migration `0015_api_key_rpm_override`).

### CORS and security headers

The API ships a hardened CORS allowlist and a baseline set of HTTP security
response headers, both driven by `Settings` so operators can tune them
without code changes.

CORS is configured via four env vars:

| Variable                  | Default                                                              | Notes                                                                |
| ------------------------- | -------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `CORS_ALLOWED_ORIGINS`    | `*`                                                                  | Comma-separated origin list. Wildcard is only honored in `development`. |
| `CORS_ALLOW_CREDENTIALS`  | `false`                                                              | When `true`, cookies and `Authorization` may cross origins. Ignored when origins contain `*`. |
| `CORS_ALLOWED_METHODS`    | `GET,POST,PUT,PATCH,DELETE,OPTIONS`                                  | Methods echoed in the preflight response.                            |
| `CORS_ALLOWED_HEADERS`    | `Authorization,Content-Type,X-API-Key,X-Request-ID,X-Tenant`         | Request headers allowed on cross-origin calls.                       |

When `APP_ENV` is `staging` or `production`, any `*` entry in
`CORS_ALLOWED_ORIGINS` is silently dropped. If the resulting allowlist is
empty the API fails closed and no cross-origin browser traffic is accepted,
so you must set an explicit list before deploying. `X-Request-ID` is exposed
to browsers so client-side observability can correlate failures with server
logs and traces.

`SecurityHeadersMiddleware` is registered as the outermost middleware so
every response, including 401s from auth and 429s from rate limiting,
carries the baseline header set:

| Header                          | Default value                                                                                                              |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `Content-Security-Policy`       | `default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'` |
| `X-Content-Type-Options`        | `nosniff`                                                                                                                  |
| `X-Frame-Options`               | `DENY`                                                                                                                     |
| `Referrer-Policy`               | `strict-origin-when-cross-origin`                                                                                          |
| `Permissions-Policy`            | `accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()`            |
| `Cross-Origin-Opener-Policy`    | `same-origin`                                                                                                              |
| `Cross-Origin-Resource-Policy`  | `same-origin`                                                                                                              |
| `Strict-Transport-Security`     | `max-age=31536000; includeSubDomains` (production only)                                                                    |

HSTS is only emitted when `APP_ENV=production` so dev and staging clusters
running on plain HTTP do not pin browsers onto HTTPS-only behavior. Each
header is set with `setdefault`, so a downstream route or middleware that
needs to override one (for example a relaxed CSP on an embeddable widget)
can still do so. Set `SECURITY_HEADERS_ENABLED=false` to disable the
middleware entirely; tune `SECURITY_CSP`, `SECURITY_HSTS_MAX_AGE`,
`SECURITY_REFERRER_POLICY`, or `SECURITY_PERMISSIONS_POLICY` to override
individual values.

Regression coverage lives in `tests/test_security_headers.py`, which
asserts the baseline headers on `/healthz`, verifies they still ride on 401
responses, exercises the production-only HSTS gate, and confirms the
staging/production CORS allowlist rejects wildcards and unknown origins.

### Metrics

The API exposes Prometheus metrics on `GET /metrics` (public, unauthenticated,
intended for in-cluster scraping). `PrometheusMiddleware` wraps every request
outermost so it observes auth failures and exceptions in addition to handler
latency. The exported series are:

- `shotclassify_http_requests_total{method,route,status}` counter
- `shotclassify_http_request_duration_seconds{method,route}` histogram
  (buckets: 5ms to 10s)
- `shotclassify_http_requests_in_flight{method}` gauge
- `shotclassify_http_exceptions_total{method,route,exception}` counter

The `route` label uses the FastAPI path template (for example `/v1/items/{id}`)
rather than the raw URL, so cardinality stays bounded regardless of client
input. Scrapes of `/metrics` itself are intentionally excluded from these
counters to avoid self-amplification.

The Helm chart adds `prometheus.io/scrape` annotations to the API Service and
Pod template for annotation-based scrapers, and includes an optional
`ServiceMonitor` for the Prometheus Operator. Enable it with:

```yaml
metrics:
  serviceMonitor:
    enabled: true
    interval: 30s
    labels:
      release: kube-prometheus-stack
```

For multi-worker uvicorn/gunicorn deployments, set `PROMETHEUS_MULTIPROC_DIR`
to a writable directory and the endpoint will aggregate across workers via
`prometheus_client.multiprocess`.

### Access logs and trace correlation

Every HTTP request flows through `RequestIdMiddleware`, which:

- Honours an inbound `x-request-id` header or mints a fresh hex uuid, then
  echoes it back as `x-request-id` so clients can quote it in bug reports.
- Binds `request_id`, `path`, and `method` into the structlog contextvars so
  every downstream log line (auth, audit, application, errors) carries the
  same correlation id without any extra plumbing.
- When OpenTelemetry is enabled (`OTEL_ENABLED=true`) and a span is
  recording for the request, also binds `trace_id` and `span_id` into the
  log context and echoes `x-trace-id` on the response. This makes it a
  single click in Grafana, Tempo, Jaeger, Honeycomb, or Sentry to jump
  from a log line to the matching trace and back.
- Emits exactly one `http.access` structured log per request after the
  response is produced, including `status`, `latency_ms`, `principal`
  (authenticated subject when present), and `client` (peer IP). The log
  fires even when the handler raises, so 5xx storms are visible without
  scraping uvicorn's stdout.

Example line in `APP_LOG_FORMAT=json` mode:

```json
{"event": "http.access", "level": "info", "request_id": "7296f9b4...",
 "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "span_id": "00f067aa0ba902b7",
 "path": "/v1/classify", "method": "POST", "status": 200,
 "latency_ms": 412.7, "principal": "apikey:operator", "client": "10.0.3.4"}
```

For on-call: when a user reports a slow or failed request, ask for the
`x-request-id` (and `x-trace-id` if present) from their response headers,
then grep logs by `request_id=` to pull the full per-request slice across
the API, the audit middleware, and any RQ jobs that re-bind the same id.

`tests/test_request_id.py` guards id propagation, the access log shape,
and OTEL trace header emission.

### Deploy

Production deployments use the Helm chart in `infra/helm/shotclassify`. The
chart ships a multi-stage Dockerfile (`infra/docker/Dockerfile`), HPA, network
policy, and configurable resource limits. CI runs lint + tests + build on every
push via `.github/workflows/ci.yml`, plus a dedicated `helm` job that runs
`helm lint` and renders the chart with default and feature-flag value sets so
templating regressions fail before merge.

### Availability and pod security

Every workload in the chart (`api`, `worker`, `web`) is hardened to the same
baseline:

- Pod `securityContext`: `runAsNonRoot: true`, uid/gid 10001, `fsGroup` 10001,
  `seccompProfile.type: RuntimeDefault`.
- Container `securityContext`: `allowPrivilegeEscalation: false`,
  `capabilities.drop: ["ALL"]`.
- CPU and memory `requests` and `limits` set in `values.yaml`
  (`resources.api|worker|web`).
- Liveness probe on every container. The API and web pods use HTTP probes
  (`/healthz`, `/`); the RQ worker pod uses an `exec` probe that pings Redis
  via `python -c "import os,redis;redis.Redis.from_url(os.environ['REDIS_URL']).ping()"`,
  which fails fast if the broker connection is lost (RQ workers do not expose
  HTTP).
- PodDisruptionBudgets in `infra/helm/shotclassify/templates/pdb.yaml` keep at
  least one `api` and one `worker` pod available during voluntary disruptions
  (node drains, cluster upgrades, autoscaler evictions). Tune or disable per
  workload via `pdb.<api|worker|web>.{enabled,minAvailable}` in `values.yaml`.
  The `web` PDB is opt-in because most installs run a single replica.

`tests/test_helm_chart.py` enforces these properties by running `helm lint`
and `helm template`, then asserting that every rendered `Deployment` runs
non-root with `ALL` capabilities dropped, declares resource requests and
limits, has a `livenessProbe`, and that the default render contains the
expected PodDisruptionBudgets. The suite skips cleanly if `helm` is not on
PATH, and the CI `helm` job installs Helm v3 so the same checks run on
every push.

### Health and readiness

Two probes with deliberately different contracts so Kubernetes does the right
thing under partial outages.

- `GET /healthz` is liveness. It returns `200 {"status":"ok"}` as long as the
  process can serve HTTP. It does not touch the database, Redis, or storage,
  so a backing service blip will not cause the kubelet to restart the pod.
- `GET /readyz` is a deep readiness probe. It actively checks each hard
  dependency and returns **HTTP 503** with a per-check breakdown when any of
  them is degraded, so the pod is pulled out of the Service endpoints until
  it recovers. Checks:
  - `db` runs `SELECT 1` against the configured `DATABASE_URL`.
  - `storage` verifies `STORAGE_LOCAL_DIR` exists and is writable.
  - `redis` pings `REDIS_URL` with a 2 second timeout. Required outside
    `APP_ENV=development` so a missing queue fails the probe in staging and
    production; treated as advisory in dev so a local laptop without Redis
    still serves traffic.

Example healthy response:

```json
{
  "status": "ready",
  "checks": {
    "db": {"status": "ok"},
    "storage": {"status": "ok"},
    "redis": {"status": "ok"}
  }
}
```

Example degraded response (HTTP 503), exactly what an operator wants to see in
a probe-failure event:

```json
{
  "status": "degraded",
  "checks": {
    "db": {"status": "error", "detail": "OperationalError: connection refused"},
    "storage": {"status": "ok"},
    "redis": {"status": "ok"}
  }
}
```

The Helm chart already wires `/healthz` to `livenessProbe` and `/readyz` to
`readinessProbe` on the API deployment, so no extra configuration is needed.

### Backup

The SQLite default is fine for single-node and dev, but production should run
Postgres via `DATABASE_URL`. Back up both the database (classifications and
audit log) and the object/blob store (`STORAGE_LOCAL_DIR` or the configured S3
bucket). The audit log is append-only in practice and is your forensic record
of who did what, so prioritise its restore path.

### On-call

- Structured JSON logs include `request_id`, `path`, and `method`. Search for a
  request by `request_id` to correlate the full request lifecycle across the
  API, worker, and audit log.
- Watch `shotclassify_http_request_duration_seconds` p95/p99 per route and
  `shotclassify_http_requests_total{status=~"5.."}` for error budget burn.
  Suggested first alerts: 5xx rate > 1% over 5 min, and p95 latency on
  `/v1/classify` over 5 seconds.
- If `audit_log_write_failed` warnings appear, the request itself still
  succeeded; investigate DB connectivity to the audit table.
- Spike in `/v1/audit` rows from an unexpected `principal` is a credential
  abuse signal. Rotate `AUTH_API_KEY` and revoke OAuth sessions if needed.
- Sustained `shotclassify_rate_limit_rejections_total{scope="api_key"}` means a
  legitimate caller is hitting their per-key ceiling. Either raise
  `RATE_LIMIT_PER_KEY_RPM` or issue a separate key. Rejections with
  `scope="ip"` from a single address that has no key are usually scanners,
  block at the ingress.

### Alerting (PrometheusRule)

The Helm chart ships a `PrometheusRule` covering availability, error rate,
latency, and saturation. It is opt-in so installs without the Prometheus
Operator do not fail to render. Enable it by setting
`metrics.prometheusRule.enabled=true` and labelling it so your Prometheus
instance picks it up:

```yaml
metrics:
  prometheusRule:
    enabled: true
    labels:
      release: kube-prometheus-stack   # matches Prometheus ruleSelector
    downFor: 2m
    errorRateThreshold: 0.05           # 5% 5xx over 10m -> warning
    exceptionRatePerSec: 0.1           # unhandled exceptions per second
    latencyP95Seconds: 2.5             # route p95 over 15m -> warning
    inFlightThreshold: 50              # sustained queue depth
```

Alerts fired by the rule, each carrying a `runbook_url` that points back at
this section:

- `ShotclassifyApiDown` (critical): no successful scrape for `downFor`.
- `ShotclassifyApiHighErrorRate` (warning): 5xx ratio over threshold for 10m.
- `ShotclassifyApiHighExceptionRate` (warning): unhandled exceptions/s over
  threshold for 10m. Cross-check Sentry for stack traces.
- `ShotclassifyApiHighLatencyP95` (warning): per-route p95 above threshold
  for 15m. Check upstream LLM, OCR, DB, and CPU saturation.
- `ShotclassifyApiInFlightSaturation` (warning): in-flight requests above
  threshold for 10m. Scale `replicaCount.api` or investigate slow
  downstreams.

Rule structure is pinned by `tests/test_helm_prometheus_rule.py`, which
renders the chart with the rule on and asserts the alert set, severities,
runbook links, and that the expressions still reference the metric names
emitted by `services/api/app/middleware/metrics.py`. A metric rename will
fail the test before it silently breaks paging.

### Error tracking (Sentry)

The API and worker initialize the Sentry SDK in their startup hooks via
`shotclassify_common.init_sentry`. Initialization is a no-op unless
`SENTRY_DSN` is set, so local development and CI never emit events.

Relevant environment variables (see `.env.example`):

```
SENTRY_DSN=                       # leave empty to disable
SENTRY_RELEASE=                   # e.g. git sha; tags events with a release
SENTRY_SAMPLE_RATE=1.0            # error sampling, 0.0 to 1.0
SENTRY_TRACES_SAMPLE_RATE=0.0     # performance traces, 0.0 to 1.0
SENTRY_PROFILES_SAMPLE_RATE=0.0   # profiles, 0.0 to 1.0
```

The wiring is opinionated for safety:

- `send_default_pii=False` so user identifiers are not auto-attached.
- A `before_send` scrubber strips `Authorization`, `Cookie`, `X-API-Key`,
  and `X-Auth-Token` request headers, clears request cookies, replaces the
  raw `QUERY_STRING` env entry, and filters any `extra` field whose name
  contains `key`, `secret`, or `token`.
- Starlette, FastAPI, and standard-library logging integrations are enabled.
  Log records at `ERROR` and above are forwarded as events; everything from
  `INFO` and above becomes a breadcrumb.

In Kubernetes, enable Sentry by setting both flags in `values.yaml`:

```yaml
sentry:
  enabled: true
  release: "v0.1.0"
secret:
  sentryDsn: "https://<public>@<host>/<project>"
```

The Helm chart injects `SENTRY_DSN` from the chart's existing Opaque secret
(`<release>-shotclassify-secret`, key `sentry-dsn`); the other Sentry knobs
ride along as plain env on the API deployment.

For ad hoc capture inside application code use
`shotclassify_common.capture_exception(exc)`, which returns the Sentry event
id when initialized and `None` otherwise; it never raises.

## Per-tenant upload size cap

Workspace admins can cap the byte size of any single image accepted by the classify routes (`POST /v1/classify`, `POST /v1/classify/batch`, `POST /v1/queue`). Oversized uploads are refused with HTTP 413 `upload_too_large` before the payload is buffered to disk or sent to the model, so a single tenant cannot exhaust shared worker memory or drive up inference cost.

Try it:

- UI: `http://localhost:3000/settings/security` then the "Upload size cap" section (admin role, MFA step-up required to save).
- API:

```bash
# read the current policy (null = no cap, falls back to the deployment global)
curl -s http://localhost:7441/v1/settings/security/upload-size \
  -H "X-API-Key: $SHOTCLASSIFY_API_KEY"

# enforce a 10 MiB per-upload cap for this workspace
curl -s -X PUT http://localhost:7441/v1/settings/security/upload-size \
  -H "X-API-Key: $SHOTCLASSIFY_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"max_upload_bytes": 10485760}'

# clear the policy
curl -s -X PUT http://localhost:7441/v1/settings/security/upload-size \
  -H "X-API-Key: $SHOTCLASSIFY_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"max_upload_bytes": null}'
```

The policy is strictly tenant-scoped: tenant A's cap cannot be read or enforced against tenant B (covered by `tests/test_upload_size_policy.py`).

## License

MIT. See `LICENSE`.

