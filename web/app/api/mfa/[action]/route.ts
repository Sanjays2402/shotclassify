import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

function authHeaders(req: NextRequest): HeadersInit {
  const h: Record<string, string> = { "content-type": "application/json" };
  const cookie = req.headers.get("cookie");
  if (cookie && cookie.includes("sc_session=")) h["cookie"] = cookie;
  else if (KEY) h["x-api-key"] = KEY;
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

async function forward(req: NextRequest, path: string, method: string) {
  const body = await req.text();
  const r = await fetch(`${API}${path}`, {
    method,
    headers: authHeaders(req),
    body: body || "{}",
    cache: "no-store",
  });
  return relay(r);
}

export async function POST(req: NextRequest) {
  // /api/mfa/[action] where action is verify or challenge
  const parts = req.nextUrl.pathname.split("/");
  const action = parts[parts.length - 1];
  if (!["verify", "challenge"].includes(action)) {
    return NextResponse.json({ error: "unknown action" }, { status: 404 });
  }
  return forward(req, `/v1/mfa/${action}`, "POST");
}

export async function DELETE(req: NextRequest) {
  return forward(req, "/v1/mfa", "DELETE");
}
