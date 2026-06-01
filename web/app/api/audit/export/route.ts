// Proxy for FastAPI POST /v1/audit/export.
// Streams CSV or JSON Lines back to the browser unchanged. The session
// cookie or workspace API key is forwarded to FastAPI, which enforces
// admin role + read:audit scope + tenant scoping. This route adds no
// auth of its own; FastAPI is authoritative.
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

function authHeaders(req: NextRequest): HeadersInit {
  const h: Record<string, string> = { "content-type": "application/json" };
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

const PASSTHROUGH_HEADERS = [
  "content-type",
  "content-disposition",
  "cache-control",
  "x-audit-manifest",
  "x-audit-format",
];

export async function POST(req: NextRequest) {
  const body = await req.text();
  const upstream = await fetch(`${API}/v1/audit/export`, {
    method: "POST",
    headers: authHeaders(req),
    body: body || "{}",
    cache: "no-store",
  });
  if (!upstream.ok) {
    const text = await upstream.text();
    return new NextResponse(text, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  }
  const headers = new Headers();
  for (const name of PASSTHROUGH_HEADERS) {
    const v = upstream.headers.get(name);
    if (v) headers.set(name, v);
  }
  return new NextResponse(upstream.body, { status: 200, headers });
}
