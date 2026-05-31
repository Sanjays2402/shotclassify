import { NextRequest, NextResponse } from "next/server";
import {
  listNotifications,
  unreadCount,
  clearAll,
  markAllRead,
} from "@/lib/notifications";
import { paginateNotifs, parseNotifQuery } from "@/lib/notif-query";
// We need the raw store for query mode so we can filter across all items,
// not just the current limit window. listNotifications already caps at
// MAX (200) so reading via it here is safe and avoids exporting internals.
async function readAllForQuery() {
  return listNotifications(200);
}

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const countOnly = url.searchParams.get("count_only") === "1";
  if (countOnly) {
    const unread = await unreadCount();
    return NextResponse.json({ unread });
  }

  // Query mode kicks in if any search/filter/pagination param is present.
  // Otherwise we keep the original {items, unread} shape so existing
  // callers (NotificationBell, the test suite) don't have to change.
  const hasQuery =
    url.searchParams.has("q") ||
    url.searchParams.has("kind") ||
    url.searchParams.has("cursor") ||
    url.searchParams.has("unread_only") ||
    url.searchParams.get("paged") === "1";

  if (hasQuery) {
    const page = parseNotifQuery(url.searchParams);
    const [all, unread] = await Promise.all([
      readAllForQuery(),
      unreadCount(),
    ]);
    const res = paginateNotifs(all, page);
    return NextResponse.json({
      items: res.items,
      total: res.total,
      matched: res.matched,
      unread,
      next_cursor: res.next_cursor,
      filter: res.filter,
    });
  }

  const limitRaw = url.searchParams.get("limit");
  const limit = Math.min(
    Math.max(parseInt(limitRaw || "50", 10) || 50, 1),
    200,
  );
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
