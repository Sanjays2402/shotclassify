import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

function authHeaders(req: NextRequest, includeJson = false): HeadersInit {
  const h: Record<string, string> = {};
  const cookie = req.headers.get("cookie");
  if (cookie && cookie.includes("sc_session=")) {
    h["cookie"] = cookie;
  } else if (KEY) {
    h["x-api-key"] = KEY;
  }
  const tenant = req.headers.get("x-tenant");
  if (tenant) h["x-tenant"] = tenant;
  const mfa = req.headers.get("x-mfa-otp");
  if (mfa) h["x-mfa-otp"] = mfa;
  if (includeJson) h["content-type"] = "application/json";
  return h;
}

async function relay(res: Response) {
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: {
      "content-type": res.headers.get("content-type") ?? "application/json",
    },
  });
}

// List active keys plus their current access windows so the UI can render
// the whole tenant in a single page without an N+1 fetch per key.
export async function GET(req: NextRequest) {
  const r = await fetch(`${API}/v1/api-keys`, {
    headers: authHeaders(req),
    cache: "no-store",
  });
  return relay(r);
}
