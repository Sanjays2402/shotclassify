import { NextRequest, NextResponse } from "next/server";
import { revokeInvitation } from "@/lib/memberstore";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string }> };

export async function DELETE(_req: NextRequest, { params }: Ctx) {
  const { id } = await params;
  const result = await revokeInvitation(id);
  if (result === null) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }
  return NextResponse.json({ invitation: result });
}
