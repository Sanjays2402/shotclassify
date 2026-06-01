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

// POST /v1/members/{principal}/suspension  -> suspend the member.
// Body is optional { reason?: string } and is forwarded as-is.
export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ principal: string }> },
) {
  const { principal } = await ctx.params;
  const body = await req.text();
  const r = await fetch(
    `${API}/v1/members/${encodeURIComponent(principal)}/suspension`,
    {
      method: "POST",
      headers: authHeaders(req, true),
      body: body && body.length > 0 ? body : "{}",
    },
  );
  return relay(r);
}

// DELETE /v1/members/{principal}/suspension  -> reinstate the member.
export async function DELETE(
  req: NextRequest,
  ctx: { params: Promise<{ principal: string }> },
) {
  const { principal } = await ctx.params;
  const r = await fetch(
    `${API}/v1/members/${encodeURIComponent(principal)}/suspension`,
    { method: "DELETE", headers: authHeaders(req) },
  );
  return relay(r);
}
