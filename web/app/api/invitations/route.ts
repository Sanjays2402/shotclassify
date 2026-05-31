import { NextRequest, NextResponse } from "next/server";
import {
  listInvitations,
  createInvitation,
  isRole,
} from "@/lib/memberstore";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const includeInactive =
    req.nextUrl.searchParams.get("include_inactive") === "true";
  const invitations = await listInvitations({ includeInactive });
  return NextResponse.json({ invitations });
}

export async function POST(req: NextRequest) {
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
  const ttl = Number.isFinite(body?.ttl_days) ? Number(body.ttl_days) : 7;
  try {
    const created = await createInvitation({
      email: typeof body?.email === "string" ? body.email : "",
      role,
      ttl_days: ttl,
      invited_by: req.headers.get("x-actor") || null,
    });
    // Match the FastAPI shape: `token` is returned exactly once, and the
    // client is responsible for surfacing it to the admin before navigating
    // away.
    return NextResponse.json(
      {
        ...created.invitation,
        token: created.token,
        token_display_once: true,
      },
      { status: 201 },
    );
  } catch (err: any) {
    return NextResponse.json(
      { error: "invalid_request", detail: String(err?.message || err) },
      { status: 422 },
    );
  }
}
