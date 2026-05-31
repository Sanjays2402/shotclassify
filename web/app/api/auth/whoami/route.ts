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
  return h;
}

export async function GET(req: NextRequest) {
  try {
    const res = await fetch(`${API}/auth/whoami`, {
      headers: authHeaders(req),
      cache: "no-store",
    });
    if (res.status === 401 || res.status === 403) {
      return NextResponse.json({ principal: null }, { status: 200 });
    }
    const text = await res.text();
    let parsed: unknown = null;
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = { principal: null };
    }
    return NextResponse.json(parsed, { status: 200 });
  } catch {
    return NextResponse.json(
      { principal: null, error: "backend_unreachable" },
      { status: 200 },
    );
  }
}
