// POST /api/billing/intent — record that a signed-in (or anonymous)
// visitor wants to upgrade to a paid plan. Until Stripe is wired this
// is the source of truth for "who clicked Upgrade".
//
// GET returns the catalog so the pricing page can render the same
// data the server sees.
import { NextRequest, NextResponse } from "next/server";

import { PLANS, recordIntent } from "@/lib/billing";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ plans: PLANS });
}

export async function POST(req: NextRequest) {
  let raw: unknown = null;
  try {
    raw = await req.json();
  } catch {
    return NextResponse.json(
      { error: { code: "invalid_body", message: "JSON body required." } },
      { status: 400 },
    );
  }
  const body = (raw ?? {}) as {
    plan?: unknown;
    email?: unknown;
    company?: unknown;
    note?: unknown;
    source?: unknown;
  };
  if (typeof body.plan !== "string" || !body.plan) {
    return NextResponse.json(
      {
        error: {
          code: "invalid_body",
          message: "Field 'plan' is required.",
        },
      },
      { status: 400 },
    );
  }
  const result = await recordIntent({
    plan: body.plan,
    email: typeof body.email === "string" ? body.email : null,
    company: typeof body.company === "string" ? body.company : null,
    note: typeof body.note === "string" ? body.note : null,
    source: typeof body.source === "string" ? body.source : "pricing",
  });
  if (!result.ok) {
    const status = result.error.code === "unknown_plan" ? 404 : 400;
    return NextResponse.json({ error: result.error }, { status });
  }
  return NextResponse.json(
    { intent: result.intent },
    { status: 201, headers: { "cache-control": "no-store" } },
  );
}
