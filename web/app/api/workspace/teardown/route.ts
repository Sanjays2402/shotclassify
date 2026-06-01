// Proxy for FastAPI /v1/workspace/teardown.
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

function authHeaders(req: NextRequest): Record<string, string> {
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
  return h;
}

async function passthrough(upstream: Response) {
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": "application/json" },
  });
}

export async function GET(req: NextRequest) {
  const upstream = await fetch(`${API}/v1/workspace/teardown`, {
    headers: authHeaders(req),
    cache: "no-store",
  });
  return passthrough(upstream);
}

export async function POST(req: NextRequest) {
  const url = new URL(req.url);
  const qs = url.searchParams.toString();
  const body = await req.text();
  const upstream = await fetch(
    `${API}/v1/workspace/teardown${qs ? "?" + qs : ""}`,
    {
      method: "POST",
      headers: { ...authHeaders(req), "content-type": "application/json" },
      body,
      cache: "no-store",
    },
  );
  return passthrough(upstream);
}

export async function DELETE(req: NextRequest) {
  const upstream = await fetch(`${API}/v1/workspace/teardown`, {
    method: "DELETE",
    headers: authHeaders(req),
    cache: "no-store",
  });
  return passthrough(upstream);
}
