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
  return h;
}

export async function POST(req: NextRequest) {
  const body = await req.text();
  const url = new URL(req.url);
  const res = await fetch(`${API}/v1/history/bulk${url.search}`, {
    method: "POST",
    headers: authHeaders(req),
    body,
  });
  const text = await res.text();
  const headers: Record<string, string> = {
    "content-type": res.headers.get("content-type") ?? "application/json",
  };
  const dryRun = res.headers.get("x-dry-run");
  if (dryRun) headers["x-dry-run"] = dryRun;
  return new NextResponse(text, { status: res.status, headers });
}
