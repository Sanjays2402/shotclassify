import { NextRequest, NextResponse } from "next/server";
import { markRead, deleteOne } from "@/lib/notifications";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string }> };

export async function PATCH(_req: NextRequest, ctx: Ctx) {
  const { id } = await ctx.params;
  const updated = await markRead(id);
  if (!updated) {
    return NextResponse.json(
      { error: { code: "not_found", message: "Notification not found." } },
      { status: 404 },
    );
  }
  return NextResponse.json({ ok: true, item: updated });
}

export async function DELETE(_req: NextRequest, ctx: Ctx) {
  const { id } = await ctx.params;
  const ok = await deleteOne(id);
  if (!ok) {
    return NextResponse.json(
      { error: { code: "not_found", message: "Notification not found." } },
      { status: 404 },
    );
  }
  return NextResponse.json({ ok: true });
}
