// Proxy for FastAPI /v1/workspace/seats.
// The admin UI reads the current seat limit and updates it via PUT.
// Both verbs require the admin role; PUT additionally requires a fresh
// MFA step-up token (forwarded as x-mfa-otp). 402 responses surface
// the structured seat_limit_exceeded payload to the client unchanged.
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

export async function GET(req: NextRequest) {
  const r = await fetch(`${API}/v1/workspace/seats`, {
    headers: authHeaders(req),
    cache: "no-store",
  });
  return relay(r);
}

export async function PUT(req: NextRequest) {
  const body = await req.text();
  const r = await fetch(`${API}/v1/workspace/seats`, {
    method: "PUT",
    headers: authHeaders(req, true),
    body,
  });
  return relay(r);
}
