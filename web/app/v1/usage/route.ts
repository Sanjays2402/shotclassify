// GET /v1/usage — returns calling key's identity and usage counters.
// Useful for customers building quota meters in their own dashboards.
import { NextRequest, NextResponse } from "next/server";
import { authenticate, keyHeaders, rateSnapshot } from "@/lib/v1auth";
import { getWorkspaceConfig } from "@/lib/ratelimit";
import { workspaceOf } from "@/lib/keystore";
import { withObservability } from "@/lib/observability";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function getHandler(req: NextRequest): Promise<Response> {
  const auth = await authenticate(req);
  if (auth instanceof NextResponse) return auth;
  const { key } = auth;
  const cfg = await getWorkspaceConfig(workspaceOf(key));
  const snap = rateSnapshot(key);
  return NextResponse.json(
    {
      key: {
        id: key.id,
        name: key.name,
        prefix: key.prefix,
        created_at: key.created_at,
        last_used_at: key.last_used_at,
        usage_count: key.usage_count,
        scopes: key.scopes ?? ["read", "write"],
      },
      rate_limit: {
        plan: cfg.plan,
        limits: cfg.limits,
        used: snap,
      },
    },
    { headers: keyHeaders(key, auth.rateHeaders) },
  );
}

export const GET = withObservability("/v1/usage", getHandler);
