import { NextRequest, NextResponse } from "next/server";
import { listKeys, createKey } from "@/lib/keystore";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const keys = await listKeys();
  // Never leak the hash.
  return NextResponse.json({
    keys: keys.map(({ hash, ...rest }) => rest),
  });
}

export async function POST(req: NextRequest) {
  let body: any = {};
  try {
    body = await req.json();
  } catch {
    /* empty body is ok */
  }
  const name = typeof body?.name === "string" ? body.name : "";
  const scopes = body?.scopes;
  const { key, plaintext } = await createKey(name, scopes, body?.workspace_id);
  const { hash, ...safe } = key;
  return NextResponse.json({ key: safe, plaintext }, { status: 201 });
}
