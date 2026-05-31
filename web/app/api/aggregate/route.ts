import { NextRequest, NextResponse } from "next/server";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const target = `${API}/v1/history/aggregate${url.search}`;
  const res = await fetch(target, { headers: { "x-api-key": KEY } });
  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
  });
}
