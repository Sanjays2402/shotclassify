// Proxy for FastAPI /v1/workspace/data.
// Streams the ZIP export through unchanged so the browser triggers a
// download. DELETE forwards confirm/dry_run and any MFA OTP header.
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
  const mfa = req.headers.get("x-mfa-otp");
  if (mfa) h["x-mfa-otp"] = mfa;
  return h;
}

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const qs = url.searchParams.toString();
  const upstream = await fetch(
    `${API}/v1/workspace/data${qs ? "?" + qs : ""}`,
    { headers: authHeaders(req), cache: "no-store" },
  );
  if (!upstream.ok) {
    const text = await upstream.text();
    return new NextResponse(text, {
      status: upstream.status,
      headers: { "content-type": "application/json" },
    });
  }
  const contentType =
    upstream.headers.get("content-type") || "application/octet-stream";
  const disposition = upstream.headers.get("content-disposition") || "";
  const headers: Record<string, string> = {
    "content-type": contentType,
    "cache-control": "no-store",
  };
  if (disposition) headers["content-disposition"] = disposition;
  return new NextResponse(upstream.body, { status: 200, headers });
}

export async function DELETE(req: NextRequest) {
  const url = new URL(req.url);
  const qs = url.searchParams.toString();
  const upstream = await fetch(
    `${API}/v1/workspace/data${qs ? "?" + qs : ""}`,
    { method: "DELETE", headers: authHeaders(req), cache: "no-store" },
  );
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": "application/json" },
  });
}
