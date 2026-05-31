import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";

export async function POST(req: NextRequest) {
  const cookie = req.headers.get("cookie") ?? "";
  try {
    await fetch(`${API}/auth/logout`, {
      method: "POST",
      headers: cookie ? { cookie } : {},
      cache: "no-store",
    });
  } catch {
    // best effort; we still clear the cookie locally below
  }
  const res = NextResponse.json({ ok: true });
  // Clear the session cookie at the web origin too
  res.cookies.set("sc_session", "", { path: "/", maxAge: 0 });
  return res;
}
