import { NextRequest, NextResponse } from "next/server";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

export async function GET() {
  const res = await fetch(`${API}/v1/settings/rules`, { headers: { "x-api-key": KEY } });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json" },
  });
}

export async function PUT(req: NextRequest) {
  const res = await fetch(`${API}/v1/settings/rules`, {
    method: "PUT",
    headers: { "x-api-key": KEY, "content-type": "application/json" },
    body: await req.text(),
  });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json" },
  });
}
