import { NextRequest, NextResponse } from "next/server";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

export async function POST(req: NextRequest) {
  const fd = await req.formData();
  const res = await fetch(`${API}/v1/classify`, {
    method: "POST",
    headers: { "x-api-key": KEY },
    body: fd as any,
  });
  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
  });
}
