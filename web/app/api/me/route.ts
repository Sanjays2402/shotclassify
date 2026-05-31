import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

// Build headers that prefer the browser's session cookie when present
// (so an OAuth-signed-in operator sees their own data), falling back to
// the server-side API key so the page works in single-tenant deploys.
function authHeaders(req: NextRequest): HeadersInit {
  const h: Record<string, string> = {};
  const cookie = req.headers.get("cookie");
  if (cookie && cookie.includes("sc_session=")) {
    h["cookie"] = cookie;
  } else if (KEY) {
    h["x-api-key"] = KEY;
  }
  return h;
}

export async function GET(req: NextRequest) {
  const res = await fetch(`${API}/v1/me/data`, {
    headers: authHeaders(req),
    cache: "no-store",
  });
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: {
      "content-type": res.headers.get("content-type") ?? "application/json",
    },
  });
}

export async function DELETE(req: NextRequest) {
  const url = new URL(req.url);
  const confirm = url.searchParams.get("confirm") ?? "";
  const res = await fetch(
    `${API}/v1/me/data?confirm=${encodeURIComponent(confirm)}`,
    {
      method: "DELETE",
      headers: authHeaders(req),
    },
  );
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: {
      "content-type": res.headers.get("content-type") ?? "application/json",
    },
  });
}
