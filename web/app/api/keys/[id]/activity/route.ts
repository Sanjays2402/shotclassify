// Proxy for FastAPI /v1/api-keys/{id}/activity (admin + read:audit).
//
// The browser session cookie or workspace API key is forwarded to FastAPI,
// which enforces RBAC (admin role), scope (read:audit) and tenant scoping.
// This route adds no auth of its own; FastAPI is authoritative and returns
// 404 for cross-tenant lookups so guessing a key id from another workspace
// cannot reveal whether it exists.
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

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  if (!id) {
    return NextResponse.json({ error: "missing id" }, { status: 400 });
  }
  const url = new URL(req.url);
  const limit = Math.max(
    1,
    Math.min(500, Number.parseInt(url.searchParams.get("limit") || "50", 10) || 50),
  );
  const r = await fetch(
    `${API}/v1/api-keys/${encodeURIComponent(id)}/activity?limit=${limit}`,
    { headers: authHeaders(req), cache: "no-store" },
  );
  const text = await r.text();
  return new NextResponse(text, {
    status: r.status,
    headers: {
      "content-type": r.headers.get("content-type") ?? "application/json",
    },
  });
}
