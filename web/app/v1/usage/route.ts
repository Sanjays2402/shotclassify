// GET /v1/usage — returns calling key's identity and usage counters.
// Useful for customers building quota meters in their own dashboards.
import { NextRequest, NextResponse } from "next/server";
import { authenticate, keyHeaders } from "@/lib/v1auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
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
