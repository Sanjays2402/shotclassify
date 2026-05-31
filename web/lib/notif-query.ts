// Pure search/filter/pagination helpers for the notifications inbox.
// Kept separate from lib/notifications.ts so the predicates can be
// unit-tested without touching the filesystem and so the API route can
// reuse them.
import type { Notification, NotificationKind } from "./notifications";

export type NotifFilter = {
  q?: string | null;
  kind?: string | null;
  unread_only?: boolean;
};

export type NotifPage = {
  q?: string | null;
  kind?: string | null;
  unread_only?: boolean;
  cursor?: number;
  limit?: number;
};

export const ALL_NOTIF_KINDS: NotificationKind[] = [
  "classify.completed",
  "webhook.failed",
  "system",
];

function normaliseQuery(q: string | null | undefined): string {
  if (typeof q !== "string") return "";
  return q.trim().toLowerCase().slice(0, 200);
}

function normaliseKind(kind: string | null | undefined): NotificationKind | null {
  if (typeof kind !== "string") return null;
  const t = kind.trim();
  if (!t || t === "all") return null;
  return (ALL_NOTIF_KINDS as string[]).includes(t)
    ? (t as NotificationKind)
    : null;
}

export function matchesNotif(
  n: Notification,
  filter: NotifFilter,
): boolean {
  const k = normaliseKind(filter.kind ?? null);
  if (k && n.kind !== k) return false;
  if (filter.unread_only && n.read_at) return false;
  const q = normaliseQuery(filter.q ?? null);
  if (q) {
    const hay =
      `${n.title} ${n.body} ${n.kind}`.toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

export type PaginatedNotifs = {
  items: Notification[];
  total: number;
  matched: number;
  unread: number;
  next_cursor: number | null;
  filter: {
    q: string;
    kind: string;
    unread_only: boolean;
  };
};

export function paginateNotifs(
  all: Notification[],
  page: NotifPage,
): PaginatedNotifs {
  const limit = Math.min(Math.max(Math.floor(page.limit ?? 25), 1), 100);
  const cursor = Math.max(Math.floor(page.cursor ?? 0), 0);
  const q = normaliseQuery(page.q ?? null);
  const kind = normaliseKind(page.kind ?? null);
  const unread_only = !!page.unread_only;
  const filter: NotifFilter = { q, kind, unread_only };

  const filtered = all.filter((n) => matchesNotif(n, filter));
  const slice = filtered.slice(cursor, cursor + limit);
  const next = cursor + limit < filtered.length ? cursor + limit : null;

  return {
    items: slice,
    total: all.length,
    matched: filtered.length,
    unread: all.reduce((acc, n) => acc + (n.read_at ? 0 : 1), 0),
    next_cursor: next,
    filter: {
      q,
      kind: kind ?? "all",
      unread_only,
    },
  };
}

export function parseNotifQuery(
  params: URLSearchParams,
): NotifPage {
  const cursorRaw = params.get("cursor");
  const limitRaw = params.get("limit");
  const cursor = cursorRaw ? parseInt(cursorRaw, 10) : 0;
  const limit = limitRaw ? parseInt(limitRaw, 10) : 25;
  return {
    q: params.get("q"),
    kind: params.get("kind"),
    unread_only: params.get("unread_only") === "1",
    cursor: Number.isFinite(cursor) ? cursor : 0,
    limit: Number.isFinite(limit) ? limit : 25,
  };
}
