import { NextResponse } from "next/server";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

export async function GET() {
  const res = await fetch(`${API}/v1/history/stats`, {
    headers: { "x-api-key": KEY },
  });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
  });
}
