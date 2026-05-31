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
  // Public registry: matches the procurement reviewer experience of a
  // direct curl call so no credentials are forwarded.
  const r = await fetch(`${API}/v1/trust/incidents`, { cache: "no-store" });
  return relay(r);
}
