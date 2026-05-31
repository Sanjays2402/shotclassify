import { NextRequest, NextResponse } from "next/server";
import {
  listMembers,
  upsertMember,
  isRole,
} from "@/lib/memberstore";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const members = await listMembers();
  return NextResponse.json({ members, roles: ["admin", "operator", "viewer"] });
}

export async function POST(req: NextRequest) {
  let body: any = {};
  try {
    body = await req.json();
  } catch {
    /* empty body falls through */
  }
  const email = typeof body?.email === "string" ? body.email : "";
  const role = body?.role;
  if (!isRole(role)) {
    return NextResponse.json(
      { error: "invalid_role", detail: "role must be admin, operator, or viewer." },
      { status: 422 },
    );
  }
  try {
    const member = await upsertMember({
      email,
      role,
      invited_by: req.headers.get("x-actor") || null,
    });
    return NextResponse.json({ member }, { status: 201 });
  } catch (err: any) {
    return NextResponse.json(
      { error: "invalid_request", detail: String(err?.message || err) },
      { status: 422 },
    );
  }
}
