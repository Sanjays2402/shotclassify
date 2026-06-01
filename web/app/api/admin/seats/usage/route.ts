// Proxy for FastAPI /v1/admin/seats/usage. The FastAPI side enforces the
// admin role, requires a resolved tenant, and scopes every row to the
// caller's workspace. This route forwards the browser session cookie or
// the workspace API key and relays the response verbatim.
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

function authHeaders(req: NextRequest): HeadersInit {
  const h: Record<string, string> = {};
  const cookie = req.headers.get("cookie");
  if (cookie && cookie.includes("sc_session=")) {
    h["cookie"] = cookie;
  } else if (KEY) {
    h["x-api-key"] = KEY;
  }
  const tenant = req.headers.get("x-tenant");
  if (tenant) h["x-tenant"] = tenant;
  return h;
}

export async function GET(req: NextRequest) {
  const r = await fetch(`${API}/v1/admin/seats/usage`, {
    headers: authHeaders(req),
    cache: "no-store",
  });
  const text = await r.text();
  return new NextResponse(text, {
    status: r.status,
    headers: {
      "content-type": r.headers.get("content-type") ?? "application/json",
    },
  });
}
