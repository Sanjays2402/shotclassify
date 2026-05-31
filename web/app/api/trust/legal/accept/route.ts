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
  const stepUp = req.headers.get("x-mfa-step-up");
  if (stepUp) h["x-mfa-step-up"] = stepUp;
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

export async function POST(req: NextRequest) {
  const body = await req.text();
  const r = await fetch(`${API}/v1/trust/legal/accept`, {
    method: "POST",
    headers: authHeaders(req, true),
    body,
    cache: "no-store",
  });
  return relay(r);
}
