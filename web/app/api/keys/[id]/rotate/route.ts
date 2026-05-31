import { NextRequest, NextResponse } from "next/server";
import { rotateKey } from "@/lib/keystore";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(
  _req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  if (!id) {
    return NextResponse.json({ error: "missing id" }, { status: 400 });
  }
  const result = await rotateKey(id);
  if (!result) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  const { hash, ...safe } = result.key;
  return NextResponse.json(
    { key: safe, plaintext: result.plaintext },
    { status: 200 },
  );
}
