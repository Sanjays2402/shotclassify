import { NextRequest, NextResponse } from "next/server";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  let note: string | null = null;
  try {
    const fd = await req.formData();
    const n = fd.get("note");
    if (typeof n === "string" && n.trim()) note = n.trim();
  } catch {
    /* no body is fine */
  }
  const out = new FormData();
  if (note) out.append("note", note);
  const res = await fetch(
    `${API}/v1/classify/${encodeURIComponent(id)}/reclassify`,
    { method: "POST", headers: { "x-api-key": KEY }, body: out as any }
  );
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
  });
}
