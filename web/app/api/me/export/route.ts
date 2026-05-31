import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

// Streams the GDPR data bundle as a downloadable JSON file. Reuses the
// same auth precedence as /api/me: forward the browser session cookie
// when present, otherwise authenticate with the server-side API key.
export async function GET(req: NextRequest) {
  const headers: Record<string, string> = {};
  const cookie = req.headers.get("cookie");
  if (cookie && cookie.includes("sc_session=")) {
    headers["cookie"] = cookie;
  } else if (KEY) {
    headers["x-api-key"] = KEY;
  }
  const upstream = await fetch(`${API}/v1/me/data`, {
    headers,
    cache: "no-store",
  });
  if (!upstream.ok) {
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: { "content-type": "application/json" },
    });
  }
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "content-disposition": `attachment; filename="shotclassify-data-${stamp}.json"`,
      "cache-control": "no-store",
    },
  });
}
