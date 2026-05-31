import { NextRequest, NextResponse } from "next/server";
import { acceptInvitation } from "@/lib/memberstore";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  let body: any = {};
  try {
    body = await req.json();
  } catch {
    /* empty body falls through */
  }
  const token = typeof body?.token === "string" ? body.token : "";
  const email = typeof body?.email === "string" ? body.email : "";
  if (!token || !email) {
    return NextResponse.json(
      { error: "invalid_request", detail: "token and email are required." },
      { status: 422 },
    );
  }
  const result = await acceptInvitation(token, email);
  if (!result) {
    return NextResponse.json(
      { error: "not_found", detail: "Invitation is invalid, expired, or already used." },
      { status: 404 },
    );
  }
  return NextResponse.json(result);
}
