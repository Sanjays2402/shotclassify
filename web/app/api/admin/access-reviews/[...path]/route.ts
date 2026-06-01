// Proxy for FastAPI per-review endpoints. Read, decide on items, apply
// (with optional ?dry_run=true preview), cancel. Tenant scoping and
// last-admin protection are enforced server-side; this route only relays.
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
      ...(upstream.headers.get("content-disposition")
        ? { "content-disposition": upstream.headers.get("content-disposition")! }
        : {}),
    },
  });
}

type Ctx = { params: Promise<{ path: string[] }> };

function buildUrl(parts: string[], search: string): string {
  const tail = parts.join("/");
  return `${API}/v1/access-reviews/${tail}${search}`;
}

export async function GET(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  const url = new URL(req.url);
  const r = await fetch(buildUrl(path, url.search), {
    headers: authHeaders(req),
    cache: "no-store",
  });
  return relay(r);
}

export async function POST(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  const url = new URL(req.url);
  const body = await req.text();
  const r = await fetch(buildUrl(path, url.search), {
    method: "POST",
    headers: authHeaders(req, { "content-type": "application/json" }),
    body: body || "{}",
    cache: "no-store",
  });
  return relay(r);
}

export async function PUT(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  const url = new URL(req.url);
  const body = await req.text();
  const r = await fetch(buildUrl(path, url.search), {
    method: "PUT",
    headers: authHeaders(req, { "content-type": "application/json" }),
    body,
    cache: "no-store",
  });
  return relay(r);
}
