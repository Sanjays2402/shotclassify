import { NextRequest, NextResponse } from "next/server";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

const FORWARD_HEADERS = [
  "content-type",
  "x-total-count",
  "x-offset",
  "x-limit",
];

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const target = `${API}/v1/history${url.search}`;
  const res = await fetch(target, { headers: { "x-api-key": KEY } });
  const body = await res.text();
  const headers: Record<string, string> = {};
  for (const h of FORWARD_HEADERS) {
    const v = res.headers.get(h);
    if (v) headers[h] = v;
  }
  if (!headers["content-type"]) headers["content-type"] = "application/json";
  return new NextResponse(body, { status: res.status, headers });
}
