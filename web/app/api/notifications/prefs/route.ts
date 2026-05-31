import { NextRequest, NextResponse } from "next/server";

import { readPrefs, writePrefs } from "@/lib/notification-prefs";
import type { NotificationKind } from "@/lib/notifications";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const VALID_KINDS: NotificationKind[] = [
  "classify.completed",
  "webhook.failed",
  "system",
];

export async function GET() {
  const prefs = await readPrefs();
  return NextResponse.json(prefs);
}

export async function PUT(req: NextRequest) {
  let raw: unknown = null;
  try {
    raw = await req.json();
  } catch {
    return NextResponse.json(
      { error: { code: "invalid_body", message: "JSON body required." } },
      { status: 400 },
    );
  }
  const body = raw as { enabled?: Record<string, unknown> } | null;
  const enabledIn = body?.enabled;
  if (!enabledIn || typeof enabledIn !== "object") {
    return NextResponse.json(
      {
        error: {
          code: "invalid_body",
          message: "Body must be { enabled: { <kind>: boolean } }.",
        },
      },
      { status: 400 },
    );
  }
  const patch: Partial<Record<NotificationKind, boolean>> = {};
  for (const k of VALID_KINDS) {
    const v = (enabledIn as Record<string, unknown>)[k];
    if (typeof v === "boolean") patch[k] = v;
  }
  if (Object.keys(patch).length === 0) {
    return NextResponse.json(
      {
        error: {
          code: "no_known_kinds",
          message: `enabled must include at least one of: ${VALID_KINDS.join(", ")}`,
        },
      },
      { status: 422 },
    );
  }
  const next = await writePrefs(patch);
  return NextResponse.json(next);
}
