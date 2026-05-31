// GET /v1/usage — returns calling key's identity and usage counters.
// Useful for customers building quota meters in their own dashboards.
import { NextRequest, NextResponse } from "next/server";
import { authenticate, keyHeaders } from "@/lib/v1auth";
import { withObservability } from "@/lib/observability";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function getHandler(req: NextRequest): Promise<Response> {
  const auth = await authenticate(req);
  if (auth instanceof NextResponse) return auth;
  const { key } = auth;
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
    },
    { headers: keyHeaders(key) },
  );
}

export const GET = withObservability("/v1/usage", getHandler);
