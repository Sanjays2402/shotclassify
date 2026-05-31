import { NextRequest, NextResponse } from "next/server";
import {
  listNotifications,
  unreadCount,
  clearAll,
  markAllRead,
} from "@/lib/notifications";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const limitRaw = url.searchParams.get("limit");
  const countOnly = url.searchParams.get("count_only") === "1";
  const limit = Math.min(
    Math.max(parseInt(limitRaw || "50", 10) || 50, 1),
    200,
  );
  if (countOnly) {
    const unread = await unreadCount();
    return NextResponse.json({ unread });
  }
  const [items, unread] = await Promise.all([
    listNotifications(limit),
    unreadCount(),
  ]);
  return NextResponse.json({ items, unread });
}

export async function POST(req: NextRequest) {
  // Accepted bulk actions: mark_all_read, clear
  let action = "";
  try {
    const body = (await req.json()) as { action?: string };
    action = (body?.action || "").trim();
  } catch {
    return NextResponse.json(
      { error: { code: "invalid_body", message: "JSON body required." } },
      { status: 400 },
    );
  }
  if (action === "mark_all_read") {
    const n = await markAllRead();
    return NextResponse.json({ ok: true, marked: n });
  }
  if (action === "clear") {
    const n = await clearAll();
    return NextResponse.json({ ok: true, cleared: n });
  }
  return NextResponse.json(
    {
      error: {
        code: "unknown_action",
        message: "action must be 'mark_all_read' or 'clear'",
      },
    },
    { status: 400 },
  );
}
