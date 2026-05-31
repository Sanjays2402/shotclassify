// GET  /v1/webhooks       — list webhook subscriptions for the API key holder
// POST /v1/webhooks       — register a new subscription (returns the signing
//                           secret exactly once, like /v1/keys)
//
// Authenticated with the same `Authorization: Bearer sk_...` or `x-api-key`
// header the rest of /v1 uses. Listing requires the `read` scope; create
// requires the `admin` scope. Webhooks deliver workspace data to external
// systems, so registering one is treated as an administrative integration
// change rather than a routine write.
import { NextRequest, NextResponse } from "next/server";
import { authenticate, v1Error } from "@/lib/v1auth";
import {
  createWebhook,
  listWebhooks,
  type Webhook,
} from "@/lib/webhooks";
import { workspaceOf } from "@/lib/keystore";
import { withObservability } from "@/lib/observability";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Hide the signing secret on list responses. The secret is only returned at
// creation time, matching the API-key UX.
function publicView(hook: Webhook) {
  const { secret, ...rest } = hook;
  return { ...rest, secret_prefix: secret.slice(0, 12) };
}

async function getHandler(req: NextRequest): Promise<Response> {
  const auth = await authenticate(req, "read");
  if (auth instanceof NextResponse) return auth;

  const hooks = await listWebhooks(workspaceOf(auth.key));
  return NextResponse.json({ webhooks: hooks.map(publicView) });
}

async function postHandler(req: NextRequest): Promise<Response> {
  const auth = await authenticate(req, "admin");
  if (auth instanceof NextResponse) return auth;

  let body: any = null;
  try {
    body = await req.json();
  } catch {
    return v1Error(400, "invalid_json", "Request body must be valid JSON.");
  }
  if (!body || typeof body !== "object") {
    return v1Error(400, "invalid_input", "Request body must be a JSON object.");
  }

  const url = typeof body.url === "string" ? body.url.trim() : "";
  if (!url) {
    return v1Error(400, "missing_url", "Field 'url' is required.");
  }
  if (!/^https?:\/\//i.test(url)) {
    return v1Error(400, "invalid_url", "URL must start with http:// or https://.");
  }

  const description =
    typeof body.description === "string" ? body.description : "";

  let events: string[] | undefined;
  if (Array.isArray(body.events)) {
    const cleaned = body.events
      .filter((e: unknown): e is string => typeof e === "string" && e.length > 0)
      .slice(0, 8);
    if (cleaned.length === 0) {
      return v1Error(
        400,
        "invalid_events",
        "'events' must contain at least one event name.",
      );
    }
    events = cleaned;
  }

  let hook: Webhook;
  try {
    hook = await createWebhook({ url, description, events, workspaceId: workspaceOf(auth.key) });
  } catch (err: any) {
    return v1Error(
      400,
      "create_failed",
      err?.message || "Could not create webhook.",
    );
  }

  // Return the secret exactly once, alongside the public fields.
  return NextResponse.json(
    {
      webhook: publicView(hook),
      secret: hook.secret,
    },
    { status: 201 },
  );
}

export const GET = withObservability("/v1/webhooks", getHandler);
export const POST = withObservability("/v1/webhooks", postHandler);
