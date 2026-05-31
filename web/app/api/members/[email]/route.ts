import { NextRequest, NextResponse } from "next/server";
import {
  listMembers,
  upsertMember,
  removeMember,
  countAdmins,
  isRole,
} from "@/lib/memberstore";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ email: string }> };

function decodeEmail(raw: string): string {
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

export async function PUT(req: NextRequest, { params }: Ctx) {
  const { email: rawEmail } = await params;
  const email = decodeEmail(rawEmail);
  let body: any = {};
  try {
    body = await req.json();
  } catch {
    /* empty body falls through to validation */
  }
  const role = body?.role;
  if (!isRole(role)) {
    return NextResponse.json(
      { error: "invalid_role", detail: "role must be admin, operator, or viewer." },
      { status: 422 },
    );
  }
  if (role !== "admin") {
    const members = await listMembers();
    const current = members.find((m) => m.email === email.toLowerCase());
    if (current?.role === "admin" && countAdmins(members, email) === 0) {
      return NextResponse.json(
        {
          error: "last_admin",
          detail: "Cannot demote the last admin of this workspace.",
        },
        { status: 409 },
      );
    }
  }
  try {
    const member = await upsertMember({
      email,
      role,
      invited_by: req.headers.get("x-actor") || null,
    });
    return NextResponse.json({ member });
  } catch (err: any) {
    return NextResponse.json(
      { error: "invalid_request", detail: String(err?.message || err) },
      { status: 422 },
    );
  }
}

export async function DELETE(_req: NextRequest, { params }: Ctx) {
  const { email: rawEmail } = await params;
  const email = decodeEmail(rawEmail);
  const members = await listMembers();
  const current = members.find((m) => m.email === email.toLowerCase());
  if (current?.role === "admin" && countAdmins(members, email) === 0) {
    return NextResponse.json(
      {
        error: "last_admin",
        detail: "Cannot remove the last admin of this workspace.",
      },
      { status: 409 },
    );
  }
  const removed = await removeMember(email);
  if (!removed) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }
  return NextResponse.json({ removed: true, email });
}
