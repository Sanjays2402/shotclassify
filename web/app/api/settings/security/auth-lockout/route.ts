// Proxy for FastAPI /v1/settings/security/auth-lockout (GET + PUT).
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

function authHeaders(req: NextRequest, withJson = false): HeadersInit {
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
  const csrf = req.headers.get("x-csrf-token");
  if (csrf) h["x-csrf-token"] = csrf;
  if (withJson) h["content-type"] = "application/json";
  return h;
}

const URL_PATH = `${API}/v1/settings/security/auth-lockout`;

export async function GET(req: NextRequest) {
  const r = await fetch(URL_PATH, { headers: authHeaders(req), cache: "no-store" });
  const text = await r.text();
  return new NextResponse(text, {
    status: r.status,
    headers: { "content-type": r.headers.get("content-type") ?? "application/json" },
  });
}

export async function PUT(req: NextRequest) {
  const body = await req.text();
  const r = await fetch(URL_PATH, {
    method: "PUT",
    headers: authHeaders(req, true),
    body,
    cache: "no-store",
  });
  const text = await r.text();
  return new NextResponse(text, {
    status: r.status,
    headers: { "content-type": r.headers.get("content-type") ?? "application/json" },
  });
}
