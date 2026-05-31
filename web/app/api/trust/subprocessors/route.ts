import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";

async function relay(res: Response) {
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: {
      "content-type": res.headers.get("content-type") ?? "application/json",
    },
  });
}

export async function GET(_req: NextRequest) {
  // Public endpoint: forward without auth headers so the procurement
  // reviewer experience matches a direct curl against the API.
  const r = await fetch(`${API}/v1/trust/subprocessors`, {
    cache: "no-store",
  });
  return relay(r);
}
