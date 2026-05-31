import { NextRequest, NextResponse } from "next/server";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await req.formData();
  const category = body.get("category");
  if (typeof category !== "string" || !category) {
    return NextResponse.json({ error: "category is required" }, { status: 422 });
  }
  const fd = new FormData();
  fd.append("category", category);
  const res = await fetch(
    `${API}/v1/classify/${encodeURIComponent(id)}/correct`,
    { method: "POST", headers: { "x-api-key": KEY }, body: fd as any }
  );
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
  });
}
