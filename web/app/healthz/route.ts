// Liveness probe. Returns 200 as long as the Node process can serve a request.
// Kept dependency-free so it stays green even when the upstream FastAPI is down,
// per Kubernetes guidance: liveness should not flap on dependency failures.
import { NextResponse } from "next/server";
import { resolveRequestId } from "@/lib/metrics";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request): Promise<Response> {
  const rid = resolveRequestId(req.headers);
  return NextResponse.json(
    { status: "ok", uptime_seconds: Math.round(process.uptime()) },
    {
      status: 200,
      headers: {
        "cache-control": "no-store",
        "x-request-id": rid,
      },
    },
  );
}

export async function HEAD(req: Request): Promise<Response> {
  const rid = resolveRequestId(req.headers);
  return new Response(null, {
    status: 200,
    headers: { "cache-control": "no-store", "x-request-id": rid },
  });
}
