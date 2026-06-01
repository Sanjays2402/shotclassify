// Per-sink proxy: GET/DELETE /v1/audit/sinks/:id and POST /:id/test.
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

async function relay(res: Response) {
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: {
      "content-type": res.headers.get("content-type") ?? "application/json",
    },
  });
}

type Ctx = { params: Promise<{ id: string }> };

export async function GET(req: NextRequest, ctx: Ctx) {
  const { id } = await ctx.params;
  const r = await fetch(`${API}/v1/audit/sinks/${encodeURIComponent(id)}`, {
    headers: authHeaders(req),
    cache: "no-store",
  });
  return relay(r);
}

export async function DELETE(req: NextRequest, ctx: Ctx) {
  const { id } = await ctx.params;
  const r = await fetch(`${API}/v1/audit/sinks/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: authHeaders(req),
  });
  return relay(r);
}

export async function POST(req: NextRequest, ctx: Ctx) {
  // Mounted at /audit-sinks/[id]; the page calls the same URL to fire a
  // probe event. The FastAPI route is /v1/audit/sinks/:id/test.
  const { id } = await ctx.params;
  const r = await fetch(`${API}/v1/audit/sinks/${encodeURIComponent(id)}/test`, {
    method: "POST",
    headers: authHeaders(req),
  });
  return relay(r);
}
