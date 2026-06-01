// Proxy for FastAPI /v1/access-reviews. The FastAPI side enforces the
// admin role, requires a resolved tenant, and scopes every read and
// write to the caller's workspace. This route forwards the browser
// session cookie (or the workspace API key in dev) verbatim.
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

function authHeaders(req: NextRequest, extra: Record<string, string> = {}): HeadersInit {
  const h: Record<string, string> = { ...extra };
  const cookie = req.headers.get("cookie");
  if (cookie && cookie.includes("sc_session=")) {
    h["cookie"] = cookie;
  } else if (KEY) {
    h["x-api-key"] = KEY;
  }
  const tenant = req.headers.get("x-tenant");
  if (tenant) h["x-tenant"] = tenant;
  const csrf = req.headers.get("x-csrf");
  if (csrf) h["x-csrf"] = csrf;
  return h;
}

async function relay(upstream: Response): Promise<NextResponse> {
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
    },
  });
}

export async function GET(req: NextRequest) {
  const r = await fetch(`${API}/v1/access-reviews`, {
    headers: authHeaders(req),
    cache: "no-store",
  });
  return relay(r);
}

export async function POST(req: NextRequest) {
  const body = await req.text();
  const r = await fetch(`${API}/v1/access-reviews`, {
    method: "POST",
    headers: authHeaders(req, { "content-type": "application/json" }),
    body,
    cache: "no-store",
  });
  return relay(r);
}
